"""Trip history read endpoints.

The trip_history table is populated by the telemetry pipeline. These
endpoints expose the data to the admin dashboard and the bus dashboard.
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import CurrentUser
from app.db.session import get_db

router = APIRouter(tags=["trip-history"])


class TripHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    assignment_id: int
    stop_id: int
    stop_name: str | None = None
    arrival_time: str | None = None
    dwell_time: int | None = None
    occupancy_level: int | None = None
    heuristic_eta: int | None = None
    ml_eta: int | None = None
    actual_travel_time: int | None = None


def _to_out(row) -> TripHistoryOut:
    return TripHistoryOut(
        id=row.id,
        assignment_id=row.assignment_id,
        stop_id=row.stop_id,
        stop_name=row.stop.name if row.stop else None,
        arrival_time=row.arrival_time.isoformat() if row.arrival_time else None,
        dwell_time=row.dwell_time,
        occupancy_level=row.occupancy_level,
        heuristic_eta=row.heuristic_eta,
        ml_eta=row.ml_eta,
        actual_travel_time=row.actual_travel_time,
    )


@router.get(
    "/admin/trip-history/vehicle/{vehicle_id}", response_model=list[TripHistoryOut]
)
async def get_trip_history_by_vehicle(
    vehicle_id: int,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """Read trip history for all assignments of a given vehicle."""
    from app.models.assignment import Assignment
    from app.models.trip_history import TripHistory

    # Find assignment IDs for this vehicle
    assignment_ids = await db.execute(
        select(Assignment.id).where(Assignment.vehicle_id == vehicle_id)
    )
    ids = [r[0] for r in assignment_ids.all()]
    if not ids:
        return []

    result = await db.execute(
        select(TripHistory)
        .where(TripHistory.assignment_id.in_(ids))
        .options(selectinload(TripHistory.stop))
        .order_by(TripHistory.arrival_time.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.scalars().all()
    return [_to_out(r) for r in rows]


@router.get(
    "/admin/trip-history/assignment/{assignment_id}",
    response_model=list[TripHistoryOut],
)
async def get_trip_history_by_assignment(
    assignment_id: int,
    current_user: CurrentUser = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """Read trip history for a specific assignment."""
    from app.models.trip_history import TripHistory

    result = await db.execute(
        select(TripHistory)
        .where(TripHistory.assignment_id == assignment_id)
        .options(selectinload(TripHistory.stop))
        .order_by(TripHistory.arrival_time.asc())
    )
    rows = result.scalars().all()
    return [_to_out(r) for r in rows]
