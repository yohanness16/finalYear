"""GPS outlier rejection tests + route validation tests."""

from app.services.route_validation import (
    _point_to_segment_distance_m,
    find_nearest_stop,
    is_on_route,
)
from app.utils.gps_validation import get_average_coord, haversine_meters, is_valid_coord


class TestGpsOutlierDetection:
    """Verify GPS outlier detection and fallback (existing tests)."""

    def test_haversine_meters(self):
        d = haversine_meters(9.03, 38.74, 9.05, 38.76)
        assert d > 0
        assert d < 10000

    def test_is_valid_coord_empty_history(self):
        assert is_valid_coord(9.03, 38.74, []) is True

    def test_is_valid_coord_plausible(self):
        last = [{"lat": 9.03, "lon": 38.74}]
        assert is_valid_coord(9.031, 38.741, last) is True

    def test_is_valid_coord_outlier(self):
        last = [{"lat": 9.03, "lon": 38.74}]
        assert is_valid_coord(10.0, 40.0, last) is False

    def test_get_average_coord(self):
        coords = [{"lat": 9.0, "lon": 38.0}, {"lat": 10.0, "lon": 40.0}]
        avg = get_average_coord(coords)
        assert avg == (9.5, 39.0)

    def test_get_average_coord_empty(self):
        assert get_average_coord([]) is None


class TestIsOnRouteRelaxed:
    """Verify the relaxed 500m threshold and segment projection."""

    def _make_stop(self, stop_id: int, lat: float, lon: float):
        from app.models.stop import Stop
        return Stop(
            id=stop_id,
            name=f"Stop_{stop_id}",
            lat=lat,
            lon=lon,
            base_dwell_time=30,
            peak_multiplier=1.0,
        )

    def test_near_stop_passes(self):
        """A point within 500m of a stop should pass."""
        stops = [self._make_stop(1, 9.032, 38.752)]
        assert is_on_route(9.0325, 38.7525, stops) is True

    def test_far_from_all_stops_fails(self):
        """A point 2km from the nearest stop should fail."""
        stops = [self._make_stop(1, 9.032, 38.752)]
        assert is_on_route(9.050, 38.770, stops) is False

    def test_between_stops_on_segment_passes(self):
        """A point between two stops (on the segment) should pass even if
        far from either stop individually."""
        stops = [
            self._make_stop(1, 9.030, 38.750),
            self._make_stop(2, 9.050, 38.770),
        ]
        mid_lat = (9.030 + 9.050) / 2
        mid_lon = (38.750 + 38.770) / 2
        assert is_on_route(mid_lat, mid_lon, stops) is True

    def test_empty_stops_always_passes(self):
        """No route stops = cannot validate, so pass."""
        assert is_on_route(9.0, 38.0, []) is True

    def test_single_stop_near(self):
        stops = [self._make_stop(1, 9.032, 38.752)]
        assert is_on_route(9.032, 38.752, stops) is True

    def test_single_stop_far(self):
        stops = [self._make_stop(1, 9.032, 38.752)]
        assert is_on_route(9.100, 38.800, stops) is False

    def test_threshold_is_configurable(self):
        stops = [self._make_stop(1, 9.032, 38.752)]
        # ~300m away — passes with 500m default
        assert is_on_route(9.035, 38.755, stops, max_off_route_m=500.0) is True
        # But fails with 100m threshold
        assert is_on_route(9.035, 38.755, stops, max_off_route_m=100.0) is False


class TestPointToSegmentDistance:
    """Verify the point-to-segment distance calculation."""

    def test_point_on_segment(self):
        """Point roughly on the segment should give near-zero distance."""
        d = _point_to_segment_distance_m(
            9.040, 38.760,
            9.030, 38.750,
            9.050, 38.770,
        )
        assert d < 100  # equirectangular approximation tolerance

    def test_point_at_segment_end(self):
        d = _point_to_segment_distance_m(
            9.050, 38.770,
            9.030, 38.750,
            9.050, 38.770,
        )
        assert d < 50

    def test_zero_length_segment(self):
        d = _point_to_segment_distance_m(
            9.032, 38.752,
            9.030, 38.750,
            9.030, 38.750,
        )
        assert d > 0
        assert d < 500


class TestFindNearestStop:
    """Verify nearest stop finding."""

    def test_finds_closest(self):
        from app.models.stop import Stop

        stops = [
            Stop(id=1, name="Far", lat=9.10, lon=38.80, base_dwell_time=30, peak_multiplier=1.0),
            Stop(id=2, name="Near", lat=9.032, lon=38.752, base_dwell_time=30, peak_multiplier=1.0),
            Stop(id=3, name="Medium", lat=9.05, lon=38.76, base_dwell_time=30, peak_multiplier=1.0),
        ]
        nearest = find_nearest_stop(9.032, 38.752, stops)
        assert nearest is not None
        assert nearest.id == 2

    def test_empty_returns_none(self):
        assert find_nearest_stop(9.0, 38.0, []) is None
