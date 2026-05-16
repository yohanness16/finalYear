"""Tests for ETA calculation."""

from app.services.eta_calc import calculate_eta_heuristic, haversine_meters


def test_haversine():
    # Addis Ababa approx
    lat1, lon1 = 9.03, 38.74
    lat2, lon2 = 9.05, 38.76
    d = haversine_meters(lat1, lon1, lat2, lon2)
    assert d > 0
    assert d < 10000  # Should be a few km


def test_eta_heuristic():
    lat1, lon1 = 9.03, 38.74
    lat2, lon2 = 9.05, 38.76
    eta = calculate_eta_heuristic(lat1, lon1, lat2, lon2, num_stops=3)
    assert eta > 0
