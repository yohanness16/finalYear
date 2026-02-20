"""GPS outlier rejection tests."""

from app.utils.gps_validation import is_valid_coord, haversine_meters, get_average_coord


def test_haversine_meters():
    d = haversine_meters(9.03, 38.74, 9.05, 38.76)
    assert d > 0
    assert d < 10000


def test_is_valid_coord_empty_history():
    assert is_valid_coord(9.03, 38.74, []) is True


def test_is_valid_coord_plausible():
    last = [{"lat": 9.03, "lon": 38.74}]
    assert is_valid_coord(9.031, 38.741, last) is True


def test_is_valid_coord_outlier():
    last = [{"lat": 9.03, "lon": 38.74}]
    assert is_valid_coord(10.0, 40.0, last) is False


def test_get_average_coord():
    coords = [{"lat": 9.0, "lon": 38.0}, {"lat": 10.0, "lon": 40.0}]
    avg = get_average_coord(coords)
    assert avg == (9.5, 39.0)


def test_get_average_coord_empty():
    assert get_average_coord([]) is None
