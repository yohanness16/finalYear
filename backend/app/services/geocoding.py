"""Geocoding helpers for user-entered locations."""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings


async def geocode_text(query: str) -> dict[str, Any] | None:
    """Resolve a user-provided location string to coordinates.

    Returns dict with lat, lon, provider, and label; None if not resolved.
    """
    text = (query or "").strip()
    if not text:
        return None

    settings = get_settings()
    api_key = settings.GOOGLE_MAPS_API_KEY
    if not api_key:
        return None

    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": text, "key": api_key}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, params=params)
        if resp.status_code != 200:
            return None
        payload = resp.json()
    except Exception:
        return None

    if payload.get("status") != "OK":
        return None
    results = payload.get("results") or []
    if not results:
        return None
    best = results[0]
    location = best.get("geometry", {}).get("location", {})
    lat = location.get("lat")
    lon = location.get("lng")
    if lat is None or lon is None:
        return None

    return {
        "lat": float(lat),
        "lon": float(lon),
        "provider": "google",
        "label": best.get("formatted_address") or text,
    }
