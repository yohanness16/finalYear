from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class VehicleBase(BaseModel):
    plate_number: str
    device_id: str
    bus_type: Optional[str] = None
    capacity: Optional[int] = None
    is_active: bool = True


class VehicleCreate(VehicleBase):
    """Payload for registering a new vehicle (no server-generated id)."""

    pass


class VehicleUpdate(BaseModel):
    plate_number: Optional[str] = None
    bus_type: Optional[str] = None
    capacity: Optional[int] = None
    is_active: Optional[bool] = None


class VehicleAdminUpdate(BaseModel):
    """Admin-only partial update (e.g. assign bus to a route for on-route validation)."""

    route_id: Optional[int] = None


class VehicleResponse(VehicleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    route_id: Optional[int] = None
    route_number: Optional[str] = None
    last_lat: Optional[float] = None
    last_lon: Optional[float] = None
    speed: Optional[float] = None
    position_updated_at: Optional[datetime] = None


class VehiclePosition(BaseModel):
    vehicle_id: int
    plate_number: str
    lat: float
    lon: float
    speed: float = 0.0
    timestamp: float  # Unix seconds (last position update)
    route_id: Optional[int] = None
    assignment_id: Optional[int] = None


class LivePositionsEnvelope(BaseModel):
    positions: dict[str, VehiclePosition]
    timestamp: float


class TelemetryInput(BaseModel):
    device_id: str
    lat: float
    lon: float
    speed: Optional[float] = None
    pixel_count: Optional[int] = None
    raw_payload: Optional[dict] = None
