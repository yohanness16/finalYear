"""Tracking and telemetry schemas."""

from typing import Any

from pydantic import BaseModel


class TelemetryInput(BaseModel):
    """Raw data from SIM7600/ESP32-CAM."""

    device_id: str
    lat: float
    lon: float
    speed: float | None = None
    pixel_count: int | None = None
    raw_payload: dict[str, Any] | None = None


class BusLiveState(BaseModel):
    """Live bus state from Redis."""

    plate_number: str
    lat: float
    lon: float
    speed: float
    occupancy_level: int
    assignment_id: int


class AssignmentStart(BaseModel):
    """Start a new assignment (driver check-in)."""

    driver_id: int
    vehicle_id: int
    route_id: int


class AssignmentEnd(BaseModel):
    """End an assignment."""

    assignment_id: int


class PointToPointSearch(BaseModel):
    """Search for buses between two stops."""

    start_stop_id: int
    end_stop_id: int


class GeoJourneySearch(BaseModel):
    """Search for buses using user-entered locations or coordinates."""

    start_query: str | None = None
    end_query: str | None = None
    start_lat: float | None = None
    start_lon: float | None = None
    end_lat: float | None = None
    end_lon: float | None = None
    max_routes: int | None = 5
    max_buses: int | None = 10


class FavoriteCreate(BaseModel):
    user_id: int
    route_id: int
    nickname: str | None = None


class RatingCreate(BaseModel):
    user_id: int
    assignment_id: int
    score: int
    comment: str | None = None


class NotificationSettingCreate(BaseModel):
    user_id: int
    route_id: int
    stop_id: int | None = None
    lead_time_minutes: int = 10
