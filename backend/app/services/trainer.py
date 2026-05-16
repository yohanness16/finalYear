"""Retrain ML model from trip_history with feature engineering."""

import math
from pathlib import Path

import joblib
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import train_test_split
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ml_dataset import build_training_rows, rows_to_xy
from app.services.ml_features import FEATURE_NAMES

MIN_SAMPLES = 50


async def train_from_db(
    db: AsyncSession, model_path: Path | None = None
) -> tuple[bool, str]:
    """
    Pull trip_history, train RandomForest with feature engineering, save to .joblib.
    Returns (success, message).
    """
    rows = await build_training_rows(db)
    if len(rows) < MIN_SAMPLES:
        return False, f"Need at least {MIN_SAMPLES} samples, got {len(rows)}"

    X, y = rows_to_xy(rows)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )
    model = RandomForestRegressor(
        n_estimators=120,
        max_depth=14,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)
    test_pred = model.predict(X_test)
    mae = float(mean_absolute_error(y_test, test_pred))
    rmse = float(math.sqrt(mean_squared_error(y_test, test_pred)))

    path = model_path or Path(__file__).parent / "delay_predictor.joblib"
    payload = {"model": model, "feature_names": FEATURE_NAMES}
    joblib.dump(payload, path, compress=3)
    return True, (
        f"Trained on {len(rows)} samples; holdout MAE (residual seconds): {mae:.2f}; "
        f"RMSE (residual seconds): {rmse:.2f}"
    )


def get_feature_names() -> list[str]:
    """Return feature names for inference consistency."""
    return FEATURE_NAMES.copy()
