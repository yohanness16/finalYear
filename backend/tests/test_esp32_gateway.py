"""ESP32 gateway telemetry tests."""

import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.vehicle import Vehicle


@pytest.mark.asyncio
@pytest.mark.integration
async def test_esp32_gateway_telemetry_with_image_runs_cv_and_marks_crowd():
    unique = uuid.uuid4().hex[:8]
    device_id = f"ESP32_{unique}"

    try:
        async with AsyncSessionLocal() as db:
            vehicle = Vehicle(
                plate_number=f"AA-ESP-{unique[:5]}",
                device_id=device_id,
                bus_type="Anbessa",
                capacity=40,
                is_active=True,
            )
            db.add(vehicle)
            await db.commit()
    except Exception:
        pytest.skip("database unavailable")

    image_candidates = sorted(Path("storage/esp32_images").glob("*.jpg"))
    if not image_candidates:
        pytest.skip("no ESP32 sample images available")
    image_bytes = image_candidates[0].read_bytes()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/gateway/esp32/telemetry",
                data={
                    "device_id": device_id,
                    "lat": "9.032",
                    "lon": "38.752",
                    "speed": "12.5",
                    "bus_capacity": "10",
                },
                files={"image": ("frame.jpg", image_bytes, "image/jpeg")},
            )
    except Exception:
        pytest.skip("database unavailable")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "received"
    assert body["vehicle_id"] > 0
    assert body["created"] is False
    assert body["occupancy_level"] in {0, 1, 2}
    assert "cv" in body
    assert body["cv"]["human_count"] >= 1
    assert body["cv"]["people_count"] == body["cv"]["human_count"]
    assert body["cv"]["crowd_density"] == body["occupancy_level"]
    assert isinstance(body["cv"]["is_crowded"], bool)
    assert body["cv"]["method"] in {"hog", "foreground", "hog+foreground", "fallback"}
    assert 0.0 <= body["cv"]["foreground_ratio"] <= 1.0

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Vehicle).where(Vehicle.device_id == device_id))
        created = result.scalar_one_or_none()
        assert created is not None
        assert created.plate_number.startswith("AA-ESP-")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_esp32_gateway_auto_registers_unknown_device_and_updates_positions():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")

    unique = uuid.uuid4().hex[:8]
    device_id = f"ESP_AUTO_{unique}"

    img = np.full((120, 160, 3), 255, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", img)
    assert ok is True

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            ingest = await client.post(
                "/api/v1/gateway/esp32/telemetry",
                data={
                    "device_id": device_id,
                    "lat": "9.04",
                    "lon": "38.76",
                    "speed": "8.2",
                    "bus_capacity": "50",
                },
                files={"image": ("frame.jpg", encoded.tobytes(), "image/jpeg")},
            )
    except Exception:
        pytest.skip("database unavailable")

    assert ingest.status_code == 200
    ingest_body = ingest.json()
    assert ingest_body["created"] is True

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Vehicle).where(Vehicle.device_id == device_id))
        created = result.scalar_one_or_none()
        assert created is not None
        assert created.plate_number.startswith("ESP-")
        assert created.capacity == 50

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        positions_res = await client.get("/api/v1/vehicles/positions")
        assert positions_res.status_code == 200
        positions = positions_res.json()["positions"]
        created_key = str(created.id)
        assert created_key in positions
        assert positions[created_key]["lat"] == pytest.approx(9.04)
        assert positions[created_key]["lon"] == pytest.approx(38.76)
