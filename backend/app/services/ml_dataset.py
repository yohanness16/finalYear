"""Build ML training datasets from trip_history and route metadata."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.assignment import Assignment
from app.models.route import Route, RouteStop
from app.models.stop import Stop
from app.models.trip_history import TripHistory
from app.services.eta_calc import calculate_eta_heuristic, haversine_meters
from app.services.ml_features import (
    build_feature_dict,
    build_feature_vector,
    time_features,
)


class RouteMaps:
    def __init__(self, route: Route):
        self.route_id = int(route.id)
        stops = [rs for rs in (route.route_stops or []) if rs.stop is not None]
        stops_sorted = sorted(stops, key=lambda rs: rs.sequence_order)
        self.order_to_stop: dict[int, Stop] = {
            rs.sequence_order: rs.stop for rs in stops_sorted
        }
        self.stop_to_order: dict[int, int] = {
            rs.stop_id: rs.sequence_order for rs in stops_sorted
        }
        self.stop_count = len(stops_sorted)

    def get_prev_stop(self, stop_id: int) -> Stop | None:
        order = self.stop_to_order.get(stop_id)
        if order is None:
            return None
        return self.order_to_stop.get(order - 1)

    def get_order(self, stop_id: int) -> int | None:
        return self.stop_to_order.get(stop_id)


async def build_training_rows(db: AsyncSession) -> list[dict[str, Any]]:
    """Return enriched training rows with features and targets."""
    result = await db.execute(
        select(TripHistory)
        .where(TripHistory.arrival_time.isnot(None))
        .options(
            selectinload(TripHistory.stop),
            selectinload(TripHistory.assignment)
            .selectinload(Assignment.route)
            .selectinload(Route.route_stops)
            .selectinload(RouteStop.stop),
        )
    )
    rows = list(result.scalars().all())
    if not rows:
        return []

    route_maps: dict[int, RouteMaps] = {}
    grouped: dict[int, list[TripHistory]] = defaultdict(list)
    for row in rows:
        grouped[row.assignment_id].append(row)

    training_rows: list[dict[str, Any]] = []
    for _, history in grouped.items():
        history.sort(key=lambda r: r.arrival_time or datetime.min)
        prev: TripHistory | None = None
        for entry in history:
            if prev is None:
                prev = entry
                continue
            if not entry.assignment or not entry.assignment.route or not entry.stop:
                prev = entry
                continue
            if entry.arrival_time is None or prev.arrival_time is None:
                prev = entry
                continue

            route = entry.assignment.route
            if route.id not in route_maps:
                route_maps[route.id] = RouteMaps(route)
            maps = route_maps[route.id]

            order = maps.get_order(entry.stop_id)
            if order is None or maps.stop_count <= 0:
                prev = entry
                continue
            prev_stop = maps.get_prev_stop(entry.stop_id)
            if prev_stop is None:
                prev = entry
                continue

            actual_segment = max(
                1, int((entry.arrival_time - prev.arrival_time).total_seconds())
            )
            occupancy = int(entry.occupancy_level or 0)
            hour, dow, is_peak = time_features(entry.arrival_time)
            distance_m = haversine_meters(
                prev_stop.lat, prev_stop.lon, entry.stop.lat, entry.stop.lon
            )
            heuristic_eta = calculate_eta_heuristic(
                prev_stop.lat,
                prev_stop.lon,
                entry.stop.lat,
                entry.stop.lon,
                num_stops=1,
                base_dwell_time=entry.stop.base_dwell_time or 30,
                peak_multiplier=entry.stop.peak_multiplier,
                occupancy_level=occupancy,
            )
            remaining_stops = max(0, maps.stop_count - order)
            features = build_feature_dict(
                route_id=int(route.id),
                stop_id=int(entry.stop_id),
                stop_sequence=int(order),
                remaining_stops=int(remaining_stops),
                distance_m=float(distance_m),
                base_dwell_time=int(entry.stop.base_dwell_time or 30),
                peak_multiplier=float(entry.stop.peak_multiplier or 1.0),
                hour=hour,
                day_of_week=dow,
                is_peak=is_peak,
                occupancy_level=occupancy,
                heuristic_eta=float(heuristic_eta),
            )
            target_residual = float(actual_segment - heuristic_eta)
            training_rows.append(
                {
                    "assignment_id": entry.assignment_id,
                    "route_id": route.id,
                    "stop_id": entry.stop_id,
                    "arrival_time": entry.arrival_time,
                    "actual_segment": float(actual_segment),
                    "heuristic_eta": float(heuristic_eta),
                    "target_residual": target_residual,
                    "features": features,
                    "feature_vector": build_feature_vector(features),
                }
            )
            prev = entry

    return training_rows


def rows_to_xy(rows: list[dict[str, Any]]) -> tuple[list[list[float]], list[float]]:
    """Return X, y for model training."""
    X = [row["feature_vector"] for row in rows]
    y = [row["target_residual"] for row in rows]
    return X, y
