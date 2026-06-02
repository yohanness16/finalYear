"""User CRUD operations."""

from sqlalchemy import delete, or_, select, update
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


async def get_all_users(db: AsyncSession):
    """Fetch all users from the database. Use get_users_paginated instead."""
    result = await db.execute(select(User))
    return result.scalars().all()


async def get_users_paginated(db: AsyncSession, skip: int = 0, limit: int = 100):
    """Fetch users with pagination."""
    result = await db.execute(select(User).offset(skip).limit(limit))
    return list(result.scalars().all())


async def get_users_by_role(db: AsyncSession, role: str):
    """Fetch users filtered by a specific role (e.g., 'driver', 'admin')."""
    result = await db.execute(select(User).where(User.role == role))
    return result.scalars().all()


async def search_users(db: AsyncSession, query: str):
    """Search users by username or email."""
    pattern = f"%{query}%"
    result = await db.execute(
        select(User).where(
            or_(
                User.username.ilike(pattern),
                User.email.ilike(pattern),
            )
        )
    )
    return result.scalars().all()


async def delete_user(db: AsyncSession, user_id: int):
    """Permanently remove a user by ID. Caller is responsible for commit."""
    await db.execute(delete(User).where(User.id == user_id))
    await db.flush()


async def update_user(db: AsyncSession, user_id: int, **kwargs):
    """Update user fields dynamically based on provided arguments.

    Filters out None values to avoid overwriting with nulls.
    Caller is responsible for commit (via get_db dependency).
    """
    update_data = {k: v for k, v in kwargs.items() if v is not None}

    if update_data:
        await db.execute(update(User).where(User.id == user_id).values(**update_data))
        await db.flush()

    # Return the updated user object
    result = await db.execute(select(User).where(User.id == user_id))
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
