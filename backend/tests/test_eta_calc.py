from unittest.mock import patch

from app.services.eta_calc import calculate_eta_heuristic, haversine_meters
from app.services.eta_engine import get_final_eta


def test_haversine_accuracy():
    # Distance between two points in Addis Ababa (approx 1.1km)
    dist = haversine_meters(9.02, 38.74, 9.03, 38.75)
    assert 1000 < dist < 2000


def test_eta_heuristic_calculation():
    # Test 1km distance at 40km/h (11.1 m/s) -> ~90 seconds
    # + 1 stop (30s) = 120s
    eta = calculate_eta_heuristic(9.02, 38.74, 9.03, 38.75, num_stops=1)
    assert eta > 100


@patch("app.services.eta_engine.predict_eta_adjustment")
@patch("app.services.eta_engine.get_settings")
def test_eta_engine_ml_toggle(mock_settings, mock_predict):
    # Case 1: ML is disabled in settings
    mock_settings.return_value.USE_ML_FOR_PROD = False
    mock_predict.return_value = 120.0

    final, h_eta, mode = get_final_eta(9.0, 38.0, 9.1, 38.1)
    assert mode == "heuristic"

    # Case 2: ML is enabled
    mock_settings.return_value.USE_ML_FOR_PROD = True
    final, h_eta, mode = get_final_eta(9.0, 38.0, 9.1, 38.1)
    assert mode == "ml"
    assert final == h_eta + 120.0
