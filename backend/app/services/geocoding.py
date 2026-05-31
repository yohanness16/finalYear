"""Geocoding helpers for user-entered locations."""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings


async def geocode_text(query: str) -> dict[str, Any] | None:
    """Resolve a user-provided location string to coordinates.

    Tries Google Maps API first (if GOOGLE_MAPS_API_KEY is configured),
    then falls back to OpenStreetMap Nominatim (free, no API key needed).

    Returns dict with lat, lon, provider, and label; None if not resolved.
    """
    text = (query or "").strip()
    if not text:
        return None

    settings = get_settings()

    # ── Try Google Maps first ──
    api_key = settings.GOOGLE_MAPS_API_KEY
    if api_key and api_key != "xxx":
        result = await _geocode_google(text, api_key)
        if result:
            return result

    # ── Fallback: OpenStreetMap Nominatim (free, no API key) ──
    return await _geocode_nominatim(text)


async def _geocode_google(query: str, api_key: str) -> dict[str, Any] | None:
    """Geocode using Google Maps API."""
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": query, "key": api_key}
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
        "label": best.get("formatted_address") or query,
    }


async def _geocode_nominatim(query: str) -> dict[str, Any] | None:
    """Geocode using OpenStreetMap Nominatim (free, no API key required).

    Has a usage policy of max 1 request/second — suitable for low-volume
    journey search use. For production at scale, add a cache layer or
    use a self-hosted Nominatim instance.
    """
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": query, "format": "json", "limit": 1},
                headers={"User-Agent": "BusTrack/1.0"},
            )
        if resp.status_code != 200:
            return None
        results = resp.json()
    except Exception:
        return None

    if not results:
        return None
    best = results[0]
    lat = best.get("lat")
    lon = best.get("lon")
    if lat is None or lon is None:
        return None

    return {
        "lat": float(lat),
        "lon": float(lon),
        "provider": "nominatim",
        "label": best.get("display_name") or query,
    }
