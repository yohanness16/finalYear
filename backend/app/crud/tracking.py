"""Tracking and telemetry CRUD operations."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import Assignment
from app.models.raw_telemetry import RawTelemetry
from app.models.stop import Stop
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


async def create_trip_history_from_assignment(
    db: AsyncSession,
    assignment: Assignment,
    stop: Stop,
    lat: float,
    lon: float,
    occupancy_level: int | None = None,
) -> TripHistory:
    """Create a trip-history sample for ML training from live telemetry."""
    from app.services.eta_calc import calculate_eta_heuristic

    now = datetime.now(UTC)
    start_time = assignment.start_time
    if start_time is None:
        actual_travel_time = 0
    else:
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=UTC)
        actual_travel_time = max(1, int((now - start_time).total_seconds()))

    heuristic_eta = int(
        calculate_eta_heuristic(
            lat,
            lon,
            stop.lat,
            stop.lon,
            num_stops=0,
            base_dwell_time=stop.base_dwell_time or 30,
            peak_multiplier=stop.peak_multiplier,
            occupancy_level=occupancy_level or 0,
        )
    )

    return await create_trip_history(
        db,
        assignment_id=assignment.id,
        stop_id=stop.id,
        occupancy_level=occupancy_level,
        heuristic_eta=heuristic_eta,
        actual_travel_time=actual_travel_time,
    )
