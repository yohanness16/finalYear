"""Notification settings for proximity alerts."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.notification_setting import NotificationSetting
from app.schemas.tracking import NotificationSettingCreate
from app.utils.redis_client import get_redis

router = APIRouter()


class FcmTokenRequest(BaseModel):
    user_id: int
    token: str


@router.post("/notifications/settings")
async def set_notification(
    body: NotificationSettingCreate, db: AsyncSession = Depends(get_db)
):
    ns = NotificationSetting(
        user_id=body.user_id,
        route_id=body.route_id,
        lead_time_minutes=body.lead_time_minutes,
    )
    db.add(ns)
    await db.flush()
    await db.refresh(ns)
    return {"id": ns.id, "lead_time_minutes": body.lead_time_minutes}


@router.get("/notifications/settings/{user_id}")
async def get_notification_settings(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(NotificationSetting).where(NotificationSetting.user_id == user_id)
    )
    return list(result.scalars().all())


@router.post("/notifications/register-token")
async def register_fcm_token(body: FcmTokenRequest):
    """Register an FCM device token for push notifications."""
    redis = await get_redis()
    await redis.set(f"fcm:{body.user_id}", body.token, ex=2592000)
    return {"status": "registered"}
