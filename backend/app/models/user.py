"""User model with role-based access."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class User(Base):
    """User table: Driver, Admin, Passenger."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)
    role = Column(String(20), nullable=False, default="passenger")
    google_id = Column(String(255), unique=True, nullable=True, index=True)
    is_verified = Column(Boolean, default=False, nullable=False)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    assignments = relationship("Assignment", back_populates="driver")
    favorites = relationship("Favorite", back_populates="user")
    ratings = relationship("Rating", back_populates="user")
    notification_settings = relationship("NotificationSetting", back_populates="user")
