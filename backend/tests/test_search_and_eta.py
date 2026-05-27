"""Tests for search ETA and bus data in responses."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_point_to_point_response_structure(client: AsyncClient):
    """Point-to-point should return buses array alongside etas."""
    # Build mock stops with lat/lon for direction/distance calculations
    mock_stop_a = MagicMock()
    mock_stop_a.id = 1
    mock_stop_a.name = "Stop A"
    mock_stop_a.lat = 9.02
    mock_stop_a.lon = 38.73
    mock_stop_a.base_dwell_time = 30
    mock_stop_a.peak_multiplier = 1.0

    mock_stop_b = MagicMock()
    mock_stop_b.id = 2
    mock_stop_b.name = "Stop B"
    mock_stop_b.lat = 9.04
    mock_stop_b.lon = 38.75
    mock_stop_b.base_dwell_time = 30
    mock_stop_b.peak_multiplier = 1.0

    mock_route_obj = MagicMock()
    mock_route_obj.id = 1
    mock_route_obj.route_number = "12"
    mock_route_obj.name = "Test Route"

    with (
        patch("app.api.v1.search.crud_route") as mock_route,
        patch("app.api.v1.search.crud_vehicle") as mock_vehicle,
        patch("app.api.v1.search.get_redis") as mock_redis,
        patch("app.api.v1.search.get_recent_coords", new_callable=AsyncMock) as mock_coords,
    ):
        mock_route.get_stop_by_id = AsyncMock(
            side_effect=[mock_stop_a, mock_stop_b]
        )
        mock_route.get_routes_through_stops = AsyncMock(
            return_value=[mock_route_obj]
        )
        mock_route.get_route_stops_ordered = AsyncMock(
            return_value=[mock_stop_a, mock_stop_b]
        )
        mock_vehicle.get_live_positions = AsyncMock(
            return_value={
                "1": {
                    "vehicle_id": 1,
                    "plate_number": "ABC-123",
                    "lat": 9.025,
                    "lon": 38.735,
                    "route_id": 1,
                    "occupancy_level": 1,
                    "assignment_id": 1,
                    "speed": 30.0,
                    "timestamp": 1700000000,
                }
            }
        )
        # Bus is moving forward (from stop_a toward stop_b)
        mock_coords.return_value = [
            {"lat": 9.025, "lon": 38.735},
            {"lat": 9.021, "lon": 38.731},
        ]
        redis_mock = AsyncMock()
        redis_mock.hgetall = AsyncMock(
            return_value={
                "eta_seconds": "120",
                "bus_plate": "ABC-123",
                "vehicle_id": "1",
            }
        )
        mock_redis.return_value = redis_mock

        resp = await client.post(
            "/api/v1/search/point-to-point",
            json={
                "start_stop_id": 1,
                "end_stop_id": 2,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "routes" in data
        assert len(data["routes"]) == 1
        assert "buses" in data["routes"][0]
        assert "etas" in data["routes"][0]


@pytest.mark.asyncio
async def test_eta_payload_includes_bus_plate():
    """ETA payload dict should contain bus_plate and vehicle_id."""
    from app.services.route_eta import estimate_route_stop_eta_payloads

    mock_stop = MagicMock()
    mock_stop.id = 42
    mock_stop.name = "Test Stop"
    mock_stop.lat = 9.03
    mock_stop.lon = 38.74
    mock_stop.base_dwell_time = 30
    mock_stop.peak_multiplier = 1.0

    payloads = estimate_route_stop_eta_payloads(
        lat=9.03,
        lon=38.74,
        speed_kmh=30.0,
        occupancy_level=1,
        route_number="12",
        route_id=1,
        route_stops=[mock_stop],
        plate_number="ABC-123",
        vehicle_id=5,
    )
    assert 42 in payloads
    assert payloads[42]["bus_plate"] == "ABC-123"
    assert payloads[42]["vehicle_id"] == "5"
