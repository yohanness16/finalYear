"""Tests for user-centric ETA endpoint and service."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch

from app.schemas.eta import BusEtaInfo, UserEtaRequest, UserEtaResponse
from app.services.user_eta import get_user_centric_eta


# ── Schema Tests ──────────────────────────────────────────────────────────────


class TestUserEtaSchemas:
    """Validate schema construction and defaults."""

    def test_user_eta_request_defaults(self):
        req = UserEtaRequest(current_stop_id=1, destination_stop_id=5)
        assert req.current_stop_id == 1
        assert req.destination_stop_id == 5
        assert req.next_n_buses == 3  # default

    def test_user_eta_request_custom_n(self):
        req = UserEtaRequest(current_stop_id=1, destination_stop_id=5, next_n_buses=5)
        assert req.next_n_buses == 5

    def test_bus_eta_info_construction(self):
        info = BusEtaInfo(
            vehicle_id=1,
            plate_number="ABC-123",
            route_number="12",
            eta_seconds=120,
            eta_live_seconds=115,
            destination_eta_seconds=300,
            total_eta_seconds=300,
            stops_between_user_and_bus=2,
            stops_between_user_and_dest=5,
            occupancy_level=1,
            direction="approaching",
        )
        assert info.vehicle_id == 1
        assert info.eta_live_seconds == 115
        assert info.direction == "approaching"

    def test_user_eta_response_construction(self):
        resp = UserEtaResponse(
            current_stop_name="Megenagna",
            destination_stop_name="Mexico",
            buses=[],
        )
        assert resp.current_stop_name == "Megenagna"
        assert resp.destination_stop_name == "Mexico"
        assert resp.buses == []


# ── Service Tests (mocked) ────────────────────────────────────────────────────


class TestGetUserCentricEta:
    """Test the get_user_centric_eta service function with mocked dependencies."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def mock_stop(self):
        """Create a mock Stop-like object."""
        from unittest.mock import MagicMock
        stop = MagicMock()
        stop.id = 1
        stop.name = "Megenagna"
        stop.lat = 9.0267
        stop.lon = 38.7613
        stop.base_dwell_time = 30
        return stop

    @pytest.fixture
    def mock_dest_stop(self):
        from unittest.mock import MagicMock
        stop = MagicMock()
        stop.id = 5
        stop.name = "Mexico"
        stop.lat = 8.9956
        stop.lon = 38.7385
        stop.base_dwell_time = 30
        return stop

    @pytest_asyncio.fixture
    def mock_route(self):
        """Create a mock Route-like object."""
        from unittest.mock import MagicMock
        route = MagicMock()
        route.id = 1
        route.route_number = "12"
        return route

    @pytest.fixture
    def mock_route_stops(self):
        """Create mock stops along a route."""
        from unittest.mock import MagicMock
        stops = []
        for i, (name, lat, lon) in enumerate([
            ("Megenagna", 9.0267, 38.7613),
            ("Bole Michael", 9.0198, 38.7556),
            ("Bole Road", 9.0144, 38.7504),
            ("Awareness", 9.0065, 38.7461),
            ("CMC", 9.0011, 38.7423),
            ("Mexico", 8.9956, 38.7385),
        ]):
            s = MagicMock()
            s.id = i + 1
            s.name = name
            s.lat = lat
            s.lon = lon
            s.base_dwell_time = 30
            s.peak_multiplier = 1.5
            stops.append(s)
        return stops

    @pytest.fixture
    def mock_live_positions(self):
        return {
            "1": {
                "vehicle_id": 1,
                "plate_number": "ABC-123",
                "lat": 9.0198,
                "lon": 38.7556,
                "speed": 25.0,
                "timestamp": 1717185600.0,
                "route_id": 1,
                "assignment_id": 1,
                "occupancy_level": 1,
            }
        }

    @pytest.mark.anyio
    async def test_no_routes_found(self, mock_db):
        """When no routes connect the two stops, return empty buses list."""
        stop_a = AsyncMock()
        stop_a.name = "StopA"
        stop_z = AsyncMock()
        stop_z.name = "StopZ"

        with patch("app.services.user_eta.crud_route") as mock_crud:
            mock_crud.get_stop_by_id = AsyncMock(side_effect=[stop_a, stop_z])
            mock_crud.get_routes_through_stops = AsyncMock(return_value=[])

            result = await get_user_centric_eta(mock_db, 1, 99)
            assert result.buses == []
            assert result.current_stop_name == "StopA"
            assert result.destination_stop_name == "StopZ"

    @pytest.mark.anyio
    async def test_no_active_buses(self, mock_db, mock_stop, mock_dest_stop):
        """When routes exist but no active buses, return empty list."""
        mock_route = AsyncMock()
        mock_route.id = 1
        mock_route.route_number = "12"

        with patch("app.services.user_eta.crud_route") as mock_crud, \
             patch("app.services.user_eta.crud_vehicle") as mock_veh:
            mock_crud.get_stop_by_id = AsyncMock(side_effect=[mock_stop, mock_dest_stop])
            mock_crud.get_routes_through_stops = AsyncMock(return_value=[mock_route])
            mock_crud.get_route_stops_ordered = AsyncMock(return_value=[])
            mock_veh.get_live_positions = AsyncMock(return_value={})

            result = await get_user_centric_eta(mock_db, 1, 5)
            assert result.buses == []

    @pytest.mark.anyio
    async def test_redis_eta_available(
        self, mock_db, mock_stop, mock_dest_stop, mock_route, mock_route_stops, mock_live_positions
    ):
        """When Redis has pre-computed ETA, return it in the response."""
        mock_route.id = 1
        mock_route.route_number = "12"

        redis_data_current = {
            "eta_seconds": "120",
            "computed_at": "1717185600",
            "stop_name": "Megenagna",
            "distance_m": "500",
        }
        redis_data_dest = {
            "eta_seconds": "300",
            "computed_at": "1717185600",
            "stop_name": "Mexico",
            "distance_m": "2000",
        }

        with patch("app.services.user_eta.crud_route") as mock_crud, \
             patch("app.services.user_eta.crud_vehicle") as mock_veh, \
             patch("app.services.user_eta.get_redis") as mock_get_redis, \
             patch("app.services.user_eta.infer_bus_direction", return_value=1):
            mock_crud.get_stop_by_id = AsyncMock(side_effect=[mock_stop, mock_dest_stop])
            mock_crud.get_routes_through_stops = AsyncMock(return_value=[mock_route])
            mock_crud.get_route_stops_ordered = AsyncMock(return_value=mock_route_stops)
            mock_veh.get_live_positions = AsyncMock(return_value=mock_live_positions)

            mock_redis = AsyncMock()
            mock_redis.hgetall = AsyncMock(side_effect=[redis_data_current, redis_data_dest])
            mock_get_redis.return_value = mock_redis

            result = await get_user_centric_eta(mock_db, 1, 6, next_n_buses=3)

            assert result.current_stop_name == "Megenagna"
            assert result.destination_stop_name == "Mexico"
            # Bus found with ETA
            if result.buses:
                bus = result.buses[0]
                assert bus.plate_number == "ABC-123"
                assert bus.route_number == "12"
                assert bus.direction == "approaching"

    @pytest.mark.anyio
    async def test_bus_direction_filtered(self, mock_db, mock_stop, mock_route_stops):
        """Buses heading away from the user's stop should be filtered out."""
        from unittest.mock import MagicMock
        mock_route = MagicMock()
        mock_route.id = 1
        mock_route.route_number = "12"

        mock_dest = MagicMock()
        mock_dest.id = 6
        mock_dest.name = "Mexico"
        mock_dest.lat = 8.9956
        mock_dest.lon = 38.7385

        # Bus that has already passed the user's stop (bus at idx 3, user at idx 0)
        live_positions = {
            "1": {
                "vehicle_id": 1,
                "plate_number": "PASSED-01",
                "lat": 9.0065,
                "lon": 38.7461,
                "speed": 25.0,
                "timestamp": 1717185600.0,
                "route_id": 1,
                "assignment_id": 1,
                "occupancy_level": 0,
            }
        }

        with patch("app.services.user_eta.crud_route") as mock_crud, \
             patch("app.services.user_eta.crud_vehicle") as mock_veh, \
             patch("app.services.user_eta.get_redis") as mock_get_redis, \
             patch("app.services.user_eta.infer_bus_direction", return_value=1):
            # Bus going forward = heading AWAY from user at stop idx 0
            mock_crud.get_stop_by_id = AsyncMock(side_effect=[mock_stop, mock_dest])
            mock_crud.get_routes_through_stops = AsyncMock(return_value=[mock_route])
            mock_crud.get_route_stops_ordered = AsyncMock(return_value=mock_route_stops)
            mock_veh.get_live_positions = AsyncMock(return_value=live_positions)

            mock_redis = AsyncMock()
            mock_redis.hgetall = AsyncMock(return_value={})  # No Redis data = filtered
            mock_get_redis.return_value = mock_redis

            result = await get_user_centric_eta(mock_db, 1, 6)
            # Bus should be filtered (wrong direction + no Redis ETA)
            assert result.buses == []


