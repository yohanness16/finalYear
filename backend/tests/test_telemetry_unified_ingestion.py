"""Tests to ensure telemetry endpoints share one ingestion pipeline."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.vehicle import Vehicle


@pytest.mark.asyncio
@pytest.mark.integration
async def test_vehicles_telemetry_uses_unified_ingestion_and_returns_occupancy():
    unique = uuid.uuid4().hex[:8]
    device_id = f"UNIFIED_{unique}"

    async with AsyncSessionLocal() as db:
        vehicle = Vehicle(
            plate_number=f"AA-UN-{unique[:5]}",
            device_id=device_id,
            bus_type="Anbessa",
            capacity=40,
            is_active=True,
        )
        db.add(vehicle)
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/vehicles/telemetry",
            json={
                "device_id": device_id,
                "lat": 9.032,
                "lon": 38.752,
                "speed": 11.0,
                "pixel_count": 8200,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "received"
    assert body["vehicle_id"] > 0
    assert body["occupancy_level"] == 2
    assert "route_checked" in body


@pytest.mark.asyncio
@pytest.mark.integration
async def test_vehicles_telemetry_auto_registers_unknown_device():
    unique = uuid.uuid4().hex[:8]
    device_id = f"UNIFIED_AUTO_{unique}"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/vehicles/telemetry",
            json={
                "device_id": device_id,
                "lat": 9.055,
                "lon": 38.788,
                "speed": 14.4,
                "pixel_count": 500,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "received"
        assert body["vehicle_id"] > 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Vehicle).where(Vehicle.device_id == device_id))
        created = result.scalar_one_or_none()
        assert created is not None
        assert created.plate_number.startswith("ESP-")
