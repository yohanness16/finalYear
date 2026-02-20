"""Admin-only user creation (driver, admin)."""

from fastapi import APIRouter, Depends, HTTPException
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import RequireAdmin
from app.crud import user as crud_user
from app.db.session import get_db
from app.schemas.auth import AdminCreateUserRequest
from app.schemas.user import UserResponse

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@router.post("/create")
async def create_admin(
    body: AdminCreateUserRequest,
    current_user: RequireAdmin,   # Move required arguments to the top
    name: str = "Default Name", 
    db: AsyncSession = Depends(get_db) # Move arguments with defaults to the bottom
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
