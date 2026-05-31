"""Tests for geocoding service."""

from unittest.mock import patch

import pytest

from app.services.geocoding import geocode_text


@pytest.mark.asyncio
async def test_geocode_text_without_api_key_or_network():
    """When no Google API key and Nominatim is unreachable, should return None."""
    with patch("app.services.geocoding.get_settings") as mock_settings:
        mock_settings.return_value.GOOGLE_MAPS_API_KEY = None
        with patch("app.services.geocoding._geocode_nominatim", return_value=None):
            result = await geocode_text("Addis Ababa")
            assert result is None


@pytest.mark.asyncio
async def test_geocode_text_returns_none_for_empty_query():
    """Empty query should return None immediately without any API call."""
    result = await geocode_text("")
    assert result is None


@pytest.mark.asyncio
async def test_geocode_text_returns_none_for_whitespace():
    """Whitespace-only query should return None."""
    result = await geocode_text("   ")
    assert result is None
