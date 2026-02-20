"""Tracking and telemetry CRUD operations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.raw_telemetry import RawTelemetry
from app.models.trip_history import TripHistory


async def create_raw_telemetry(
    db: AsyncSession,
    vehicle_id: int,
    raw_lat: float,
    raw_lon: float,
    pixel_count: int | None = None,
    raw_payload: dict | None = None,
) -> RawTelemetry:
    entry = RawTelemetry(
        vehicle_id=vehicle_id,
        raw_lat=raw_lat,
        raw_lon=raw_lon,
        pixel_count=pixel_count,
        raw_payload=raw_payload,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return entry


async def create_trip_history(
    db: AsyncSession,
    assignment_id: int,
    stop_id: int,
    dwell_time: int | None = None,
    occupancy_level: int | None = None,
    heuristic_eta: int | None = None,
    ml_eta: int | None = None,
    actual_travel_time: int | None = None,
) -> TripHistory:
    entry = TripHistory(
        assignment_id=assignment_id,
        stop_id=stop_id,
        dwell_time=dwell_time,
        occupancy_level=occupancy_level,
        heuristic_eta=heuristic_eta,
        ml_eta=ml_eta,
        actual_travel_time=actual_travel_time,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return entry
