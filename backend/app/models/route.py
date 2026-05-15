"""Route and Stop models for public bus routes."""

from sqlalchemy import Column, Float, ForeignKey, Integer, String, Boolean, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.base import Base
class Route(Base):
    """Bus route definition (e.g., "121 Kality ↔ Meskel Square")."""
    __tablename__ = "routes"
    __table_args__ = (
        UniqueConstraint("route_number", "direction", name="uq_route_number_direction"),
    )

    id = Column(Integer, primary_key=True, index=True)
    route_number = Column(String(20), nullable=False, index=True)
    direction = Column(String(10), nullable=False, default="forward")
    name = Column(String(200), nullable=False)
    origin = Column(String(100), nullable=True)
    destination = Column(String(100), nullable=True)
    active = Column(Boolean, default=True, nullable=False)

    vehicles = relationship("Vehicle", back_populates="route")
    route_stops = relationship(
        "RouteStop", back_populates="route", order_by="RouteStop.sequence_order"
    )

    assignments = relationship("Assignment", back_populates="route")
    favorites = relationship("Favorite", back_populates="route")
    notification_settings = relationship("NotificationSetting", back_populates="route")
class RouteStop(Base):
    """Stop sequence per route with GPS and operational details."""
    __tablename__ = "route_stops"

    route_id = Column(Integer, ForeignKey("routes.id", ondelete="CASCADE"), primary_key=True)
    stop_id = Column(Integer, ForeignKey("stops.id"), primary_key=True)
    sequence_order = Column(Integer, nullable=False)

    route = relationship("Route", back_populates="route_stops")
    stop = relationship("Stop", back_populates="route_stops")