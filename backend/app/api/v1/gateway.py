"""Gateway endpoints for IoT devices with onboard camera support."""

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.db.session import get_db
from app.services.image_pipeline import process_esp32_telemetry

router = APIRouter(tags=["gateway"])


@router.post("/gateway/esp32/telemetry")
@limiter.limit("300/minute")
async def receive_esp32_telemetry(
    request: Request,
    device_id: str = Form(...),
    plate_number: str | None = Form(None),
    bus_type: str | None = Form(None),
    lat: float = Form(...),
    lon: float = Form(...),
    speed: float = Form(0.0),
    bus_capacity: int = Form(0),
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Receive multipart telemetry from an ESP32-CAM gateway.

    The full pipeline handles:
      - Vehicle identity resolution (auto-provision if new device_id)
      - GPS validation (outlier + on-route checks)
      - Image storage to disk
      - CV-based crowd density estimation
      - Raw telemetry persistence
      - Redis live pipeline update
      - Route ETA computation
      - Trip history recording
      - WebSocket broadcast (position + CV results)
    """
    image_bytes = await image.read()

    result = await process_esp32_telemetry(
        db=db,
        device_id=device_id,
        lat=lat,
        lon=lon,
        speed=speed,
        bus_capacity=bus_capacity,
        image_bytes=image_bytes,
        image_name=image.filename,
        plate_number=plate_number,
        bus_type=bus_type,
    )

    return result
