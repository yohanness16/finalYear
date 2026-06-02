"""Admin-only user creation (driver, admin)."""

from fastapi import APIRouter, Depends, HTTPException
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import RequireAdmin
from app.crud import user as crud_user
from app.db.session import get_db
from app.schemas.auth import AdminCreateUserRequest, AdminUpdateUserRequest
from app.schemas.user import UserResponse

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@router.post("/create")
async def create_admin(
    body: AdminCreateUserRequest,
    current_user: RequireAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Admin creates driver or admin. Passengers sign up via /auth/register."""
    if await crud_user.get_user_by_username(db, body.username):
        raise HTTPException(400, "Username already registered")
    if await crud_user.get_user_by_email(db, body.email):
        raise HTTPException(400, "Email already registered")

    password_hash = pwd_context.hash(body.password)
    user = await crud_user.create_user(
        db,
        username=body.username,
        email=body.email,
        password_hash=password_hash,
        role=body.role,
        created_by_id=current_user.id,
    )
    return user


@router.get("/list", response_model=list[UserResponse])
async def list_users(
    skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)
):
    """List users with pagination."""
    from app.crud.user import get_users_paginated
    users = await get_users_paginated(db, skip, min(limit, 500))
    return users


@router.delete("/delete/{user_id}")
async def delete_user(
    user_id: int, current_user: RequireAdmin, db: AsyncSession = Depends(get_db)
):
    """Delete a user by ID."""
    user = await crud_user.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    await crud_user.delete_user(db, user_id)
    return {"detail": "User deleted"}


@router.put("/update/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    body: AdminUpdateUserRequest,
    current_user: RequireAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Update a user's details."""
    user = await crud_user.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    update_data: dict = {}
    if body.username is not None:
        update_data["username"] = body.username
    if body.email is not None:
        update_data["email"] = body.email
    if body.role is not None:
        update_data["role"] = body.role
    if body.password is not None and body.password != "":
        update_data["password_hash"] = pwd_context.hash(body.password)

    updated_user = await crud_user.update_user(db, user_id, **update_data)
    return updated_user


@router.get("/me", response_model=UserResponse)
async def get_current_user(current_user: RequireAdmin):
    """Get current admin user details."""
    return current_user


@router.get("/search")
async def search_users(
    query: str, limit: int = 50, current_user: RequireAdmin, db: AsyncSession = Depends(get_db)
):
    """Search users by username or email."""
    users = await crud_user.search_users(db, query, limit=min(limit, 200))
    return users


@router.get("/drivers", response_model=list[UserResponse])
async def list_drivers(current_user: RequireAdmin, db: AsyncSession = Depends(get_db)):
    """List all drivers."""
    drivers = await crud_user.get_users_by_role(db, "driver")
    return drivers


@router.get("/admins", response_model=list[UserResponse])
async def list_admins(current_user: RequireAdmin, db: AsyncSession = Depends(get_db)):
    """List all admins."""
    admins = await crud_user.get_users_by_role(db, "admin")
    return admins
