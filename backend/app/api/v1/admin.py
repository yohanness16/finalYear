"""Admin dashboard endpoints."""

from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter()


@router.get("/admin/use-ml")
async def get_ml_toggle():
    """Get current ETA mode (heuristic vs ML)."""
    settings = get_settings()
    return {"use_ml_for_prod": settings.USE_ML_FOR_PROD}


# Note: Toggle would require a settings store (DB or Redis). For MVP, use env var.
