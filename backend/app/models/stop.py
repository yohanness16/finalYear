"""Stop model for bus stops."""

from sqlalchemy import Boolean, Column, Float, Integer, String
from sqlalchemy.orm import relationship

from app.db.base import Base


class Stop(Base):
    """Bus stop metadata with dwell time and peak multiplier."""

    __tablename__ = "stops"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    base_dwell_time = Column(Integer, default=30)
    is_terminal = Column(Boolean, default=False)
    peak_multiplier = Column(Float, default=1.5)

    route_stops = relationship("RouteStop", back_populates="stop")
    trip_history = relationship("TripHistory", back_populates="stop")
