"""Crowd density query endpoints — live CV results for admin dashboards."""

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import RequireAdmin
from app.services.redis_cache import get_cv_result

router = APIRouter()


@router.get("/admin/crowd/{plate_number}")
async def get_vehicle_crowd(
    plate_number: str,
    current_user=Depends(RequireAdmin),
):
    """Get the latest CV crowd density result for a specific vehicle."""
    cv = await get_cv_result(plate_number)
    if cv is None:
        raise HTTPException(
            status_code=404,
            detail=f"No CV data for vehicle {plate_number}",
        )
    return {
        "plate_number": plate_number,
        "cv": cv,
    }
