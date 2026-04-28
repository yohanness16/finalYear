"""ESP32 gateway telemetry tests."""

from pathlib import Path
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.vehicle import Vehicle


@pytest.mark.asyncio
@pytest.mark.integration
async def test_esp32_gateway_telemetry_with_image_runs_cv_and_marks_crowd():
    unique = uuid.uuid4().hex[:8]
    device_id = f"ESP32_{unique}"

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

    image_bytes = Path("storage/esp32_images/esp32_20260427T132908Z_f011d7ec.jpg").read_bytes()

    transport = ASGITransport(app=app)
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

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "received"
    assert body["vehicle_id"] > 0
    assert body["occupancy_level"] in {0, 1, 2}
    assert "cv" in body
    assert body["cv"]["human_count"] >= 1
    assert body["cv"]["people_count"] == body["cv"]["human_count"]
    assert body["cv"]["crowd_density"] == body["occupancy_level"]
    assert isinstance(body["cv"]["is_crowded"], bool)


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
        assert ingest.status_code == 200

        vehicles_res = await client.get("/api/v1/vehicles")
        assert vehicles_res.status_code == 200
        vehicles = vehicles_res.json()
        created = next((v for v in vehicles if v["device_id"] == device_id), None)
        assert created is not None
        assert created["plate_number"].startswith("ESP-")
        assert created["capacity"] == 50

        positions_res = await client.get("/api/v1/vehicles/positions")
        assert positions_res.status_code == 200
        positions = positions_res.json()["positions"]
        created_key = str(created["id"])
        assert created_key in positions
        assert positions[created_key]["lat"] == pytest.approx(9.04)
        assert positions[created_key]["lon"] == pytest.approx(38.76)
