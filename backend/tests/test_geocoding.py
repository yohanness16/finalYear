from unittest.mock import patch

import pytest

from app.services.geocoding import geocode_text


@pytest.mark.asyncio
async def test_geocode_text_without_api_key():
    with patch("app.services.geocoding.get_settings") as mock_settings:
        mock_settings.return_value.GOOGLE_MAPS_API_KEY = None
        result = await geocode_text("Addis Ababa")
        assert result is None
