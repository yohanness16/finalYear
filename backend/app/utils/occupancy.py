"""Helpers for resolving occupancy from telemetry payloads."""

from __future__ import annotations

from typing import Any

from app.services.cv_engine import estimate_density


def _coerce_occupancy(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return max(0, min(2, int(value)))
    except (TypeError, ValueError):
        return None


def resolve_occupancy_level(
    pixel_count: int | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> int:
    """Resolve occupancy from telemetry payload fields.

    Priority:
    1. top-level `occupancy_level`
    2. top-level `crowd_density`
    3. nested `cv.occupancy_level`
    4. nested `cv.crowd_density`
    5. fallback estimate from `pixel_count`
    6. default 0
    """
    if raw_payload:
        for key in ("occupancy_level", "crowd_density"):
            occupancy = _coerce_occupancy(raw_payload.get(key))
            if occupancy is not None:
                return occupancy

        cv_payload = raw_payload.get("cv")
        if isinstance(cv_payload, dict):
            for key in ("occupancy_level", "crowd_density"):
                occupancy = _coerce_occupancy(cv_payload.get(key))
                if occupancy is not None:
                    return occupancy

    if pixel_count is not None:
        return max(0, min(2, int(estimate_density(pixel_count))))

    return 0
