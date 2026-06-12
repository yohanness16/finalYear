"""Admin dashboard endpoints."""

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.security import RequireAdmin

router = APIRouter()


@router.get("/admin/use-ml")
async def get_ml_toggle(current_user: RequireAdmin):
    """Get current ETA mode (heuristic vs ML). Admin only."""
    settings = get_settings()
    return {"use_ml_for_prod": settings.USE_ML_FOR_PROD}


# Note: Toggle would require a settings store (DB or Redis). For MVP, use env var.
