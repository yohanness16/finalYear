"""ML-based ETA adjustment prediction. Loads .joblib model if available."""

from datetime import datetime
from pathlib import Path

from app.services.ml_features import (
    FEATURE_NAMES,
    build_feature_dict,
    build_feature_vector,
    time_features,
)

_model = None
_feature_names: list[str] = FEATURE_NAMES.copy()
_model_version: str | None = None
_model_path = Path(__file__).parent / "delay_predictor.joblib"


def _load_model():
    global _model, _model_version
    if _model is not None:
        return _model
    if _model_path.exists():
        try:
            import joblib

            payload = joblib.load(_model_path)
            if isinstance(payload, dict) and "model" in payload:
                _model = payload.get("model")
                names = payload.get("feature_names")
                if isinstance(names, list) and names:
                    global _feature_names
                    _feature_names = [str(n) for n in names]
            else:
                _model = payload
            _model_version = (
                str(_model_path.stat().st_mtime) if _model_path.exists() else None
            )
            return _model
        except Exception:
            pass
    return None


def reload_model() -> None:
    """Clear lazy cache so the next predict loads disk again (after retrain)."""
    global _model, _model_version
    _model = None
    _model_version = None


def model_loaded() -> bool:
    """Health check: whether ML model is loaded."""
    return _load_model() is not None


def get_model_version() -> str | None:
    """Return model version (mtime) if loaded."""
    _load_model()
    return _model_version


def predict_eta_adjustment(features: dict) -> float | None:
    """Predict ETA adjustment in seconds. Returns None if model not loaded."""
    model = _load_model()
    if model is None:
        return None
    try:
        vector = build_feature_vector(features)
        if len(vector) != len(_feature_names):
            return None
        pred = model.predict([vector])
        return float(pred[0])
    except Exception:
        return None


def predict_delay(stop_id: int | None, occupancy_level: int) -> float | None:
    """Backward-compatible delay prediction using minimal features."""
    now = datetime.now()
    hour, dow, is_peak = time_features(now)
    features = build_feature_dict(
        route_id=0,
        stop_id=int(stop_id or 0),
        stop_sequence=0,
        remaining_stops=0,
        distance_m=0.0,
        base_dwell_time=30,
        peak_multiplier=1.0,
        hour=hour,
        day_of_week=dow,
        is_peak=is_peak,
        occupancy_level=int(occupancy_level or 0),
        heuristic_eta=0.0,
    )
    return predict_eta_adjustment(features)
