"""Authentication endpoints: register, login, Google OAuth, email verification, password reset."""

from fastapi import APIRouter, Depends, HTTPException, Request
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.limiter import limiter
from app.core.security import ALGORITHM, create_access_token, get_current_user
from app.crud import driver_bus_session as crud_driver_session
from app.crud import user as crud_user
from app.crud import vehicle as crud_vehicle
from app.db.session import get_db
from app.schemas.auth import (
    BusDashboardLoginRequest,
    BusDashboardLoginResponse,
    ChangePasswordRequest,
    DriverLoginRequest,
    DriverLoginResponse,
    DriverLogoutRequest,
    ForgotPasswordRequest,
    GoogleAuthRequest,
    LoginRequest,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserUpdateRequest,
    VerifyEmailRequest,
)
from app.schemas.user import UserResponse
from app.services.email_service import (
    send_password_reset_email,
    send_verification_email,
)
from app.services.token_service import (
    consume_email_verify_token,
    consume_password_reset_token,
    create_email_verify_token,
    create_password_reset_token,
)

router = APIRouter()
# In app/api/v1/auth.py
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__ident="2b")
settings = get_settings()


@router.post("/auth/register", response_model=UserResponse)
@limiter.limit("10/minute")
async def register(
    request: Request, body: RegisterRequest, db: AsyncSession = Depends(get_db)
):
    """Passenger signup with email and password. Sends verification email."""
    if await crud_user.get_user_by_username(db, body.username):
        raise HTTPException(status_code=400, detail="Username already registered")
    if await crud_user.get_user_by_email(db, body.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    password_hash = pwd_context.hash(body.password)
    user = await crud_user.create_user(
        db,
        body.username,
        body.email,
        password_hash=password_hash,
        role="passenger",
        is_verified=False,
    )
    # Send verification email (non-blocking failure)
    token = await create_email_verify_token(user.id)
    await send_verification_email(user.email, user.username, token)
    return user


@router.post("/auth/login", response_model=TokenResponse)
@limiter.limit("20/minute")
async def login(
    request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)
):
    """Email/password login. Returns JWT."""
    user = await crud_user.get_user_by_username(db, body.username)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.password_hash:
        raise HTTPException(
            status_code=401, detail="Use Google sign-in for this account"
        )
    if not pwd_context.verify(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(user.id)

    # You MUST return both fields for the Bearer handshake to work
    return TokenResponse(access_token=token, token_type="bearer")


@router.post("/auth/google", response_model=TokenResponse)
@limiter.limit("20/minute")
async def google_auth(
    request: Request, body: GoogleAuthRequest, db: AsyncSession = Depends(get_db)
):
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


@router.patch("/auth/me", response_model=UserResponse)
@limiter.limit("10/minute")
async def update_profile(
    request: Request,
    body: UserUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the authenticated user's profile."""
    if body.username is not None:
        existing = await crud_user.get_user_by_username(db, body.username)
        if existing and existing.id != current_user.id:
            raise HTTPException(400, "Username already taken")
        current_user.username = body.username
    if body.email is not None:
        existing = await crud_user.get_user_by_email(db, body.email)
        if existing and existing.id != current_user.id:
            raise HTTPException(400, "Email already taken")
        current_user.email = body.email
    await db.flush()
    await db.refresh(current_user)
    return current_user


@router.post("/auth/change-password")
@limiter.limit("10/minute")
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change the authenticated user's password."""
    if not current_user.password_hash:
        raise HTTPException(
            400, "Account uses Google sign-in; password cannot be changed"
        )
    if not pwd_context.verify(body.current_password, current_user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    current_user.password_hash = pwd_context.hash(body.new_password)
    await db.flush()
    return {"status": "password_changed"}


@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh(current_user=Depends(get_current_user)):
    """Refresh JWT (requires valid token)."""
    token = create_access_token(current_user.id)
    return TokenResponse(access_token=token)


@router.post("/auth/driver-login", response_model=DriverLoginResponse)
@limiter.limit("20/minute")
async def driver_login(
    request: Request,
    body: DriverLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Driver login bound to a bus context using a bus-dashboard token."""
    user = await crud_user.get_user_by_username(db, body.username)
    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.role not in {"driver", "admin"}:
        raise HTTPException(
            status_code=403, detail="Only driver/admin accounts are allowed"
        )
    if not pwd_context.verify(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    vehicle = await crud_vehicle.get_vehicle_by_device_id(db, body.device_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not registered")

    try:
        payload = jwt.decode(
            body.bus_token, settings.SECRET_KEY, algorithms=[ALGORITHM]
        )
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid bus token")
    if payload.get("type") != "bus_dashboard":
        raise HTTPException(status_code=401, detail="Invalid bus token type")
    if str(payload.get("sub")) != str(vehicle.id):
        raise HTTPException(status_code=401, detail="Bus token does not match vehicle")

    active = await crud_driver_session.get_active_session_for_driver(db, user.id)
    if active:
        await crud_driver_session.end_session(db, active.id)

    session = await crud_driver_session.create_session(db, user.id, vehicle.id)
    token = create_access_token(user.id)
    return DriverLoginResponse(
        access_token=token,
        token_type="bearer",
        session_id=session.id,
        driver_id=user.id,
        vehicle_id=vehicle.id,
        device_id=vehicle.device_id,
    )


@router.post("/auth/driver-logout")
async def driver_logout(
    body: DriverLogoutRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Close a driver bus session for the authenticated driver."""
    session = await crud_driver_session.get_session_by_id(db, body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.driver_id != current_user.id and current_user.role != "admin":
        raise HTTPException(
            status_code=403, detail="Not allowed to logout this session"
        )

    await crud_driver_session.end_session(db, body.session_id)
    return {"status": "logged_out", "session_id": body.session_id}


@router.post("/auth/bus-dashboard/login", response_model=BusDashboardLoginResponse)
@limiter.limit("20/minute")
async def bus_dashboard_login(
    request: Request,
    body: BusDashboardLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate a physical bus dashboard device."""
    vehicle = await crud_vehicle.get_vehicle_by_id(db, body.vehicle_id)
    if not vehicle or vehicle.device_id != body.device_id:
        raise HTTPException(status_code=401, detail="Invalid bus dashboard credentials")

    if not vehicle.dashboard_password_hash:
        raise HTTPException(
            status_code=400, detail="Bus dashboard password is not configured"
        )

    if not pwd_context.verify(body.password, vehicle.dashboard_password_hash):
        raise HTTPException(status_code=401, detail="Invalid bus dashboard credentials")

    token_payload = {"sub": str(vehicle.id), "type": "bus_dashboard"}
    token = jwt.encode(token_payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    return BusDashboardLoginResponse(
        access_token=token,
        token_type="bearer",
        vehicle_id=vehicle.id,
        device_id=vehicle.device_id,
    )


@router.post("/auth/verify-email")
@limiter.limit("10/minute")
async def verify_email(
    request: Request, body: VerifyEmailRequest, db: AsyncSession = Depends(get_db)
):
    """Verify email address using token from email link."""
    user_id = await consume_email_verify_token(body.token)
    if not user_id:
        raise HTTPException(
            status_code=400, detail="Invalid or expired verification token"
        )
    user = await crud_user.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_verified:
        return {"status": "already_verified"}
    await crud_user.update_user(db, user_id, is_verified=True)
    return {"status": "verified"}


@router.post("/auth/resend-verification")
@limiter.limit("5/minute")
async def resend_verification(
    request: Request,
    body: ResendVerificationRequest,
    db: AsyncSession = Depends(get_db),
):
    """Resend verification email to an unverified user."""
    user = await crud_user.get_user_by_email(db, body.email)
    if not user:
        # Don't reveal whether email exists
        return {"status": "sent"}
    if user.is_verified:
        return {"status": "already_verified"}
    token = await create_email_verify_token(user.id)
    await send_verification_email(user.email, user.username, token)
    return {"status": "sent"}


@router.post("/auth/forgot-password")
@limiter.limit("5/minute")
async def forgot_password(
    request: Request, body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)
):
    """Send password reset email. Always returns success to prevent email enumeration."""
    user = await crud_user.get_user_by_email(db, body.email)
    if user and user.password_hash:
        token = await create_password_reset_token(user.id)
        await send_password_reset_email(user.email, user.username, token)
    # Always return success to prevent email enumeration
    return {"status": "sent"}


@router.post("/auth/reset-password")
@limiter.limit("5/minute")
async def reset_password(
    request: Request, body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)
):
    """Reset password using token from email link."""
    user_id = await consume_password_reset_token(body.token)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    user = await crud_user.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    new_hash = pwd_context.hash(body.new_password)
    await crud_user.update_user(db, user_id, password_hash=new_hash)
    return {"status": "reset"}
