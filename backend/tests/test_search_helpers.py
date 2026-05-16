from app.models.stop import Stop
from app.services.search_helpers import infer_bus_direction, nearest_stop_index


def test_nearest_stop_index():
    stops = [
        Stop(id=1, name="A", lat=9.0, lon=38.0),
        Stop(id=2, name="B", lat=9.1, lon=38.1),
        Stop(id=3, name="C", lat=9.2, lon=38.2),
    ]
    idx = nearest_stop_index(9.11, 38.11, stops)
    assert idx == 1


def test_infer_bus_direction_forward():
    stops = [
        Stop(id=1, name="A", lat=9.0, lon=38.0),
        Stop(id=2, name="B", lat=9.1, lon=38.1),
        Stop(id=3, name="C", lat=9.2, lon=38.2),
    ]
    coords = [
        {"lat": 9.11, "lon": 38.11},
        {"lat": 9.01, "lon": 38.01},
    ]
    assert infer_bus_direction(coords, stops) == 1


def test_infer_bus_direction_reverse():
    stops = [
        Stop(id=1, name="A", lat=9.0, lon=38.0),
        Stop(id=2, name="B", lat=9.1, lon=38.1),
        Stop(id=3, name="C", lat=9.2, lon=38.2),
    ]
    coords = [
        {"lat": 9.01, "lon": 38.01},
        {"lat": 9.11, "lon": 38.11},
    ]
    assert infer_bus_direction(coords, stops) == -1


def test_infer_bus_direction_unknown():
    stops = [
        Stop(id=1, name="A", lat=9.0, lon=38.0),
        Stop(id=2, name="B", lat=9.1, lon=38.1),
    ]
    coords = [{"lat": 9.01, "lon": 38.01}]
    assert infer_bus_direction(coords, stops) is None
