"""Short-lived token generation and validation for email verification and password reset.

Uses Redis for O(1) token lookups with automatic expiry.
"""

import secrets
import json
from datetime import datetime, timezone

from app.utils.redis_client import get_redis

# Token TTLs
EMAIL_VERIFY_TTL = 86400    # 24 hours
PASSWORD_RESET_TTL = 3600   # 1 hour


async def create_email_verify_token(user_id: int) -> str:
    """Create a one-time email verification token. Returns the token string."""
    token = secrets.token_urlsafe(48)
    r = await get_redis()
    await r.set(
        f"email_verify:{token}",
        json.dumps({"user_id": user_id, "created_at": datetime.now(timezone.utc).isoformat()}),
        ex=EMAIL_VERIFY_TTL,
    )
    return token


async def consume_email_verify_token(token: str) -> int | None:
    """Validate and consume an email verification token. Returns user_id or None."""
    r = await get_redis()
    key = f"email_verify:{token}"
    data = await r.get(key)
    if not data:
        return None
    await r.delete(key)
    try:
        payload = json.loads(data)
        return int(payload["user_id"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return None


async def create_password_reset_token(user_id: int) -> str:
    """Create a one-time password reset token. Returns the token string."""
    token = secrets.token_urlsafe(48)
    r = await get_redis()
    # Invalidate any existing reset token for this user
    old_token = await r.get(f"pwd_reset_user:{user_id}")
    if old_token:
        await r.delete(f"pwd_reset:{old_token}")
    await r.set(
        f"pwd_reset:{token}",
        json.dumps({"user_id": user_id, "created_at": datetime.now(timezone.utc).isoformat()}),
        ex=PASSWORD_RESET_TTL,
    )
    await r.set(f"pwd_reset_user:{user_id}", token, ex=PASSWORD_RESET_TTL)
    return token


async def consume_password_reset_token(token: str) -> int | None:
    """Validate and consume a password reset token. Returns user_id or None."""
    r = await get_redis()
    key = f"pwd_reset:{token}"
    data = await r.get(key)
    if not data:
        return None
    await r.delete(key)
    try:
        payload = json.loads(data)
        user_id = int(payload["user_id"])
        await r.delete(f"pwd_reset_user:{user_id}")
        return user_id
    except (KeyError, ValueError, json.JSONDecodeError):
        return None
