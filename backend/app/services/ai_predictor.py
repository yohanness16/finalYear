"""ML-based delay prediction. Loads .joblib model if available."""

from pathlib import Path
from typing import Optional

_model = None
_model_version: Optional[str] = None
_model_path = Path(__file__).parent / "delay_predictor.joblib"

# Features must match trainer: stop_id, hour, day_of_week, is_peak_hour, occupancy_level
FEATURE_COUNT = 5


def _load_model():
    global _model, _model_version
    if _model is not None:
        return _model
    if _model_path.exists():
        try:
            import joblib
            _model = joblib.load(_model_path)
            _model_version = str(_model_path.stat().st_mtime) if _model_path.exists() else None
            return _model
        except Exception:
            pass
    return None


def model_loaded() -> bool:
    """Health check: whether ML model is loaded."""
    return _load_model() is not None


def get_model_version() -> Optional[str]:
    """Return model version (mtime) if loaded."""
    _load_model()
    return _model_version


def predict_delay(stop_id: Optional[int], occupancy_level: int) -> Optional[float]:
    """
    Predict delay in seconds. Returns None if model not loaded.
    Features: stop_id, hour, day_of_week, is_peak_hour, occupancy_level.
    """
    model = _load_model()
    if model is None:
        return None
    from datetime import datetime
    now = datetime.now()
    hour = now.hour
    dow = now.weekday()
    is_peak = 1 if (7 <= hour < 10 or 16 <= hour < 20) else 0
    stop_id = stop_id or 0
    try:
        features = [[stop_id, hour, dow, is_peak, occupancy_level]]
        pred = model.predict(features)
        return float(pred[0])
    except Exception:
        return None
