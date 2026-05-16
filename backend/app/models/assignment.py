"""Assignment model: Driver + Vehicle + Route (active journey)."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class Assignment(Base):
    """Bridge: links driver, vehicle, route for a shift/journey."""

    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, index=True)
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=False)
    start_time = Column(DateTime(timezone=True), server_default=func.now())
    end_time = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), default="active")

    driver = relationship("User", back_populates="assignments")
    vehicle = relationship("Vehicle", back_populates="assignments")
    route = relationship("Route", back_populates="assignments")
    trip_history = relationship("TripHistory", back_populates="assignment")
    ratings = relationship("Rating", back_populates="assignment")
