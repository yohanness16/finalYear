"""Master ETA service: heuristic vs ML with admin toggle."""

from app.core.config import get_settings
from app.services.ai_predictor import predict_eta_adjustment
from app.services.eta_calc import calculate_eta_heuristic, get_time_multiplier
from app.services.ml_features import build_feature_dict, time_features


def get_final_eta(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    num_stops: int = 0,
    base_dwell_time: int = 30,
    stop_id: int | None = None,
    occupancy_level: int = 0,
    use_ml_for_prod: bool | None = None,
) -> tuple[float, float, str]:
    """
    Returns (eta_seconds, heuristic_eta, confidence_mode).
    confidence_mode is 'heuristic' or 'ml'.
    If use_ml_for_prod is None, falls back to env USE_ML_FOR_PROD.
    """
    # Use actual peak multiplier so ML features match heuristic computation
    peak_multiplier = get_time_multiplier()

    h_eta = calculate_eta_heuristic(
        lat1, lon1, lat2, lon2, num_stops, base_dwell_time,
        peak_multiplier, occupancy_level
    )
    # Pass peak_multiplier to ML features (was hardcoded 1.0, causing mismatch)
    hour, dow, is_peak = time_features(None)
    features = build_feature_dict(
        route_id=0,
        stop_id=int(stop_id or 0),
        stop_sequence=max(1, num_stops),
        remaining_stops=max(0, num_stops - 1),
        distance_m=float(h_eta) * 10.0,  # derive from heuristic instead of recomputing haversine
        base_dwell_time=base_dwell_time,
        peak_multiplier=peak_multiplier,
        hour=hour,
        day_of_week=dow,
        is_peak=is_peak,
        occupancy_level=occupancy_level,
        heuristic_eta=float(h_eta),
    )
    ml_adjustment = predict_eta_adjustment(features)
    settings = get_settings()
    use_ml = settings.USE_ML_FOR_PROD if use_ml_for_prod is None else use_ml_for_prod
    if use_ml and ml_adjustment is not None:
        ml_eta = max(0.0, float(h_eta) + float(ml_adjustment))
        return (ml_eta, h_eta, "ml")
    return (float(h_eta), float(h_eta), "heuristic")
