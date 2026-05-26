"""Bus dashboard pairing endpoints."""

import secrets
import string

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.core.security import RequireAdmin
from app.crud import vehicle as crud_vehicle
from app.db.session import get_db
from app.utils.redis_client import get_redis

router = APIRouter()

PAIRING_CODE_TTL = 300  # 5 minutes
PAIRING_CODE_ALPHABET = (
    (string.ascii_uppercase + string.digits)
    .replace("O", "")
    .replace("0", "")
    .replace("I", "")
    .replace("L", "")
)


def _generate_code() -> str:
    """Generate human-friendly pairing code: BUS-XXXX-XXXX."""
    segment = "".join(secrets.choice(PAIRING_CODE_ALPHABET) for _ in range(4))
    segment2 = "".join(secrets.choice(PAIRING_CODE_ALPHABET) for _ in range(4))
    return f"BUS-{segment}-{segment2}"


class PairingCodeResponse(BaseModel):
    code: str
    vehicle_id: int
    plate_number: str
    device_id: str
    expires_in_seconds: int = PAIRING_CODE_TTL
    message: str


class PairVerifyRequest(BaseModel):
    code: str
    password: str = Field(..., min_length=6, max_length=100)


class PairVerifyResponse(BaseModel):
    status: str
    vehicle_id: int
    plate_number: str
    device_id: str
    message: str


@router.post(
    "/admin/vehicles/{vehicle_id}/generate-pairing-code",
    response_model=PairingCodeResponse,
)
@limiter.limit("20/minute")
async def generate_pairing_code(
    request: Request,
    vehicle_id: int,
    current_user: RequireAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Admin: generate a one-time 5-min pairing code for a bus dashboard."""
    vehicle = await crud_vehicle.get_vehicle_by_id(db, vehicle_id)
    if not vehicle:
        raise HTTPException(404, "Vehicle not found")

    if vehicle.dashboard_password_hash:
        raise HTTPException(
            400,
            "This dashboard is already paired. Unpair first to generate a new code.",
        )

    code = _generate_code()
    redis = await get_redis()
    await redis.set(f"pairing_code:{code}", str(vehicle_id), ex=PAIRING_CODE_TTL)

    return PairingCodeResponse(
        code=code,
        vehicle_id=vehicle.id,
        plate_number=vehicle.plate_number,
        device_id=vehicle.device_id,
        message="Code expires in 5 minutes. Enter this on the bus dashboard tablet.",
    )


@router.post("/pair/verify", response_model=PairVerifyResponse)
@limiter.limit("10/minute")
async def verify_pairing_code(
    request: Request,
    body: PairVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verify a pairing code and set the bus dashboard password."""
    from passlib.context import CryptContext

    pwd_context = CryptContext(
        schemes=["bcrypt"], deprecated="auto", bcrypt__ident="2b"
    )

    redis = await get_redis()
    redis_key = f"pairing_code:{body.code}"

    vehicle_id_str = await redis.get(redis_key)
    if not vehicle_id_str:
        raise HTTPException(400, "Invalid or expired pairing code")

    await redis.delete(redis_key)

    vehicle = await crud_vehicle.get_vehicle_by_id(db, int(vehicle_id_str))
    if not vehicle:
        raise HTTPException(404, "Vehicle not found")

    if vehicle.dashboard_password_hash:
        raise HTTPException(400, "This dashboard is already paired")

    vehicle.dashboard_password_hash = pwd_context.hash(body.password)
    await db.flush()

    return PairVerifyResponse(
        status="paired",
        vehicle_id=vehicle.id,
        plate_number=vehicle.plate_number,
        device_id=vehicle.device_id,
        message="Pairing complete. The dashboard is now active.",
    )


@router.post("/admin/vehicles/{vehicle_id}/unpair")
@limiter.limit("20/minute")
async def unpair_dashboard(
    request: Request,
    vehicle_id: int,
    current_user: RequireAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Admin: remove dashboard password so a new pairing code can be generated."""
    vehicle = await crud_vehicle.get_vehicle_by_id(db, vehicle_id)
    if not vehicle:
        raise HTTPException(404, "Vehicle not found")

    vehicle.dashboard_password_hash = None
    await db.flush()

    return {"status": "unpaired", "vehicle_id": vehicle.id}
