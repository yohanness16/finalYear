"""Tests for ETA injection into WebSocket broadcast pipeline."""

import time
from unittest.mock import AsyncMock, patch

import pytest

from app.services.live_broadcast import broadcast_vehicle_position
from app.services.route_eta import estimate_route_stop_eta_payloads
from app.services.search_helpers import compute_live_eta


class TestBroadcastVehiclePositionWithEta:
    """Verify that broadcast_vehicle_position includes eta_payloads in WS message."""

    @pytest.mark.asyncio
    async def test_broadcast_includes_eta_payloads(self):
        """eta_payloads should appear in the broadcast WS message."""
        eta_payloads = {
            1: {"stop_name": "Stop A", "eta_seconds": 60, "distance_m": 500, "computed_at": int(time.time())},
            2: {"stop_name": "Stop B", "eta_seconds": 120, "distance_m": 1000, "computed_at": int(time.time())},
        }

        with patch("app.services.live_broadcast.manager") as mock_manager:
            mock_manager.broadcast = AsyncMock()
            await broadcast_vehicle_position(
                vehicle_id=1,
                plate_number="ABC-1234",
                lat=9.032, lon=38.752,
                speed=25.0,
                route_id=1,
                timestamp=time.time(),
                occupancy_level=1,
                eta_payloads=eta_payloads,
            )

            mock_manager.broadcast.assert_called_once()
            call_args = mock_manager.broadcast.call_args[0][0]
            assert call_args["type"] == "vehicle_position"
            assert "eta_payloads" in call_args
            assert "1" in call_args["eta_payloads"]
            assert call_args["eta_payloads"]["1"]["stop_name"] == "Stop A"
            assert call_args["eta_payloads"]["1"]["eta_seconds"] == 60
            assert call_args["eta_payloads"]["2"]["stop_name"] == "Stop B"

    @pytest.mark.asyncio
    async def test_broadcast_no_eta_when_none(self):
        """When eta_payloads is None, the field should not appear in the message."""
        with patch("app.services.live_broadcast.manager") as mock_manager:
            mock_manager.broadcast = AsyncMock()
            await broadcast_vehicle_position(
                vehicle_id=1,
                plate_number="ABC-1234",
                lat=9.032, lon=38.752,
                speed=25.0,
                route_id=None,
                timestamp=time.time(),
                eta_payloads=None,
            )

            call_args = mock_manager.broadcast.call_args[0][0]
            assert "eta_payloads" not in call_args

    @pytest.mark.asyncio
    async def test_broadcast_eta_stop_ids_as_strings(self):
        """Stop IDs in eta_payloads must be strings (JSON-compatible keys)."""
        eta_payloads = {
            42: {"stop_name": "Terminal", "eta_seconds": 300, "distance_m": 2000, "computed_at": int(time.time())},
        }

        with patch("app.services.live_broadcast.manager") as mock_manager:
            mock_manager.broadcast = AsyncMock()
            await broadcast_vehicle_position(
                vehicle_id=3, plate_number="XYZ-999",
                lat=9.05, lon=38.76, speed=0.0, route_id=5,
                timestamp=1700000000.0, eta_payloads=eta_payloads,
            )

            call_args = mock_manager.broadcast.call_args[0][0]
            assert "42" in call_args["eta_payloads"]
            # Integer keys should not leak through
            assert 42 not in call_args["eta_payloads"]

    @pytest.mark.asyncio
    async def test_broadcast_preserves_all_base_fields(self):
        """Adding eta_payloads must not break any existing base fields."""
        with patch("app.services.live_broadcast.manager") as mock_manager:
            mock_manager.broadcast = AsyncMock()
            ts = 1700000000.0
            await broadcast_vehicle_position(
                vehicle_id=7, plate_number="DEF-5678",
                lat=9.1, lon=38.8, speed=35.5,
                route_id=10, timestamp=ts,
                bus_type="Anbessa", occupancy_level=2,
                eta_payloads={1: {"stop_name": "X", "eta_seconds": 10, "distance_m": 100, "computed_at": int(ts)}},
            )

            call_args = mock_manager.broadcast.call_args[0][0]
            assert call_args["vehicle_id"] == 7
            assert call_args["plate_number"] == "DEF-5678"
            assert call_args["lat"] == 9.1
            assert call_args["lon"] == 38.8
            assert call_args["speed"] == 35.5
            assert call_args["route_id"] == 10
            assert call_args["timestamp"] == ts
            assert call_args["bus_type"] == "Anbessa"
            assert call_args["occupancy_level"] == 2
            assert "eta_payloads" in call_args


