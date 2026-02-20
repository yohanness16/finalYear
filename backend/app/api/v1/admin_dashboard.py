"""Admin dashboard: charts, analytics, settings toggle."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select , text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import RequireAdmin
from app.crud import system_settings as crud_settings
from app.db.session import get_db
from app.models.assignment import Assignment
from app.models.raw_telemetry import RawTelemetry
from app.models.route import Route
from app.models.trip_history import TripHistory
from app.models.model_performance import ModelPerformance
from app.models.vehicle import Vehicle
from app.models.user import User
from pydantic import BaseModel

router = APIRouter()


class SettingsUpdateBody(BaseModel):
    use_ml_for_prod: bool = False


@router.get("/admin/dashboard/summary")
async def dashboard_summary(
    current_user: RequireAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Counts: active assignments, vehicles, routes, users, raw_telemetry (last 24h)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    active = await db.execute(
        select(func.count(Assignment.id)).where(Assignment.status == "active")
    )
    vehicles = await db.execute(select(func.count(Vehicle.id)))
    routes = await db.execute(select(func.count(Route.id)))
    users = await db.execute(select(func.count(User.id)))
    telemetry_24h = await db.execute(
        select(func.count(RawTelemetry.id)).where(RawTelemetry.timestamp >= cutoff)
    )
    return {
        "active_assignments": active.scalar() or 0,
        "vehicles": vehicles.scalar() or 0,
        "routes": routes.scalar() or 0,
        "users": users.scalar() or 0,
        "telemetry_last_24h": telemetry_24h.scalar() or 0,
    }


@router.get("/admin/dashboard/assignments-over-time")
async def assignments_over_time(
    current_user: RequireAdmin,
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    """Assignments per day (last N days)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(func.date(Assignment.start_time).label("day"), func.count(Assignment.id))
        .where(Assignment.start_time >= cutoff)
        .group_by(func.date(Assignment.start_time))
        .order_by(func.date(Assignment.start_time))
    )
    rows = result.all()
    return {"labels": [str(r.day) for r in rows], "data": [r[1] for r in rows]}


@router.get("/admin/dashboard/occupancy-distribution")
async def occupancy_distribution(
    current_user: RequireAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Occupancy levels (0/1/2) distribution from trip_history."""
    result = await db.execute(
        select(TripHistory.occupancy_level, func.count(TripHistory.id))
        .where(TripHistory.occupancy_level.isnot(None))
        .group_by(TripHistory.occupancy_level)
    )
    rows = result.all()
    return {
        "labels": [f"Level {r[0]}" for r in rows],
        "data": [r[1] for r in rows],
    }


@router.get("/admin/dashboard/eta-accuracy")
async def eta_accuracy(
    current_user: RequireAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Heuristic vs ML vs actual (MAE) from model_performance."""
    h_err = await db.execute(
        select(func.avg(ModelPerformance.heuristic_error)).where(
            ModelPerformance.heuristic_error.isnot(None)
        )
    )
    ml_err = await db.execute(
        select(func.avg(ModelPerformance.ml_error)).where(
            ModelPerformance.ml_error.isnot(None)
        )
    )
    return {
        "heuristic_mae": round(h_err.scalar() or 0, 2),
        "ml_mae": round(ml_err.scalar() or 0, 2),
    }


@router.get("/admin/dashboard/route-usage")
async def route_usage(
    current_user: RequireAdmin,
    days: int = Query(30, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    """Trips per route (last N days)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(Route.route_number, func.count(Assignment.id))
        .join(Assignment, Assignment.route_id == Route.id)
        .where(Assignment.start_time >= cutoff)
        .group_by(Route.route_number)
        .order_by(func.count(Assignment.id).desc())
    )
    rows = result.all()
    return {"labels": [r[0] for r in rows], "data": [r[1] for r in rows]}



@router.get("/admin/dashboard/telemetry-volume")
async def telemetry_volume(
    current_user: RequireAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Telemetry count per hour (last 24h)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    
    # We define the expression once to ensure consistency
    # We use text("'hour'") to force it as a literal string, not a parameter
    hour_col = func.date_trunc(text("'hour'"), RawTelemetry.timestamp).label("hour_bucket")

    result = await db.execute(
        select(
            hour_col,
            func.count(RawTelemetry.id),
        )
        .where(RawTelemetry.timestamp >= cutoff)
        .group_by(text("hour_bucket"))  # Group by the label we just created
        .order_by(text("hour_bucket"))
    )
    
    rows = result.all()
    # Note: Use r.hour_bucket or r[0] to access the data
    return {"labels": [str(r[0]) for r in rows], "data": [r[1] for r in rows]}

@router.get("/admin/ml/status")
async def ml_status(current_user: RequireAdmin):
    """ML model loaded status and version."""
    from app.services.ai_predictor import model_loaded, get_model_version
    return {"model_loaded": model_loaded(), "model_version": get_model_version()}


@router.post("/admin/cleanup")
async def trigger_cleanup(
    current_user: RequireAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Run data retention cleanup (raw_telemetry, trip_history)."""
    from app.tasks.cleanup import run_cleanup
    counts = await run_cleanup(db)
    return counts


@router.post("/admin/ml/train")
async def trigger_training(
    current_user: RequireAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Trigger ML model retraining from trip_history."""
    from app.services.trainer import train_from_db
    success, msg = await train_from_db(db)
    return {"success": success, "message": msg}


@router.get("/admin/settings")
async def get_admin_settings(
    current_user: RequireAdmin,
    db: AsyncSession = Depends(get_db),
    
):
    """Get runtime settings (use_ml_for_prod, etc)."""
    use_ml = await crud_settings.get_setting(db, "use_ml_for_prod")
    return {"use_ml_for_prod": use_ml == "true" if use_ml else False}


@router.put("/admin/settings")
async def update_settings(
    current_user: RequireAdmin,
    body: SettingsUpdateBody,
    db: AsyncSession = Depends(get_db),
    
):
    """Update use_ml_for_prod (admin only)."""
    await crud_settings.set_setting(db, "use_ml_for_prod", "true" if body.use_ml_for_prod else "false")
    return {"use_ml_for_prod": body.use_ml_for_prod}
