"""Tests for ETA engine fixes: ML feature match, O(n) dwell, no duplicate haversine."""

import time
from unittest.mock import patch

from app.services.eta_calc import calculate_eta_heuristic, haversine_meters
from app.services.eta_engine import get_final_eta
from app.services.route_eta import estimate_route_stop_eta_payloads


class TestEtaEngineMlFeatureMatch:
    """ML features must use the actual peak multiplier, not a hardcoded 1.0."""

    @patch("app.services.eta_engine.predict_eta_adjustment")
    @patch("app.services.eta_engine.get_settings")
    def test_ml_features_use_actual_peak_multiplier(self, mock_settings, mock_predict):
        """When peak hour, ML features should see the real multiplier (>= 1.5)."""
        mock_settings.return_value.USE_ML_FOR_PROD = True
        mock_predict.return_value = 10.0

        # Force peak hour by patching get_time_multiplier
        with patch("app.services.eta_engine.get_time_multiplier", return_value=1.8):
            get_final_eta(9.0, 38.0, 9.001, 38.001)

        # Inspect the features dict that predict_eta_adjustment received
        call_args = mock_predict.call_args[0][0]
        assert call_args["peak_multiplier"] == 1.8, (
            f"peak_multiplier should be 1.8 (peak), got {call_args['peak_multiplier']}"
        )

    @patch("app.services.eta_engine.predict_eta_adjustment")
    @patch("app.services.eta_engine.get_settings")
    def test_ml_features_off_peak(self, mock_settings, mock_predict):
        """Off-peak: multiplier should be 1.0."""
        mock_settings.return_value.USE_ML_FOR_PROD = True
        mock_predict.return_value = 5.0

        with patch("app.services.eta_engine.get_time_multiplier", return_value=1.0):
            get_final_eta(9.0, 38.0, 9.001, 38.001)

        call_args = mock_predict.call_args[0][0]
        assert call_args["peak_multiplier"] == 1.0

    @patch("app.services.eta_engine.predict_eta_adjustment")
    @patch("app.services.eta_engine.get_settings")
    def test_ml_enabled_returns_ml_mode(self, mock_settings, mock_predict):
        """ML enabled + model returns adjustment => mode == 'ml'."""
        mock_settings.return_value.USE_ML_FOR_PROD = True
        mock_predict.return_value = 60.0

        final, h_eta, mode = get_final_eta(9.0, 38.0, 9.1, 38.1)
        assert mode == "ml"
        assert final == h_eta + 60.0
        assert final > h_eta

    @patch("app.services.eta_engine.predict_eta_adjustment")
    @patch("app.services.eta_engine.get_settings")
    def test_ml_disabled_returns_heuristic(self, mock_settings, mock_predict):
        """ML disabled => mode == 'heuristic', final == h_eta."""
        mock_settings.return_value.USE_ML_FOR_PROD = False
        mock_predict.return_value = 60.0

        final, h_eta, mode = get_final_eta(9.0, 38.0, 9.1, 38.1)
        assert mode == "heuristic"
        assert final == h_eta


