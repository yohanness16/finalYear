"""Tests for route ETA projection used by live telemetry publishing."""

from app.models.stop import Stop
from app.services.route_eta import estimate_route_stop_eta_payloads


def test_estimate_route_stop_eta_payloads_builds_per_stop_snapshots():
    stops = [
        Stop(id=1, name="A", lat=9.0, lon=38.7, base_dwell_time=30, peak_multiplier=1.0),
        Stop(id=2, name="B", lat=9.01, lon=38.71, base_dwell_time=45, peak_multiplier=1.5),
    ]

    payloads = estimate_route_stop_eta_payloads(
        lat=9.005,
        lon=38.705,
        speed_kmh=30.0,
        occupancy_level=2,
        route_number="12",
        route_id=1,
        route_stops=stops,
    )

    assert set(payloads) == {1, 2}
    assert payloads[1]["route_number"] == "12"
    assert payloads[1]["stop_name"] == "A"
    assert payloads[1]["eta_seconds"] > 0
    assert payloads[2]["occupancy_level"] == 2
    assert payloads[2]["distance_m"] > 0
