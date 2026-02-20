"""Notification settings for proximity alerts."""

from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.db.base import Base


class NotificationSetting(Base):
    """Proximity alert: lead_time minutes before bus reaches stop."""

    __tablename__ = "notification_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=False)
    lead_time_minutes = Column(Integer, default=10)

    user = relationship("User", back_populates="notification_settings")
    route = relationship("Route", back_populates="notification_settings")
