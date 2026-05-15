"""Route and stop schemas."""

from typing import Optional

from pydantic import BaseModel


class StopBase(BaseModel):
    name: str
    lat: float
    lon: float
    base_dwell_time: int = 30
    is_terminal: bool = False
    peak_multiplier: float = 1.5


class StopCreate(StopBase):
    pass


class StopResponse(StopBase):
    id: int

    class Config:
        from_attributes = True


class RouteStopSchema(BaseModel):
    stop_id: int
    sequence_order: int


class RouteBase(BaseModel):
    route_number: str
    direction: str = "forward"
    name: Optional[str] = None
    origin: Optional[str] = None
    destination: Optional[str] = None


class RouteCreate(RouteBase):
    stops: list[RouteStopSchema] = []


class RouteUpdate(BaseModel):
    direction: Optional[str] = None
    name: Optional[str] = None
    origin: Optional[str] = None
    destination: Optional[str] = None


class RouteResponse(RouteBase):
    id: int

    class Config:
        from_attributes = True


class RouteWithStops(RouteResponse):
    stops: list[StopResponse] = []
