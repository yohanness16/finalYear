"""
Comprehensive tests for bus-GPS tracking integration.
Tests each bus device association, GPS validation, and telemetry processing.
"""
import pytest
from httpx import AsyncClient
from app.main import app
from app.crud.tracking import create_raw_telemetry
from app.crud import vehicle as crud_vehicle
from app.crud import assignment as crud_assignment
from app.models.vehicle import Vehicle
from app.models.raw_telemetry import RawTelemetry
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import AsyncSessionLocal
from app.utils.gps_validation import is_valid_coord


@pytest.fixture
async def client():
    from httpx import ASGITransport
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def db_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


class TestBusGPSTracking:
    """Test bus-GPS integration and per-bus tracking."""

    async def test_bus_device_registration(self, db_session: AsyncSession):
        """Each bus must have a unique device_id (SIM7600 IMEI)."""
        # Create a vehicle with device_id
        vehicle_data = {
            "plate_number": "AB-123-CD",
            "device_id": "351234068795432",  # SIM7600 IMEI format
            "bus_type": "Anbessa",
            "capacity": 60,
            "is_active": True,
        }
        vehicle = Vehicle(**vehicle_data)
        db_session.add(vehicle)
        await db_session.commit()
        await db_session.refresh(vehicle)

        assert vehicle.id is not None
        assert vehicle.device_id == "351234068795432"
        assert vehicle.plate_number == "AB-123-CD"

    async def test_gps_telemetry_per_bus(self, db_session: AsyncSession):
        """Each bus should have its own GPS telemetry stream."""
        # Create two buses
        bus1 = Vehicle(
            plate_number="BUS-001",
            device_id="IMEI_BUS001",
            bus_type="Anbessa",
            capacity=60,
            is_active=True,
        )
        bus2 = Vehicle(
            plate_number="BUS-002",
            device_id="IMEI_BUS002",
            bus_type="Sheger",
            capacity=50,
            is_active=True,
        )
        db_session.add_all([bus1, bus2])
        await db_session.commit()

        # Send GPS telemetry for bus 1
        telemetry1 = await create_raw_telemetry(
            db_session,
            vehicle_id=bus1.id,
            raw_lat=9.0320,
            raw_lon=38.7520,
            pixel_count=4500,
            raw_payload={"speed": 12.5, "battery": 85},
        )

        # Send GPS telemetry for bus 2
        telemetry2 = await create_raw_telemetry(
            db_session,
            vehicle_id=bus2.id,
            raw_lat=9.0450,
            raw_lon=38.7650,
            pixel_count=3200,
            raw_payload={"speed": 10.2, "battery": 92},
        )

        # Verify each bus has its own telemetry
        assert telemetry1.vehicle_id == bus1.id
        assert telemetry2.vehicle_id == bus2.id
        assert telemetry1.raw_lat == 9.0320
        assert telemetry2.raw_lat == 9.0450

        # Verify separation - bus1 data should not contain bus2's coordinates
        bus1_telemetry = await db_session.execute(
            select(RawTelemetry).filter_by(vehicle_id=bus1.id)
        )
        bus2_telemetry = await db_session.execute(
            select(RawTelemetry).filter_by(vehicle_id=bus2.id)
        )

        assert len(bus1_telemetry.scalars().all()) == 1
        assert len(bus2_telemetry.scalars().all()) == 1
        assert bus1_telemetry.scalars().first().raw_lat == 9.0320
        assert bus2_telemetry.scalars().first().raw_lat == 9.0450

    async def test_gps_outlier_rejection_per_bus(self, db_session: AsyncSession):
        """GPS outliers should be rejected per bus tracking context."""
        bus = Vehicle(
            plate_number="BUS-TEST",
            device_id="IMEI_TEST",
            bus_type="Minibus",
            capacity=40,
            is_active=True,
        )
        db_session.add(bus)
        await db_session.commit()

        # Valid GPS point
        valid = is_valid_coord(9.0320, 38.7520, [])
        assert valid is True

        # Create initial valid position
        await create_raw_telemetry(
            db_session,
            vehicle_id=bus.id,
            raw_lat=9.0320,
            raw_lon=38.7520,
        )

        # Outlier: 100km jump (should be rejected)
        is_outlier = not is_valid_coord(10.0, 40.0, [
            {"lat": 9.0320, "lon": 38.7520}
        ])
        assert is_outlier is True

        # Valid small movement
        is_valid = is_valid_coord(9.0350, 38.7550, [
            {"lat": 9.0320, "lon": 38.7520}
        ])
        assert is_valid is True

    async def test_bus_assignment_gps_tracking(self, db_session: AsyncSession):
        """Active bus assignments should correlate with GPS tracking."""
        # Create bus
        bus = Vehicle(
            plate_number="ASSIGN-BUS",
            device_id="IMEI_ASSIGN",
            bus_type="Anbessa",
            capacity=60,
            is_active=True,
        )
        db_session.add(bus)
        await db_session.commit()

        # Create active assignment
        assignment_data = {
            "driver_id": 1,
            "vehicle_id": bus.id,
            "route_id": 1,
        }
        assignment = await crud_assignment.create_assignment(
            db_session, **assignment_data
        )

        # Send GPS telemetry during active assignment
        telemetry = await create_raw_telemetry(
            db_session,
            vehicle_id=bus.id,
            raw_lat=9.0320,
            raw_lon=38.7520,
        )

        assert telemetry.vehicle_id == bus.id
        assert assignment.vehicle_id == bus.id

    async def test_multiple_gps_points_per_bus(self, db_session: AsyncSession):
        """Bus should accumulate multiple GPS points over time."""
        bus = Vehicle(
            plate_number="MULTI-POINT",
            device_id="IMEI_MULTI",
            bus_type="Sheger",
            capacity=50,
            is_active=True,
        )
        db_session.add(bus)
        await db_session.commit()

        # Send multiple GPS points
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

        # Verify all points stored
        result = await db_session.execute(
            select(RawTelemetry).filter_by(vehicle_id=bus.id)
        )
        stored_points = result.scalars().all()
        assert len(stored_points) == 4

        # Verify coordinates match
        for i, point in enumerate(stored_points):
            assert point.raw_lat == points[i][0]
            assert point.raw_lon == points[i][1]

    async def test_bus_gps_error_handling(self, db_session: AsyncSession):
        """GPS errors should be handled gracefully per bus."""
        bus = Vehicle(
            plate_number="ERROR-BUS",
            device_id="IMEI_ERROR",
            bus_type="Anbessa",
            capacity=60,
            is_active=True,
        )
        db_session.add(bus)
        await db_session.commit()

        # Simulate invalid GPS data (None/missing)
        with pytest.raises(Exception):
            # Attempting to store invalid GPS should raise error
            await create_raw_telemetry(
                db_session,
                vehicle_id=bus.id,
                raw_lat=None,  # Invalid
                raw_lon=38.7520,
            )

        # But valid data should still work
        telemetry = await create_raw_telemetry(
            db_session,
            vehicle_id=bus.id,
            raw_lat=9.0320,
            raw_lon=38.7520,
        )
        assert telemetry.id is not None