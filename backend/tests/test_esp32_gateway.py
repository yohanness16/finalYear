"""ESP32 gateway telemetry tests."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.vehicle import Vehicle


@pytest.mark.asyncio
@pytest.mark.integration
async def test_esp32_gateway_telemetry_with_image_runs_cv_and_marks_crowd():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")

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

    img = np.full((240, 320, 3), 255, dtype=np.uint8)
    centers = [(40, 40), (100, 50), (160, 60), (220, 70), (280, 85), (70, 170), (180, 185), (260, 160)]
    for x, y in centers:
        cv2.circle(img, (x, y), 12, (0, 0, 0), -1)
    ok, encoded = cv2.imencode(".jpg", img)
    assert ok is True

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
            files={"image": ("frame.jpg", encoded.tobytes(), "image/jpeg")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "received"
    assert body["vehicle_id"] > 0
    assert body["occupancy_level"] == 2
    assert "cv" in body
    assert body["cv"]["people_count"] == len(centers)
    assert body["cv"]["is_crowded"] is True
