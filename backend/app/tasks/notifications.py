"""
Background notification sender.

Periodically checks all active bus assignments against user notification
settings and sends FCM push notifications when a bus ETA to the user's
subscribed stop is within their configured lead_time_minutes.

Architecture:
  - Runs as a background asyncio task alongside the FastAPI app
  - On each tick (default 60s), queries all notification_settings
  - For each setting, looks up the live ETA for the route+stop
  - If live_eta <= lead_time_minutes → sends FCM push notification
  - Tracks sent notifications to avoid duplicate alerts (Redis TTL)
"""

import asyncio
import logging
import time
import httpx

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.notification_setting import NotificationSetting
from app.models.route import RouteStop
from app.models.stop import Stop
from app.utils.redis_client import get_redis, route_stop_key

logger = logging.getLogger(__name__)

FCM_SEND_URL = "https://fcm.googleapis.com/fcm/send"
CHECK_INTERVAL_SECONDS = 60
# How long to remember we sent a notification (prevent re-alert)
NOTIFICATION_COOLDOWN_SECONDS = 300  # 5 minutes


async def _send_fcm_notification(
    device_token: str, title: str, body: str, data: dict,
) -> bool:
    """Send a push notification using FCM Legacy HTTP API.

    Returns True on success. Silently returns False if FCM_SERVER_KEY
    not configured or if the send fails.
    """
    settings = get_settings()
    if not settings.FCM_SERVER_KEY:
        return False

    payload = {
        "to": device_token,
        "notification": {
            "title": title,
            "body": body,
            "sound": "default",
            "click_action": "FLUTTER_NOTIFICATION_CLICK",
        },
        "data": {k: str(v) for k, v in data.items()},
        "priority": "high",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                FCM_SEND_URL,
                headers={
                    "Authorization": f"key={settings.FCM_SERVER_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if resp.status_code == 200:
            result = resp.json()
            if result.get("success", 0) > 0:
                logger.info(
                    "FCM notification sent to %s...%s",
                    device_token[:8], device_token[-4:],
                )
                return True
            else:
                logger.warning("FCM send failed: %s", result)
        else:
            logger.warning("FCM HTTP %d: %s", resp.status_code, resp.text[:200])
    except Exception:
        logger.exception("FCM send error for token %s...%s", device_token[:8], device_token[-4:])

    return False


async def _get_user_fcm_token(user_id: int) -> str | None:
    """Retrieve stored FCM token from Redis."""
    try:
        r = await get_redis()
        return await r.get(f"fcm:{user_id}")
    except Exception:
        return None


async def _already_notified(setting_id: int, stop_id: int | None) -> bool:
    """Check if we already sent a notification recently (cooldown)."""
    try:
        r = await get_redis()
        cooldown_key = f"notif_sent:{setting_id}:stop:{stop_id}"
        return await r.exists(cooldown_key) > 0
    except Exception:
        return False


async def _mark_notified(setting_id: int, stop_id: int | None) -> None:
    """Mark that we sent a notification (set cooldown)."""
    try:
        r = await get_redis()
        cooldown_key = f"notif_sent:{setting_id}:stop:{stop_id}"
        await r.set(cooldown_key, "1", ex=NOTIFICATION_COOLDOWN_SECONDS)
    except Exception:
        pass


async def check_and_send_notifications():
    """Main check loop: compare live ETAs against user notification preferences."""
    settings = get_settings()
    if not settings.FCM_SERVER_KEY:
        return

    async with AsyncSessionLocal() as db:
        try:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            result = await db.execute(
                select(NotificationSetting)
                .options(
                    selectinload(NotificationSetting.user),
                    selectinload(NotificationSetting.route),
                )
            )
            all_settings = list(result.scalars().all())
            if not all_settings:
                return

            redis = await get_redis()

            for ns in all_settings:
                try:
                    user = ns.user
                    if not user:
                        continue

                    fcm_token = await _get_user_fcm_token(user.id)
                    if not fcm_token:
                        continue

                    route = ns.route
                    if not route:
                        continue

                    route_number = route.route_number

                    # If a specific stop is set, only check that stop
                    if ns.stop_id:
                        stop_eta_key = route_stop_key(route_number, ns.stop_id)
                        eta_data = await redis.hgetall(stop_eta_key)

                        if not eta_data:
                            continue

                        try:
                            eta_seconds = float(eta_data.get("eta_seconds", 0))
                            computed_at = float(eta_data.get("computed_at", 0))
                        except (TypeError, ValueError):
                            continue

                        if computed_at <= 0:
                            continue

                        elapsed = max(0.0, time.time() - computed_at)
                        live_eta = max(0, int(eta_seconds - elapsed))
                        lead_time_seconds = ns.lead_time_minutes * 60

                        if 0 < live_eta <= lead_time_seconds:
                            # Check cooldown to avoid spamming
                            if await _already_notified(ns.id, ns.stop_id):
                                continue

                            stop_name = eta_data.get("stop_name", "your stop")
                            plate = eta_data.get("bus_plate", "Unknown")
                            eta_minutes = max(1, live_eta // 60)

                            title = f"Bus approaching {stop_name}"
                            body = (
                                f"Bus {plate} is ~{eta_minutes} min away "
                                f"from {stop_name} on route {route_number}."
                            )

                            sent = await _send_fcm_notification(
                                device_token=fcm_token,
                                title=title,
                                body=body,
                                data={
                                    "type": "bus_approaching",
                                    "route_number": route_number,
                                    "stop_name": stop_name,
                                    "stop_id": str(ns.stop_id),
                                    "eta_minutes": str(eta_minutes),
                                    "plate_number": plate,
                                },
                            )
                            if sent:
                                await _mark_notified(ns.id, ns.stop_id)

                    else:
                        # No specific stop — check all stops on the route
                        route_stops_result = await db.execute(
                            select(Stop)
                            .join(RouteStop, RouteStop.stop_id == Stop.id)
                            .where(RouteStop.route_id == ns.route_id)
                            .order_by(RouteStop.sequence_order)
                        )
                        stops = list(route_stops_result.scalars().all())

                        for stop in stops:
                            stop_eta_key = route_stop_key(route_number, stop.id)
                            eta_data = await redis.hgetall(stop_eta_key)

                            if not eta_data:
                                continue

                            try:
                                eta_seconds = float(eta_data.get("eta_seconds", 0))
                                computed_at = float(eta_data.get("computed_at", 0))
                            except (TypeError, ValueError):
                                continue

                            if computed_at <= 0:
                                continue

                            elapsed = max(0.0, time.time() - computed_at)
                            live_eta = max(0, int(eta_seconds - elapsed))
                            lead_time_seconds = ns.lead_time_minutes * 60

                            if 0 < live_eta <= lead_time_seconds:
                                if await _already_notified(ns.id, stop.id):
                                    continue

                                plate = eta_data.get("bus_plate", "Unknown")
                                eta_minutes = max(1, live_eta // 60)

                                title = f"Bus approaching {stop.name}"
                                body = (
                                    f"Bus {plate} is ~{eta_minutes} min away "
                                    f"from {stop.name} on route {route_number}."
                                )

                                sent = await _send_fcm_notification(
                                    device_token=fcm_token,
                                    title=title,
                                    body=body,
                                    data={
                                        "type": "bus_approaching",
                                        "route_number": route_number,
                                        "stop_name": stop.name,
                                        "stop_id": str(stop.id),
                                        "eta_minutes": str(eta_minutes),
                                        "plate_number": plate,
                                    },
                                )
                                if sent:
                                    await _mark_notified(ns.id, stop.id)

                except Exception:
                    logger.exception(
                        "Error processing notification for user %s route %s",
                        ns.user_id, ns.route_id,
                    )

        except Exception:
            logger.exception("Notification check loop error")


async def notification_worker():
    """Long-running async worker that checks notifications periodically.

    Runs as a background task in the FastAPI lifespan. Checks every
    CHECK_INTERVAL_SECONDS (default 60s) for buses approaching user-
    subscribed stops. Handles cancellation gracefully on shutdown.
    """
    logger.info("Notification worker started (interval: %ds)", CHECK_INTERVAL_SECONDS)
    try:
        while True:
            try:
                await check_and_send_notifications()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Notification worker error")
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("Notification worker shutting down gracefully")
        raise
