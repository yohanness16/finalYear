"""
Comprehensive tests for bus-GPS tracking integration.
Tests each bus device association, GPS validation, and telemetry processing.
"""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import assignment as crud_assignment
from app.crud.tracking import create_raw_telemetry
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.raw_telemetry import RawTelemetry
from app.models.route import Route
from app.models.user import User
from app.models.vehicle import Vehicle
from app.utils.gps_validation import is_valid_coord


class TestBusGPSTracking:
    """Test bus-GPS integration and per-bus tracking."""

    def _unique_vehicle(self, prefix: str, bus_type: str = "Anbessa", capacity: int = 60):
        suffix = uuid4().hex[:8]
        return Vehicle(
            plate_number=f"{prefix}-{suffix[:5]}",
            device_id=f"IMEI_{prefix}_{suffix}",
            bus_type=bus_type,
            capacity=capacity,
            is_active=True,
        )

    async def test_bus_device_registration(self):
        """Each bus must have a unique device_id (SIM7600 IMEI)."""
        async with AsyncSessionLocal() as db_session:
            vehicle = self._unique_vehicle("AB-123-CD")
            db_session.add(vehicle)
            await db_session.commit()
            await db_session.refresh(vehicle)

            assert vehicle.id is not None
            assert vehicle.device_id.startswith("IMEI_AB-123-CD_")
            assert vehicle.plate_number.startswith("AB-123-CD-")

    async def test_gps_telemetry_per_bus(self):
        """Each bus should have its own GPS telemetry stream."""
        async with AsyncSessionLocal() as db_session:
            bus1 = self._unique_vehicle("BUS-001", bus_type="Anbessa", capacity=60)
            bus2 = self._unique_vehicle("BUS-002", bus_type="Sheger", capacity=50)
            db_session.add_all([bus1, bus2])
            await db_session.commit()
            await db_session.refresh(bus1)
            await db_session.refresh(bus2)

            telemetry1 = await create_raw_telemetry(
                db_session,
                vehicle_id=bus1.id,
                raw_lat=9.0320,
                raw_lon=38.7520,
                pixel_count=4500,
                raw_payload={"speed": 12.5, "battery": 85},
            )

            telemetry2 = await create_raw_telemetry(
                db_session,
                vehicle_id=bus2.id,
                raw_lat=9.0450,
                raw_lon=38.7650,
                pixel_count=3200,
                raw_payload={"speed": 10.2, "battery": 92},
            )

            assert telemetry1.vehicle_id == bus1.id
            assert telemetry2.vehicle_id == bus2.id
            assert telemetry1.raw_lat == 9.0320
            assert telemetry2.raw_lat == 9.0450

            bus1_telemetry = await db_session.execute(
                select(RawTelemetry).filter_by(vehicle_id=bus1.id)
            )
            bus2_telemetry = await db_session.execute(
                select(RawTelemetry).filter_by(vehicle_id=bus2.id)
            )

            bus1_rows = bus1_telemetry.scalars().all()
            bus2_rows = bus2_telemetry.scalars().all()
            assert len(bus1_rows) == 1
            assert len(bus2_rows) == 1
            assert bus1_rows[0].raw_lat == 9.0320
            assert bus2_rows[0].raw_lat == 9.0450

    async def test_gps_outlier_rejection_per_bus(self):
        """GPS outliers should be rejected per bus tracking context."""
        async with AsyncSessionLocal() as db_session:
            bus = self._unique_vehicle("BUS-TEST", bus_type="Minibus", capacity=40)
            db_session.add(bus)
            await db_session.commit()
            await db_session.refresh(bus)

            valid = is_valid_coord(9.0320, 38.7520, [])
            assert valid is True

            await create_raw_telemetry(
                db_session,
                vehicle_id=bus.id,
                raw_lat=9.0320,
                raw_lon=38.7520,
            )

            is_outlier = not is_valid_coord(10.0, 40.0, [{"lat": 9.0320, "lon": 38.7520}])
            assert is_outlier is True

            is_valid = is_valid_coord(9.0350, 38.7550, [{"lat": 9.0320, "lon": 38.7520}])
            assert is_valid is True

    async def test_bus_assignment_gps_tracking(self):
        """Active bus assignments should correlate with GPS tracking."""
        async with AsyncSessionLocal() as db_session:
            suffix = uuid4().hex[:8]
            bus = Vehicle(
                plate_number=f"ASSIGN-BUS-{suffix[:5]}",
                device_id=f"IMEI_ASSIGN_{suffix}",
                bus_type="Anbessa",
                capacity=60,
                is_active=True,
            )
            driver = User(
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
            db_session.add(bus)
            db_session.add(driver)
            db_session.add(route)
            await db_session.commit()
            await db_session.refresh(bus)
            await db_session.refresh(driver)
            await db_session.refresh(route)

            assignment = await crud_assignment.create_assignment(
                db_session,
                driver_id=driver.id,
                vehicle_id=bus.id,
                route_id=route.id,
            )

            telemetry = await create_raw_telemetry(
                db_session,
                vehicle_id=bus.id,
                raw_lat=9.0320,
                raw_lon=38.7520,
            )

            assert telemetry.vehicle_id == bus.id
            assert assignment.vehicle_id == bus.id

    async def test_multiple_gps_points_per_bus(self):
        """Bus should accumulate multiple GPS points over time."""
        async with AsyncSessionLocal() as db_session:
            bus = self._unique_vehicle("MULTI-POINT", bus_type="Sheger", capacity=50)
            db_session.add(bus)
            await db_session.commit()
            await db_session.refresh(bus)

            points = [
                (9.0320, 38.7520),
                (9.0350, 38.7550),
                (9.0380, 38.7580),
                (9.0410, 38.7610),
            ]

            for lat, lon in points:
                await create_raw_telemetry(
                    db_session,
                    vehicle_id=bus.id,
                    raw_lat=lat,
                    raw_lon=lon,
                )

            result = await db_session.execute(
                select(RawTelemetry).filter_by(vehicle_id=bus.id)
            )
            stored_points = result.scalars().all()
            assert len(stored_points) == 4

            for i, point in enumerate(stored_points):
                assert point.raw_lat == points[i][0]
                assert point.raw_lon == points[i][1]

    async def test_bus_gps_error_handling(self):
        """GPS errors should be handled gracefully per bus."""
        async with AsyncSessionLocal() as db_session:
            bus = self._unique_vehicle("ERROR-BUS", bus_type="Anbessa", capacity=60)
            db_session.add(bus)
            await db_session.commit()
            await db_session.refresh(bus)
            bus_id = bus.id

            with pytest.raises(Exception):
                await create_raw_telemetry(
                    db_session,
                    vehicle_id=bus_id,
                    raw_lat=None,
                    raw_lon=38.7520,
                )

            await db_session.rollback()

            telemetry = await create_raw_telemetry(
                db_session,
                vehicle_id=bus_id,
                raw_lat=9.0320,
                raw_lon=38.7520,
            )
            assert telemetry.id is not None
