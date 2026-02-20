"""Master ETA service: heuristic vs ML with admin toggle."""

from app.core.config import get_settings
from app.services.eta_calc import calculate_eta_heuristic
from app.services.ai_predictor import predict_delay


def get_final_eta(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    num_stops: int = 0,
    base_dwell_time: int = 30,
    stop_id: int | None = None,
    occupancy_level: int = 0,
) -> tuple[float, float, str]:
    """
    Returns (eta_seconds, heuristic_eta, confidence_mode).
    confidence_mode is 'heuristic' or 'ml'.
    """
    h_eta = calculate_eta_heuristic(
        lat1, lon1, lat2, lon2, num_stops, base_dwell_time, None, occupancy_level
    )
    ml_eta = predict_delay(stop_id, occupancy_level)
    settings = get_settings()
    if settings.USE_ML_FOR_PROD and ml_eta is not None:
        return (ml_eta, h_eta, "ml")
    return (h_eta, h_eta, "heuristic")
