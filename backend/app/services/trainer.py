"""Retrain ML model from trip_history with feature engineering."""

from pathlib import Path

import joblib
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.trip_history import TripHistory

MIN_SAMPLES = 50
FEATURE_NAMES = ["stop_id", "hour", "day_of_week", "is_peak_hour", "occupancy_level"]


def _is_peak_hour(hour: int) -> int:
    """1 if morning (7-9:30) or evening (16:30-19:30), else 0."""
    if 7 <= hour < 10:
        return 1
    if 16 <= hour < 20:
        return 1
    return 0


async def train_from_db(db: AsyncSession, model_path: Path | None = None) -> tuple[bool, str]:
    """
    Pull trip_history, train RandomForest with feature engineering, save to .joblib.
    Returns (success, message).
    """
    result = await db.execute(
        select(TripHistory)
        .where(
            TripHistory.heuristic_eta.isnot(None),
            TripHistory.actual_travel_time.isnot(None),
        )
        .options(selectinload(TripHistory.stop))
    )
    rows = result.scalars().all()
    if len(rows) < MIN_SAMPLES:
        return False, f"Need at least {MIN_SAMPLES} samples, got {len(rows)}"
    X = []
    y = []
    for r in rows:
        h = r.arrival_time.hour if r.arrival_time else 12
        dow = r.arrival_time.weekday() if r.arrival_time else 0
        X.append([r.stop_id, h, dow, _is_peak_hour(h), r.occupancy_level or 0])
        y.append(r.actual_travel_time or 0)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    model = RandomForestRegressor(n_estimators=80, max_depth=12, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)
    test_pred = model.predict(X_test)
    mae = float(mean_absolute_error(y_test, test_pred))
    path = model_path or Path(__file__).parent / "delay_predictor.joblib"
    joblib.dump(model, path, compress=3)
    return True, f"Trained on {len(rows)} samples; holdout MAE (seconds): {mae:.2f}"


def get_feature_names() -> list[str]:
    """Return feature names for inference consistency."""
    return FEATURE_NAMES.copy()
