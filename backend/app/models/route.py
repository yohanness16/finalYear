"""Route and RouteStop models."""

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db.base import Base


class Route(Base):
    """Static path definition."""

    __tablename__ = "routes"

    id = Column(Integer, primary_key=True, index=True)
    route_number = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=True)
    origin = Column(String(100), nullable=True)
    destination = Column(String(100), nullable=True)

    route_stops = relationship(
        "RouteStop", back_populates="route", order_by="RouteStop.sequence_order"
    )
    assignments = relationship("Assignment", back_populates="route")
    favorites = relationship("Favorite", back_populates="route")
    notification_settings = relationship("NotificationSetting", back_populates="route")


class RouteStop(Base):
    """Stop sequence per route."""

    __tablename__ = "route_stops"

    route_id = Column(Integer, ForeignKey("routes.id"), primary_key=True)
    stop_id = Column(Integer, ForeignKey("stops.id"), primary_key=True)
    sequence_order = Column(Integer, nullable=False)

    route = relationship("Route", back_populates="route_stops")
    stop = relationship("Stop", back_populates="route_stops")
