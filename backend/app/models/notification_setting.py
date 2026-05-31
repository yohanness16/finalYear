"""Notification settings for proximity alerts."""

from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.db.base import Base


class NotificationSetting(Base):
    """Proximity alert: lead_time minutes before bus reaches a specific stop.

    A user subscribes to be notified when a bus on a given route is
    within lead_time_minutes of approaching their chosen stop.
    """

    __tablename__ = "notification_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=False)
    stop_id = Column(Integer, ForeignKey("stops.id"), nullable=True)
    lead_time_minutes = Column(Integer, default=10)

    user = relationship("User", back_populates="notification_settings")
    route = relationship("Route", back_populates="notification_settings")
    stop = relationship("Stop")
