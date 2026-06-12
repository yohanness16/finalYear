"""User-centric ETA endpoint.

Given a user at stop A who wants to reach stop B, returns the next buses
arriving at stop A with total journey ETA to stop B.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.db.session import get_db
from app.schemas.eta import UserEtaRequest, UserEtaResponse
from app.services.user_eta import get_user_centric_eta

router = APIRouter(tags=["eta"])


@router.post("/eta/user-centric", response_model=UserEtaResponse)
@limiter.limit("60/minute")
async def user_eta(
    request: Request,
    body: UserEtaRequest,
    db: AsyncSession = Depends(get_db),
):
    """Get user-centric ETA: next buses from current_stop to destination_stop.

    Returns a sorted list of upcoming buses with:
    - eta_live_seconds: real-time countdown to bus arrival at user's stop
    - total_eta_seconds: estimated total journey time (bus arrival + ride to destination)
    - occupancy_level: current crowd density on the bus
    - direction: whether the bus is approaching or at the stop
    """
    return await get_user_centric_eta(
        db=db,
        current_stop_id=body.current_stop_id,
        destination_stop_id=body.destination_stop_id,
        next_n_buses=body.next_n_buses,
    )
