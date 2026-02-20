"""Favorite saved routes."""

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db.base import Base


class Favorite(Base):
    """User saved routes (e.g., 'Work')."""

    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=False)
    nickname = Column(String(50), nullable=True)

    user = relationship("User", back_populates="favorites")
    route = relationship("Route", back_populates="favorites")
