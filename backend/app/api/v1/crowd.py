"""Crowd density query endpoints — live CV results for admin dashboards."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import RequireAdmin
from app.services.redis_cache import get_cv_result

router = APIRouter()
logger = logging.getLogger(__name__)

# Keys stored in the veh:cv:{plate} Redis hash
_CV_HASH_KEYS = (
    "occupancy_level",
    "people_count",
    "crowd_density",
    "confidence",
    "method",
    "updated_at",
    "image_path",
)
_DEFAULTS = {
    "occupancy_level": 0,
    "people_count": 0,
    "crowd_density": 0,
    "confidence": 0.0,
    "method": "unknown",
    "updated_at": 0,
    "image_path": "",
}


@router.get("/admin/crowd/{plate_number}")
async def get_vehicle_crowd(
    plate_number: str,
    current_user=Depends(RequireAdmin),
):
    """Get the latest CV crowd density result for a specific vehicle."""
    cv = await get_cv_result(plate_number, keys=_CV_HASH_KEYS, defaults=_DEFAULTS)
    if cv is None:
        raise HTTPException(
            status_code=404,
            detail=f"No CV data for vehicle {plate_number}",
        )
    return {
        "plate_number": plate_number,
        "cv": cv,
        "image_path": cv.get("image_path") or None,
    }