# ── Endpoint Integration Tests ─────────────────────────────────────────────────


class TestUserEtaEndpoint:
    """Test the POST /api/v1/eta/user-centric endpoint."""

    @pytest_asyncio.fixture
    async def client(self):
        from httpx import ASGITransport, AsyncClient
        from app.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    @pytest.mark.anyio
    async def test_endpoint_returns_200_with_valid_stops(self, client):
        """Valid request returns 200 with response structure."""
        with patch("app.api.v1.eta.get_user_centric_eta") as mock_svc:
            mock_svc.return_value = UserEtaResponse(
                current_stop_name="Megenagna",
                destination_stop_name="Mexico",
                buses=[],
            )
            resp = await client.post("/api/v1/eta/user-centric", json={
                "current_stop_id": 1,
                "destination_stop_id": 6,
                "next_n_buses": 3,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert "current_stop_name" in data
            assert "destination_stop_name" in data
            assert "buses" in data

    @pytest.mark.anyio
    async def test_endpoint_validation_missing_fields(self, client):
        """Missing required fields returns 422."""
        resp = await client.post("/api/v1/eta/user-centric", json={
            "current_stop_id": 1,
            # missing destination_stop_id
        })
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_endpoint_default_next_n(self, client):
        """Default next_n_buses=3 when not specified."""
        with patch("app.api.v1.eta.get_user_centric_eta") as mock_svc:
            mock_svc.return_value = UserEtaResponse(
                current_stop_name="A",
                destination_stop_name="B",
                buses=[],
            )
            resp = await client.post("/api/v1/eta/user-centric", json={
                "current_stop_id": 1,
                "destination_stop_id": 6,
            })
            assert resp.status_code == 200
            # Verify default was passed
            call_args = mock_svc.call_args
            assert call_args.kwargs["next_n_buses"] == 3