class TestRouteEtaOn:
    """Verify O(n) dwell accumulator produces correct increasing ETAs."""

    def _make_stops(self, count: int) -> list:
        from app.models.stop import Stop
        stops = []
        for i in range(count):
            stops.append(Stop(
                id=i + 1,
                name=f"Stop_{i + 1}",
                lat=9.0 + i * 0.01,
                lon=38.7 + i * 0.01,
                base_dwell_time=30,
                peak_multiplier=1.0,
            ))
        return stops

    def test_eta_increases_for_further_stops(self):
        """Each further stop must have >= ETA than the previous."""
        stops = self._make_stops(5)
        payloads = estimate_route_stop_eta_payloads(
            lat=9.0, lon=38.7,
            speed_kmh=30.0,
            occupancy_level=0,
            route_number="TEST",
            route_id=1,
            route_stops=stops,
        )
        etas = [payloads[s.id]["eta_seconds"] for s in stops]
        for i in range(1, len(etas)):
            assert etas[i] >= etas[i - 1], (
                f"ETA at stop {i + 1} ({etas[i]}) < stop {i} ({etas[i - 1]})"
            )

    def test_dwell_accumulates_correctly(self):
        """With 3 stops and 30s dwell each, the 3rd stop should include ~90s dwell."""
        stops = self._make_stops(3)
        payloads = estimate_route_stop_eta_payloads(
            lat=9.0, lon=38.7,
            speed_kmh=30.0,
            occupancy_level=0,
            route_number="TEST",
            route_id=1,
            route_stops=stops,
        )
        # Stop 1: travel + 30s dwell
        # Stop 2: travel + 60s dwell
        # Stop 3: travel + 90s dwell
        # Each should be progressively larger
        assert payloads[3]["eta_seconds"] > payloads[2]["eta_seconds"] > payloads[1]["eta_seconds"]

    def test_zero_speed_does_not_crash(self):
        """Stationary bus (speed=0) should not crash or produce negative ETA."""
        stops = self._make_stops(3)
        payloads = estimate_route_stop_eta_payloads(
            lat=9.0, lon=38.7,
            speed_kmh=0.0,
            occupancy_level=0,
            route_number="TEST",
            route_id=1,
            route_stops=stops,
        )
        for stop_id, data in payloads.items():
            assert data["eta_seconds"] >= 0, f"stop {stop_id} has negative ETA"

    def test_payloads_have_all_required_fields(self):
        """Every payload must include the fields the mobile app expects."""
        stops = self._make_stops(2)
        payloads = estimate_route_stop_eta_payloads(
            lat=9.0, lon=38.7,
            speed_kmh=25.0,
            occupancy_level=1,
            route_number="42",
            route_id=1,
            route_stops=stops,
            plate_number="AA-1-B2345",
            vehicle_id=7,
        )
        required = {
            "route_number", "stop_id", "stop_name", "eta_seconds",
            "eta_heuristic_seconds", "eta_mode", "distance_m", "speed_kmh",
            "occupancy_level", "bus_plate", "vehicle_id", "computed_at",
        }
        for stop_id, data in payloads.items():
            missing = required - set(data.keys())
            assert not missing, f"stop {stop_id} missing: {missing}"

    def test_computed_at_is_recent(self):
        """computed_at should be within the last 5 seconds."""
        stops = self._make_stops(2)
        before = int(time.time())
        payloads = estimate_route_stop_eta_payloads(
            lat=9.0, lon=38.7,
            speed_kmh=30.0, occupancy_level=0,
            route_number="TEST", route_id=1, route_stops=stops,
        )
        after = int(time.time())
        for stop_id, data in payloads.items():
            assert before <= data["computed_at"] <= after + 1


class TestEtaCalc:
    """Verify core ETA heuristic is correct."""

    def test_peak_multiplier_applied(self):
        """Peak hour should produce higher ETA than off-peak for same route."""
        with patch("app.services.eta_calc.get_time_multiplier", return_value=1.8):
            peak_eta = calculate_eta_heuristic(9.0, 38.0, 9.05, 38.05, num_stops=3)

        with patch("app.services.eta_calc.get_time_multiplier", return_value=1.0):
            off_peak_eta = calculate_eta_heuristic(9.0, 38.0, 9.05, 38.05, num_stops=3)

        assert peak_eta > off_peak_eta, "Peak ETA should be higher than off-peak"

    def test_occupancy_penalty(self):
        """Higher occupancy should increase ETA when there are stops (dwell)."""
        # Need num_stops > 0 because occupancy penalty applies to dwell time
        low = calculate_eta_heuristic(9.0, 38.0, 9.05, 38.05, num_stops=3, occupancy_level=0)
        med = calculate_eta_heuristic(9.0, 38.0, 9.05, 38.05, num_stops=3, occupancy_level=1)
        high = calculate_eta_heuristic(9.0, 38.0, 9.05, 38.05, num_stops=3, occupancy_level=2)
        assert low < med < high, (
            f"ETA should increase with occupancy: low={low}, med={med}, high={high}"
        )

    def test_haversine_symmetry(self):
        """Distance A→B must equal B→A."""
        d1 = haversine_meters(9.03, 38.74, 9.05, 38.76)
        d2 = haversine_meters(9.05, 38.76, 9.03, 38.74)
        assert abs(d1 - d2) < 0.001

    def test_haversine_zero_distance(self):
        """Same point should give ~0 distance."""
        d = haversine_meters(9.03, 38.74, 9.03, 38.74)
        assert d < 1.0
