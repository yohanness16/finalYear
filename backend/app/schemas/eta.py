"""Schemas for user-centric ETA endpoints."""

from pydantic import BaseModel


class UserEtaRequest(BaseModel):
    """User at current_stop going to destination_stop — what's the ETA?"""

    current_stop_id: int
    destination_stop_id: int
    next_n_buses: int = 3


class BusEtaInfo(BaseModel):
    """ETA info for a single bus relative to the user's journey."""

    vehicle_id: int
    plate_number: str
    route_number: str
    eta_seconds: int
    eta_live_seconds: int
    destination_eta_seconds: int
    total_eta_seconds: int
    stops_between_user_and_bus: int
    stops_between_user_and_dest: int
    occupancy_level: int
    direction: str  # "approaching" | "at_stop" | "departing"


class UserEtaResponse(BaseModel):
    """Response: next buses arriving at user's stop with total journey ETA."""

    current_stop_name: str
    destination_stop_name: str
    buses: list[BusEtaInfo]
