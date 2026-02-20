"""Vehicle schemas."""

from typing import Optional

from pydantic import BaseModel


class VehicleBase(BaseModel):
    plate_number: str
    device_id: str
    bus_type: Optional[str] = None
    capacity: Optional[int] = None
    is_active: bool = True


class VehicleCreate(VehicleBase):
    pass


class VehicleUpdate(BaseModel):
    plate_number: Optional[str] = None
    bus_type: Optional[str] = None
    capacity: Optional[int] = None
    is_active: Optional[bool] = None


class VehicleResponse(VehicleBase):
    id: int

    class Config:
        from_attributes = True
