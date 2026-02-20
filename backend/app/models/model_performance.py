"""Model performance - heuristic vs ML comparison."""

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class ModelPerformance(Base):
    """Tracks heuristic vs ML prediction errors for research."""

    __tablename__ = "model_performance"

    id = Column(Integer, primary_key=True, index=True)
    trip_history_id = Column(Integer, ForeignKey("trip_history.id"), nullable=False)
    heuristic_error = Column(Float, nullable=True)
    ml_error = Column(Float, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    trip_history = relationship("TripHistory", back_populates="model_performance")
