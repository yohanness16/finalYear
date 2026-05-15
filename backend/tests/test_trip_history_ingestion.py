"""Regression tests for trip-history persistence from telemetry."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import assignment as crud_assignment
from app.crud.tracking import create_trip_history_from_assignment
from app.db.session import AsyncSessionLocal
from app.models.route import Route
from app.models.stop import Stop
from app.models.trip_history import TripHistory
from app.models.user import User
from app.models.vehicle import Vehicle


async def _make_driver_vehicle_route(db_session: AsyncSession):
    suffix = uuid4().hex[:8]
    user = User(
        username=f"driver_{suffix}",
        email=f"driver_{suffix}@example.com",
        password_hash="hash",
        role="driver",
        is_verified=True,
    )
    route = Route(
        route_number=f"R{suffix}",
        direction="forward",
        name=f"Route {suffix}",
        origin="Origin",
        destination="Destination",
        active=True,
    )
    vehicle = Vehicle(
        plate_number=f"BUS-{suffix[:4]}",
        device_id=f"IMEI-{suffix}",
        bus_type="Anbessa",
        capacity=60,
        is_active=True,
    )
    stop = Stop(
        name=f"Stop {suffix}",
        lat=9.03,
        lon=38.76,
        base_dwell_time=30,
        is_terminal=False,
        peak_multiplier=1.5,
    )
    db_session.add_all([user, route, vehicle, stop])
    await db_session.commit()
    return user, route, vehicle, stop


async def test_trip_history_sample_is_created():
    async with AsyncSessionLocal() as db_session:
        user, route, vehicle, stop = await _make_driver_vehicle_route(db_session)

        assignment = await crud_assignment.create_assignment(
            db_session,
            driver_id=user.id,
            vehicle_id=vehicle.id,
            route_id=route.id,
        )
        assignment.start_time = datetime.now(timezone.utc) - timedelta(seconds=125)
        await db_session.flush()

        entry = await create_trip_history_from_assignment(
            db_session,
            assignment=assignment,
            stop=stop,
            lat=9.031,
            lon=38.761,
            occupancy_level=2,
        )

        result = await db_session.execute(
            select(TripHistory).where(TripHistory.id == entry.id)
        )
        stored = result.scalar_one_or_none()

        assert stored is not None
        assert stored.assignment_id == assignment.id
        assert stored.stop_id == stop.id
        assert stored.occupancy_level == 2
        assert stored.heuristic_eta is not None
        assert stored.actual_travel_time is not None
        assert stored.actual_travel_time >= 1
