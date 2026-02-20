"""System settings for runtime config (e.g., use_ml_for_prod)."""

from sqlalchemy import Column, Integer, String

from app.db.base import Base


class SystemSettings(Base):
    """Key-value store for runtime configuration."""

    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(String(500), nullable=True)
