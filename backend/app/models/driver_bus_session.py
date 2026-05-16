"""Driver session model for bus-bound dashboard logins."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class DriverBusSession(Base):
    """Tracks when a driver logs into and out of a specific bus dashboard."""

    __tablename__ = "driver_bus_sessions"

    id = Column(Integer, primary_key=True, index=True)
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False, index=True)
    login_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    logout_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(
        String(20), nullable=False, default="active", server_default="active"
    )

    driver = relationship("User")
    vehicle = relationship("Vehicle", back_populates="driver_sessions")
