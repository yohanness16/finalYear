"""Raw telemetry - bronze layer for unprocessed hardware data."""

from sqlalchemy import Column, Float, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime

from app.db.base import Base


class RawTelemetry(Base):
    """Raw GPS and density data from SIM7600/ESP32-CAM."""

    __tablename__ = "raw_telemetry"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False)
    raw_lat = Column(Float, nullable=False)
    raw_lon = Column(Float, nullable=False)
    pixel_count = Column(Integer, nullable=True)
    raw_payload = Column(JSONB, nullable=True)

    vehicle = relationship("Vehicle", back_populates="raw_telemetry")
