"""Route and stop schemas."""

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
    name: str | None = None
    origin: str | None = None
    destination: str | None = None


class RouteCreate(RouteBase):
    stops: list[RouteStopSchema] = []


class RouteUpdate(BaseModel):
    direction: str | None = None
    name: str | None = None
    origin: str | None = None
    destination: str | None = None


class RouteResponse(RouteBase):
    id: int

    class Config:
        from_attributes = True


class RouteWithStops(RouteResponse):
    stops: list[StopResponse] = []
