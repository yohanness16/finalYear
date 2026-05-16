"""Unit tests for simulation helpers (no live API)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

SIM_DIR = Path(__file__).resolve().parents[1] / "simulation"
sys.path.insert(0, str(SIM_DIR))

from api_client import APIClient  # noqa: E402
from gps_utils import haversine_m, interpolate_gps  # noqa: E402
from route_loader import stops_from_route_detail  # noqa: E402


def test_interpolate_gps_point_count():
    pts = interpolate_gps(9.0, 38.0, 9.01, 38.0, steps=4)
    assert len(pts) == 5


def test_haversine_m_order_of_km_for_small_offset():
    d = haversine_m(9.0, 38.0, 9.01, 38.0)
    assert 900 < d < 1300


def test_stops_from_route_detail_order_and_dwell():
    payload = {
        "id": 1,
        "stops": [
            {
                "id": 10,
                "name": "A",
                "lat": 9.0,
                "lon": 38.0,
                "base_dwell_time": 45,
                "is_terminal": True,
            },
            {
                "id": 11,
                "name": "B",
                "lat": 9.01,
                "lon": 38.01,
                "base_dwell_time": 30,
                "is_terminal": False,
            },
        ],
    }
    stops = stops_from_route_detail(payload)
    assert [s["name"] for s in stops] == ["A", "B"]
    assert stops[0]["dwell"] == 45
    assert stops[1]["dwell"] == 30


def test_api_client_post_accepts_201():
    c = APIClient(base_url="http://test.invalid", label="t")
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"id": 42}
    c.client.post = MagicMock(return_value=mock_resp)
    out = c.post("/assignments/start", {"a": 1})
    assert out == {"id": 42}


def test_api_client_post_status_409():
    c = APIClient(base_url="http://test.invalid", label="t")
    mock_resp = MagicMock()
    mock_resp.status_code = 409
    mock_resp.json.return_value = {"detail": "Vehicle already has an active assignment"}
    c.client.post = MagicMock(return_value=mock_resp)
    code, body = c.post_status("/assignments/start", {})
    assert code == 409
    assert body["detail"].startswith("Vehicle")


def test_api_client_get_returns_list():
    c = APIClient(base_url="http://test.invalid", label="t")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"id": 1}, {"id": 2}]
    c.client.get = MagicMock(return_value=mock_resp)
    out = c.get("/assignments/active")
    assert out == [{"id": 1}, {"id": 2}]
