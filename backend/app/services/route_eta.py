"""Estimate ETA values from the current bus position to route stops."""

from __future__ import annotations

import time
from typing import Any

from app.core.config import get_settings
from app.models.stop import Stop
from app.services.ai_predictor import model_loaded, predict_eta_adjustment
from app.services.eta_calc import calculate_eta_heuristic
from app.services.ml_features import build_feature_dict, time_features
from app.utils.gps_validation import haversine_meters


def _nearest_stop_index(lat: float, lon: float, route_stops: list[Stop]) -> int:
    """Approximate current progress by the nearest stop index."""
    if not route_stops:
        return 0
    nearest_idx = 0
    nearest_dist = None
    for idx, stop in enumerate(route_stops):
        dist = haversine_meters(lat, lon, stop.lat, stop.lon)
        if nearest_dist is None or dist < nearest_dist:
            nearest_dist = dist
            nearest_idx = idx
    return nearest_idx


def estimate_route_stop_eta_payloads(
    lat: float,
    lon: float,
    speed_kmh: float,
    occupancy_level: int,
    route_number: str,
    route_id: int | None,
    route_stops: list[Stop],
) -> dict[int, dict[str, Any]]:
    """Build Redis-ready ETA payloads keyed by stop_id."""
    if not route_stops:
        return {}

    speed_ms = max(speed_kmh / 3.6, 6.0)
    occupancy_multiplier = {0: 1.0, 1: 1.12, 2: 1.28}.get(occupancy_level, 1.0)
    payloads: dict[int, dict[str, Any]] = {}
    computed_at = int(time.time())
    nearest_idx = _nearest_stop_index(lat, lon, route_stops)
    stop_count = len(route_stops)
    settings = get_settings()
    use_ml = bool(settings.USE_ML_FOR_PROD and model_loaded())
    hour, dow, is_peak = time_features(None)

    segment_adjustments: list[float] = []
    if use_ml and stop_count > 1:
        for seg_idx in range(1, stop_count):
            prev_stop = route_stops[seg_idx - 1]
            curr_stop = route_stops[seg_idx]
            segment_distance = haversine_meters(
                prev_stop.lat,
                prev_stop.lon,
                curr_stop.lat,
                curr_stop.lon,
            )
            heuristic_segment = calculate_eta_heuristic(
                prev_stop.lat,
                prev_stop.lon,
                curr_stop.lat,
                curr_stop.lon,
                num_stops=1,
                base_dwell_time=curr_stop.base_dwell_time or 30,
                peak_multiplier=curr_stop.peak_multiplier,
                occupancy_level=occupancy_level,
            )
            remaining_stops = max(0, stop_count - (seg_idx + 1))
            features = build_feature_dict(
                route_id=int(route_id or 0),
                stop_id=int(curr_stop.id),
                stop_sequence=int(seg_idx + 1),
                remaining_stops=int(remaining_stops),
                distance_m=float(segment_distance),
                base_dwell_time=int(curr_stop.base_dwell_time or 30),
                peak_multiplier=float(curr_stop.peak_multiplier or 1.0),
                hour=hour,
                day_of_week=dow,
                is_peak=is_peak,
                occupancy_level=int(occupancy_level),
                heuristic_eta=float(heuristic_segment),
            )
            adjustment = predict_eta_adjustment(features)
            segment_adjustments.append(float(adjustment or 0.0))

    for idx, stop in enumerate(route_stops):
        distance_m = haversine_meters(lat, lon, stop.lat, stop.lon)
        travel_seconds = distance_m / speed_ms

        # Sum dwell for all intermediate stops ahead of current position.
        dwell_seconds = 0.0
        if idx >= nearest_idx:
            for s in route_stops[nearest_idx + 1 : idx + 1]:
                dwell_seconds += (s.base_dwell_time or 30) * (s.peak_multiplier or 1.0)
        else:
            dwell_seconds = (stop.base_dwell_time or 30) * (stop.peak_multiplier or 1.0)

        heuristic_eta = int(
            (travel_seconds + dwell_seconds * occupancy_multiplier) + 0.5
        )
        eta_seconds = heuristic_eta
        eta_mode = "heuristic"
        eta_ml_seconds = None
        if use_ml and idx > nearest_idx and segment_adjustments:
            residual_total = sum(segment_adjustments[nearest_idx + 1 : idx + 1])
            eta_ml_seconds = max(0, int(round(heuristic_eta + residual_total)))
            eta_seconds = eta_ml_seconds
            eta_mode = "ml"
        payloads[stop.id] = {
            "route_number": route_number,
            "stop_id": stop.id,
            "stop_name": stop.name,
            "eta_seconds": eta_seconds,
            "eta_heuristic_seconds": heuristic_eta,
            "eta_mode": eta_mode,
            "eta_ml_seconds": eta_ml_seconds,
            "distance_m": int(distance_m + 0.5),
            "speed_kmh": round(speed_kmh, 2),
            "occupancy_level": occupancy_level,
            "computed_at": computed_at,
        }

    return payloads
