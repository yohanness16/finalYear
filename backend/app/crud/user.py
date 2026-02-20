"""User CRUD operations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_google_id(db: AsyncSession, google_id: str) -> User | None:
    result = await db.execute(select(User).where(User.google_id == google_id))
    return result.scalar_one_or_none()


async def create_user(
    db: AsyncSession,
    username: str,
    email: str,
    password_hash: str | None = None,
    role: str = "passenger",
    google_id: str | None = None,
    is_verified: bool = False,
    created_by_id: int | None = None,
) -> User:
    user = User(
        username=username,
        email=email,
        password_hash=password_hash,
        role=role,
        google_id=google_id,
        is_verified=is_verified,
        created_by_id=created_by_id,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user
