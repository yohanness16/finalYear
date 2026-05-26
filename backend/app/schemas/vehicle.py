from datetime import datetime

from pydantic import BaseModel, ConfigDict


class VehicleBase(BaseModel):
    plate_number: str
    device_id: str
    bus_type: str | None = None
    capacity: int | None = None
    is_active: bool = True


class VehicleCreate(VehicleBase):
    """Payload for registering a new vehicle (no server-generated id)."""

    pass


class VehicleUpdate(BaseModel):
    plate_number: str | None = None
    bus_type: str | None = None
    capacity: int | None = None
    is_active: bool | None = None


class VehicleAdminUpdate(BaseModel):
    """Admin-only partial update (e.g. assign bus to a route for on-route validation)."""

    route_id: int | None = None


class VehicleResponse(VehicleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    route_id: int | None = None
    route_number: str | None = None
    last_lat: float | None = None
    last_lon: float | None = None
    speed: float | None = None
    position_updated_at: datetime | None = None


class VehiclePosition(BaseModel):
    vehicle_id: int
    plate_number: str
    lat: float
    lon: float
    speed: float = 0.0
    timestamp: float  # Unix seconds (last position update)
    route_id: int | None = None
    assignment_id: int | None = None
    occupancy_level: int = 0
    density_level: int = 0
    last_updated: datetime | None = None


class LivePositionsEnvelope(BaseModel):
    positions: dict[str, VehiclePosition]
    timestamp: float


class TelemetryInput(BaseModel):
    device_id: str
    lat: float
    lon: float
    speed: float | None = None
    pixel_count: int | None = None
    raw_payload: dict | None = None
