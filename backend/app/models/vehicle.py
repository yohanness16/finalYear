"""Vehicle model for physical buses."""

from sqlalchemy import Boolean, Column, Integer, String
from sqlalchemy.orm import relationship

from app.db.base import Base


class Vehicle(Base):
    """Physical bus with SIM7600 device_id (IMEI)."""

    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True, index=True)
    plate_number = Column(String(20), unique=True, nullable=False, index=True)
    device_id = Column(String(50), unique=True, nullable=False, index=True)
    bus_type = Column(String(50), nullable=True)
    capacity = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    assignments = relationship("Assignment", back_populates="vehicle")
    raw_telemetry = relationship("RawTelemetry", back_populates="vehicle")
