from app.services.ml_features import build_feature_dict, build_feature_vector, FEATURE_NAMES


def test_feature_vector_length():
    features = build_feature_dict(
        route_id=1,
        stop_id=2,
        stop_sequence=3,
        remaining_stops=4,
        distance_m=123.4,
        base_dwell_time=30,
        peak_multiplier=1.5,
        hour=8,
        day_of_week=2,
        is_peak=1,
        occupancy_level=2,
        heuristic_eta=95.0,
    )
    vector = build_feature_vector(features)
    assert len(vector) == len(FEATURE_NAMES)
