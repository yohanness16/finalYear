"""Authentication endpoints: register, login, Google OAuth."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import JWTError, jwt

from app.core.limiter import limiter
from app.core.config import get_settings
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import ALGORITHM, create_access_token, get_current_user
from app.crud import driver_bus_session as crud_driver_session
from app.crud import user as crud_user
from app.crud import vehicle as crud_vehicle
from app.db.session import get_db
from app.schemas.auth import (
    BusDashboardLoginRequest,
    BusDashboardLoginResponse,
    DriverLoginRequest,
    DriverLoginResponse,
    DriverLogoutRequest,
    GoogleAuthRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.user import UserResponse

router = APIRouter()
# In app/api/v1/auth.py
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__ident="2b")
settings = get_settings()

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
        raise HTTPException(status_code=403, detail="Only driver/admin accounts are allowed")
    if not pwd_context.verify(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    vehicle = await crud_vehicle.get_vehicle_by_device_id(db, body.device_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not registered")

    try:
        payload = jwt.decode(body.bus_token, settings.SECRET_KEY, algorithms=[ALGORITHM])
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
        raise HTTPException(status_code=403, detail="Not allowed to logout this session")

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

    password_hash = getattr(vehicle, "dashboard_password_hash", None)
    if not password_hash:
        raise HTTPException(status_code=400, detail="Bus dashboard password is not configured")

    if not pwd_context.verify(body.password, password_hash):
        raise HTTPException(status_code=401, detail="Invalid bus dashboard credentials")

    token_payload = {"sub": str(vehicle.id), "type": "bus_dashboard"}
    token = jwt.encode(token_payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    return BusDashboardLoginResponse(
        access_token=token,
        token_type="bearer",
        vehicle_id=vehicle.id,
        device_id=vehicle.device_id,
    )
