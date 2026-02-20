"""Trip history - stop-level events for ML training."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class TripHistory(Base):
    """Stop arrival events with heuristic/ML ETA comparison."""

    __tablename__ = "trip_history"

    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=False)
    stop_id = Column(Integer, ForeignKey("stops.id"), nullable=False)
    arrival_time = Column(DateTime(timezone=True), server_default=func.now())
    dwell_time = Column(Integer, nullable=True)
    occupancy_level = Column(Integer, nullable=True)
    heuristic_eta = Column(Integer, nullable=True)
    ml_eta = Column(Integer, nullable=True)
    actual_travel_time = Column(Integer, nullable=True)

    assignment = relationship("Assignment", back_populates="trip_history")
    stop = relationship("Stop", back_populates="trip_history")
    model_performance = relationship("ModelPerformance", back_populates="trip_history")
