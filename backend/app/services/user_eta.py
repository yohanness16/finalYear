"""User-centric ETA service.

Given a user at stop A who wants to reach stop B, find the next buses
arriving at stop A and compute the total ETA (bus arrival + journey to B).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import route as crud_route
from app.crud import vehicle as crud_vehicle
from app.schemas.eta import BusEtaInfo, UserEtaResponse
from app.services.search_helpers import (
    compute_live_eta,
    infer_bus_direction,
    nearest_stop_index,
)
from app.utils.gps_validation import haversine_meters
from app.utils.redis_client import get_redis, route_stop_key

logger = logging.getLogger(__name__)


async def get_user_centric_eta(
    db: AsyncSession,
    current_stop_id: int,
    destination_stop_id: int,
    next_n_buses: int = 3,
) -> UserEtaResponse:
    """Compute user-centric ETA: next buses from current_stop to destination_stop.

    Algorithm:
      1. Resolve both stops from DB
      2. Find routes that contain both stops
      3. Get all active bus positions
      4. For each bus on a matching route:
         a. Determine bus position relative to route stops
         b. Infer travel direction (filter out buses going the wrong way)
         c. Read pre-computed ETA from Redis (set by telemetry pipeline)
         d. Apply live adjustment (subtract elapsed time)
      5. Sort by live ETA, return top N
    """
    # ── 1. Resolve stops ──────────────────────────────────────────────────
    current_stop = await crud_route.get_stop_by_id(db, current_stop_id)
    destination_stop = await crud_route.get_stop_by_id(db, destination_stop_id)

    if not current_stop or not destination_stop:
        return UserEtaResponse(
            current_stop_name=current_stop.name if current_stop else "Unknown",
            destination_stop_name=destination_stop.name if destination_stop else "Unknown",
            buses=[],
        )

    # ── 2. Find routes connecting the two stops ───────────────────────────
    routes = await crud_route.get_routes_through_stops(db, current_stop_id, destination_stop_id)
    if not routes:
        return UserEtaResponse(
            current_stop_name=current_stop.name,
            destination_stop_name=destination_stop.name,
            buses=[],
        )

    # ── 3. Get all active bus positions ───────────────────────────────────
    live_positions: dict[str, dict[str, Any]] = await crud_vehicle.get_live_positions(db)

    # ── 4. Build bus ETA list ─────────────────────────────────────────────
    bus_etas: list[BusEtaInfo] = []

    for route in routes:
        route_stops = await crud_route.get_route_stops_ordered(db, route.id)
        if not route_stops:
            continue

        # Build stop index maps
        stop_id_to_idx = {s.id: idx for idx, s in enumerate(route_stops)}
        current_stop_idx = stop_id_to_idx.get(current_stop_id)
        dest_stop_idx = stop_id_to_idx.get(destination_stop_id)

        if current_stop_idx is None or dest_stop_idx is None:
            continue

        # Determine which buses are on this route
        buses_on_route = [
            bus
            for bus in live_positions.values()
            if bus.get("route_id") == route.id
        ]

        for bus in buses_on_route:
            bus_lat = bus.get("lat")
            bus_lon = bus.get("lon")
            if bus_lat is None or bus_lon is None:
                continue

            plate = bus.get("plate_number", "")
            vehicle_id = bus.get("vehicle_id")

            # Determine bus position on route
            bus_stop_idx = nearest_stop_index(bus_lat, bus_lon, route_stops)

            # Infer direction from recent coordinates
            direction_val = None
            try:
                redis = await get_redis()
                from app.services.redis_cache import get_last_coords
                coords = await get_last_coords(plate)
                direction_val = infer_bus_direction(coords, route_stops)
            except Exception:
                pass

            # Filter: bus must be heading toward the user's stop
            # If bus is ahead of user's stop (past it), it must be going reverse
            # If bus is behind user's stop, it must be going forward
            if bus_stop_idx != current_stop_idx:
                if bus_stop_idx > current_stop_idx:
                    # Bus has passed the user's stop — only valid if going reverse
                    if direction_val is not None and direction_val != -1:
                        continue
                else:
                    # Bus hasn't reached the user's stop yet — only valid if going forward
                    if direction_val is not None and direction_val != 1:
                        continue

            # Read pre-computed ETA from Redis (set by telemetry pipeline)
            eta_to_current = None
            eta_to_dest = None
            try:
                redis = await get_redis()

                # ETA from bus to user's current stop
                key_current = route_stop_key(route.route_number, current_stop_id)
                data_current = await redis.hgetall(key_current)
                if data_current:
                    live = compute_live_eta(
                        data_current.get("eta_seconds", 0),
                        data_current.get("computed_at", 0),
                    )
                    eta_to_current = live if live is not None else 0

                # ETA from bus to user's destination stop
                key_dest = route_stop_key(route.route_number, destination_stop_id)
                data_dest = await redis.hgetall(key_dest)
                if data_dest:
                    live_dest = compute_live_eta(
                        data_dest.get("eta_seconds", 0),
                        data_dest.get("computed_at", 0),
                    )
                    eta_to_dest = live_dest if live_dest is not None else None
            except Exception:
                logger.debug("Redis ETA read failed for bus %s", plate, exc_info=True)

            # Skip if no ETA available for current stop
            if eta_to_current is None:
                continue

            # Determine direction label
            if bus_stop_idx == current_stop_idx:
                direction_label = "at_stop"
            else:
                direction_label = "approaching"

            # Compute stops between
            stops_bus_to_user = abs(bus_stop_idx - current_stop_idx)
            stops_user_to_dest = abs(dest_stop_idx - current_stop_idx)

            # Total ETA = bus arrival at current_stop + journey current→destination
            dest_eta = eta_to_dest if eta_to_dest is not None else 0
            # If we have ETA to dest, total = max(bus_eta_to_user, dest_eta - (dest<->user_dwell))
            # Simplified: bus arrives at user's stop, then user rides to destination
            total_eta = eta_to_current + max(0, dest_eta - eta_to_current) if dest_eta else eta_to_current

            bus_etas.append(
                BusEtaInfo(
                    vehicle_id=vehicle_id,
                    plate_number=plate,
                    route_number=route.route_number,
                    eta_seconds=eta_to_current,
                    eta_live_seconds=eta_to_current,
                    destination_eta_seconds=dest_eta,
                    total_eta_seconds=total_eta,
                    stops_between_user_and_bus=stops_bus_to_user,
                    stops_between_user_and_dest=stops_user_to_dest,
                    occupancy_level=int(bus.get("occupancy_level", 0)),
                    direction=direction_label,
                )
            )

    # ── 5. Sort by live ETA and return top N ──────────────────────────────
    bus_etas.sort(key=lambda b: b.eta_live_seconds)
    top_buses = bus_etas[: max(1, next_n_buses)]

    return UserEtaResponse(
        current_stop_name=current_stop.name,
        destination_stop_name=destination_stop.name,
        buses=top_buses,
    )
