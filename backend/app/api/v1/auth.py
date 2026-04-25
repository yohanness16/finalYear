"""Authentication endpoints: register, login, Google OAuth."""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.limiter import limiter
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, get_current_user
from app.crud import user as crud_user
from app.db.session import get_db
from app.schemas.auth import RegisterRequest, LoginRequest, GoogleAuthRequest, TokenResponse
from app.schemas.user import UserResponse

router = APIRouter()
# In app/api/v1/auth.py
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__ident="2b")

@router.post("/auth/register", response_model=UserResponse)
@limiter.limit("10/minute")
async def register(request: Request, body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Passenger signup with email and password."""
    if await crud_user.get_user_by_username(db, body.username):
        raise HTTPException(status_code=400, detail="Username already registered")
    if await crud_user.get_user_by_email(db, body.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    password_hash = pwd_context.hash(body.password)
    user = await crud_user.create_user(
        db, body.username, body.email, password_hash=password_hash, role="passenger"
    )
    return user


@router.post("/auth/login", response_model=TokenResponse)
@limiter.limit("20/minute")
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Email/password login. Returns JWT."""
    user = await crud_user.get_user_by_username(db, body.username)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.password_hash:
        raise HTTPException(status_code=401, detail="Use Google sign-in for this account")
    if not pwd_context.verify(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(user.id)
    
    # You MUST return both fields for the Bearer handshake to work
    return TokenResponse(access_token=token, token_type="bearer")


@router.post("/auth/google", response_model=TokenResponse)
@limiter.limit("20/minute")
async def google_auth(request: Request, body: GoogleAuthRequest, db: AsyncSession = Depends(get_db)):
    """Google OAuth: verify ID token, create or login user."""
    import httpx
    from app.core.config import get_settings
    settings = get_settings()
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google OAuth not configured")
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://oauth2.googleapis.com/tokeninfo?id_token={body.id_token}"
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Google token")
    data = resp.json()
    if data.get("aud") != settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=401, detail="Token audience mismatch")
    email = data.get("email")
    google_id = data.get("sub")
    if not email or not google_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    user = await crud_user.get_user_by_google_id(db, google_id)
    if user:
        token = create_access_token(user.id)
        return TokenResponse(access_token=token)
    if await crud_user.get_user_by_email(db, email):
        raise HTTPException(
            status_code=400,
            detail="Email already registered. Use password login.",
        )
    username = email.split("@")[0][:90] + "_" + google_id[:8]
    user = await crud_user.create_user(
        db,
        username=username,
        email=email,
        password_hash=None,
        role="passenger",
        google_id=google_id,
        is_verified=True,
    )
    token = create_access_token(user.id)
    return TokenResponse(access_token=token, token_type="bearer")


@router.get("/auth/me", response_model=UserResponse)
@limiter.limit("30/minute")
async def me(request: Request, current_user=Depends(get_current_user)):
    """Current user profile (requires JWT)."""
    return current_user


@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh(current_user=Depends(get_current_user)):
    """Refresh JWT (requires valid token)."""
    token = create_access_token(current_user.id)
    return TokenResponse(access_token=token)