class TestEstimateRouteStopEtaPayloads:
    """Verify ETA engine output structure."""

    def test_eta_payloads_have_required_fields(self):
        """All payload entries must contain the fields frontends expect."""
        from app.models.stop import Stop

        stops = [
            Stop(id=1, name="Origin", lat=9.032, lon=38.752, base_dwell_time=30, peak_multiplier=1.0),
            Stop(id=2, name="Mid Stop", lat=9.040, lon=38.758, base_dwell_time=30, peak_multiplier=1.2),
            Stop(id=3, name="Terminal", lat=9.050, lon=38.765, base_dwell_time=45, peak_multiplier=1.0),
        ]

        payloads = estimate_route_stop_eta_payloads(
            lat=9.032, lon=38.752,
            speed_kmh=30.0,
            occupancy_level=1,
            route_number="110",
            route_id=1,
            route_stops=stops,
        )

        assert len(payloads) == 3
        required_keys = {"stop_name", "eta_seconds", "distance_m", "computed_at",
                         "speed_kmh", "occupancy_level", "route_number", "stop_id",
                         "eta_heuristic_seconds", "eta_mode"}
        for stop_id, data in payloads.items():
            for key in required_keys:
                assert key in data, f"stop {stop_id} missing key: {key}"

    def test_eta_increases_with_distance(self):
        """Further stops should have larger or equal ETA."""
        from app.models.stop import Stop

        stops = [
            Stop(id=1, name="Near", lat=9.032, lon=38.752, base_dwell_time=30, peak_multiplier=1.0),
            Stop(id=2, name="Far", lat=9.060, lon=38.780, base_dwell_time=30, peak_multiplier=1.0),
        ]

        payloads = estimate_route_stop_eta_payloads(
            lat=9.032, lon=38.752,
            speed_kmh=40.0, occupancy_level=0,
            route_number="220", route_id=2, route_stops=stops,
        )

        assert payloads[2]["eta_seconds"] > payloads[1]["eta_seconds"]

    def test_empty_stops_returns_empty(self):
        """No stops should produce no ETAs — no crash."""
        payloads = estimate_route_stop_eta_payloads(
            lat=9.032, lon=38.752,
            speed_kmh=30.0, occupancy_level=0,
            route_number="999", route_id=99, route_stops=[],
        )
        assert payloads == {}


class TestComputeLiveEta:
    """Verify live ETA adjustment subtracts elapsed time."""

    def test_live_eta_adjusts_for_elapsed(self):
        """ETA computed 100s ago at 300s should now be ~200s."""
        now = time.time()
        result = compute_live_eta(eta_seconds=300, computed_at=now - 100)
        assert 195 <= result <= 205

    def test_expired_eta_is_zero(self):
        """ETA that has already elapsed should clamp to 0."""
        now = time.time()
        result = compute_live_eta(eta_seconds=30, computed_at=now - 100)
        assert result == 0

    def test_invalid_computed_at_returns_none(self):
        """computed_at=0 (never computed) should return None."""
        result = compute_live_eta(eta_seconds=300, computed_at=0)
        assert result is None

    def test_negative_computed_at_returns_none(self):
        """Negative timestamp should return None."""
        result = compute_live_eta(eta_seconds=100, computed_at=-1)
        assert result is None

    def test_string_inputs_parsed(self):
        """String-typed inputs (from Redis) should be parsed."""
        now = time.time()
        result = compute_live_eta(eta_seconds="300", computed_at=str(now - 50))
        assert 245 <= result <= 255
