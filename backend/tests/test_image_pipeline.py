"""Tests for the image processing pipeline and CV integration."""

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession


def _make_test_image(
    width: int = 640, height: int = 480, color: tuple = (128, 128, 128)
) -> bytes:
    """Create a synthetic JPEG image for testing."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_black_image(width: int = 640, height: int = 480) -> bytes:
    """Create a dark image (simulates crowded bus — low brightness)."""
    return _make_test_image(width, height, color=(30, 30, 30))


def _make_white_image(width: int = 640, height: int = 480) -> bytes:
    """Create a bright image (simulates empty bus — high brightness)."""
    return _make_test_image(width, height, color=(240, 240, 240))


@pytest.fixture
def test_image_bytes():
    """Standard test image."""
    return _make_test_image()


@pytest.fixture
def dark_image_bytes():
    """Dark image simulating crowded bus."""
    return _make_black_image()


@pytest.fixture
def bright_image_bytes():
    """Bright image simulating empty bus."""
    return _make_white_image()


@pytest.fixture
def mock_db():
    """Mock AsyncSession."""
    return MagicMock(spec=AsyncSession)


@pytest.fixture
def mock_vehicle():
    """Mock vehicle object."""
    vehicle = MagicMock()
    vehicle.id = 1
    vehicle.plate_number = "TEST-001"
    vehicle.device_id = "ESP32-TEST-001"
    vehicle.bus_type = "Anbessa"
    vehicle.capacity = 40
    vehicle.is_active = True
    vehicle.route_id = None
    vehicle.route = None
    return vehicle


class TestCVEngine:
    """Test the CV engine directly."""

    def test_analyze_returns_expected_keys(self):
        from app.services.cv_engine import analyze_bus_density_from_image

        result = analyze_bus_density_from_image(_make_test_image())
        assert "people_count" in result
        assert "crowd_density" in result
        assert "is_crowded" in result
        assert "method" in result
        assert "confidence" in result
        assert "foreground_ratio" in result

    def test_crowd_density_range(self):
        from app.services.cv_engine import analyze_bus_density_from_image

        result = analyze_bus_density_from_image(_make_test_image())
        assert result["crowd_density"] in (0, 1, 2)

    def test_confidence_range(self):
        from app.services.cv_engine import analyze_bus_density_from_image

        result = analyze_bus_density_from_image(_make_test_image())
        assert 0.0 <= result["confidence"] <= 1.0

    def test_method_is_valid(self):
        from app.services.cv_engine import analyze_bus_density_from_image

        result = analyze_bus_density_from_image(_make_test_image())
        assert result["method"] in ("hog+foreground", "hog", "foreground", "fallback")

    def test_empty_image_low_density(self):
        """A mostly white/empty image should produce low crowd density."""
        from app.services.cv_engine import analyze_bus_density_from_image

        result = analyze_bus_density_from_image(_make_white_image())
        # Bright/empty images should not be classified as crowded
        assert result["crowd_density"] in (0, 1)

    def test_decode_failure(self):
        from app.services.cv_engine import analyze_bus_density_from_image

        result = analyze_bus_density_from_image(b"not-an-image")
        assert result["crowd_density"] == 0
        assert result["method"] == "decode_failed"

    def test_estimate_density_from_people_count(self):
        from app.services.cv_engine import estimate_density_from_people_count

        assert estimate_density_from_people_count(0, 40) == 0
        assert estimate_density_from_people_count(1, 40) == 0
        assert estimate_density_from_people_count(5, 40) == 1
        assert estimate_density_from_people_count(30, 40) == 2

    def test_estimate_density_from_people_count_no_capacity(self):
        from app.services.cv_engine import estimate_density_from_people_count

        assert estimate_density_from_people_count(0) == 0
        assert estimate_density_from_people_count(1) == 0
        assert estimate_density_from_people_count(3) == 1
        assert estimate_density_from_people_count(10) == 2


class TestImagePipeline:
    """Test the image processing pipeline."""

    @pytest.mark.asyncio
    async def test_resolve_vehicle_existing(self, mock_db, mock_vehicle):
        from app.services.image_pipeline import _resolve_vehicle

        with patch("app.services.image_pipeline.crud_vehicle") as mock_crud:
            mock_crud.get_vehicle_by_device_id = AsyncMock(return_value=mock_vehicle)
            vehicle, created = await _resolve_vehicle(
                mock_db, "ESP32-TEST-001", None, None, None
            )
            assert vehicle.id == 1
            assert created is False

    @pytest.mark.asyncio
    async def test_resolve_vehicle_auto_provision(self, mock_db):
        from app.services.image_pipeline import _resolve_vehicle

        with patch("app.services.image_pipeline.crud_vehicle") as mock_crud:
            mock_crud.get_vehicle_by_device_id = AsyncMock(return_value=None)
            mock_crud.get_vehicle_by_plate = AsyncMock(return_value=None)
            new_vehicle = MagicMock()
            new_vehicle.id = 2
            new_vehicle.plate_number = "ESP-TEST-01"
            mock_crud.create_vehicle = AsyncMock(return_value=new_vehicle)

            vehicle, created = await _resolve_vehicle(
                mock_db, "NEW-DEVICE-001", None, None, None
            )
            assert created is True
            mock_crud.create_vehicle.assert_called_once()

    @pytest.mark.asyncio
    async def test_resolve_vehicle_plate_conflict(self, mock_db, mock_vehicle):
        from app.services.image_pipeline import _resolve_vehicle

        with patch("app.services.image_pipeline.crud_vehicle") as mock_crud:
            mock_crud.get_vehicle_by_device_id = AsyncMock(return_value=None)
            mock_crud.get_vehicle_by_plate = AsyncMock(return_value=mock_vehicle)

            with pytest.raises(ValueError, match="plate_number already registered"):
                await _resolve_vehicle(mock_db, "NEW-DEVICE", "TEST-001", None, None)

    @pytest.mark.asyncio
    async def test_validate_gps_no_route(self):
        from app.services.image_pipeline import _validate_gps

        lat, lon, rejection = await _validate_gps(9.03, 38.74, "TEST-001", [])
        assert rejection is None
        assert lat == 9.03
        assert lon == 38.74

    @pytest.mark.asyncio
    async def test_validate_gps_off_route(self):
        from app.services.image_pipeline import _validate_gps

        # Create mock route stops far from the test coordinate
        mock_stop = MagicMock()
        mock_stop.latitude = 10.0
        mock_stop.longitude = 40.0

        with patch("app.services.image_pipeline.is_on_route", return_value=False):
            lat, lon, rejection = await _validate_gps(
                9.03, 38.74, "TEST-001", [mock_stop]
            )
            assert rejection == "off_route"

    @pytest.mark.asyncio
    async def test_store_image(self, tmp_path):
        from app.services.image_pipeline import _store_image

        image_bytes = _make_test_image()
        with patch("app.services.image_pipeline.Path") as mock_path_cls:
            mock_root = MagicMock()
            mock_root.__truediv__ = MagicMock(return_value=tmp_path)
            mock_path_cls.resolve = MagicMock(return_value=MagicMock())
            mock_path_cls.resolve.return_value.parents = [None, None, tmp_path]

            # Use actual file system via tmp_path
            import app.services.image_pipeline as pipeline_module

            original_parents = pipeline_module.Path.__truediv__

            path, saved = await _store_image(image_bytes, "test.jpg")
            assert saved is True
            assert path != ""


class TestLiveBroadcast:
    """Test the enhanced live broadcast functions."""

    @pytest.mark.asyncio
    async def test_broadcast_vehicle_position_with_occupancy(self):
        from app.services.live_broadcast import broadcast_vehicle_position

        with patch("app.services.live_broadcast.manager") as mock_mgr:
            mock_mgr.broadcast = AsyncMock()
            await broadcast_vehicle_position(
                vehicle_id=1,
                plate_number="TEST-001",
                lat=9.03,
                lon=38.74,
                speed=30.0,
                route_id=5,
                occupancy_level=2,
            )
            mock_mgr.broadcast.assert_called_once()
            payload = mock_mgr.broadcast.call_args[0][0]
            assert payload["type"] == "vehicle_position"
            assert payload["occupancy_level"] == 2
            assert payload["vehicle_id"] == 1

    @pytest.mark.asyncio
    async def test_broadcast_cv_result(self):
        from app.services.live_broadcast import broadcast_cv_result

        with patch("app.services.live_broadcast.manager") as mock_mgr:
            mock_mgr.broadcast = AsyncMock()
            cv_result = {
                "people_count": 8,
                "crowd_density": 2,
                "is_crowded": True,
                "method": "hog+foreground",
                "confidence": 0.85,
                "foreground_ratio": 0.45,
            }
            await broadcast_cv_result(
                vehicle_id=1,
                plate_number="TEST-001",
                cv_result=cv_result,
                image_path="storage/esp32_images/test.jpg",
            )
            mock_mgr.broadcast.assert_called_once()
            payload = mock_mgr.broadcast.call_args[0][0]
            assert payload["type"] == "cv_result"
            assert payload["cv"]["people_count"] == 8
            assert payload["cv"]["crowd_density"] == 2
            assert payload["cv"]["is_crowded"] is True
            assert payload["cv"]["method"] == "hog+foreground"
            assert payload["image_path"] == "storage/esp32_images/test.jpg"

    @pytest.mark.asyncio
    async def test_broadcast_cv_result_no_image(self):
        from app.services.live_broadcast import broadcast_cv_result

        with patch("app.services.live_broadcast.manager") as mock_mgr:
            mock_mgr.broadcast = AsyncMock()
            cv_result = {
                "people_count": 0,
                "crowd_density": 0,
                "is_crowded": False,
                "method": "fallback",
                "confidence": 0.25,
                "foreground_ratio": 0.02,
            }
            await broadcast_cv_result(
                vehicle_id=1,
                plate_number="TEST-001",
                cv_result=cv_result,
                image_path=None,
            )
            payload = mock_mgr.broadcast.call_args[0][0]
            assert "image_path" not in payload

    @pytest.mark.asyncio
    async def test_broadcast_error_handling(self):
        """Broadcast functions should never raise, even when WS is down."""
        from app.services.live_broadcast import (
            broadcast_cv_result,
            broadcast_vehicle_position,
        )

        with patch("app.services.live_broadcast.manager") as mock_mgr, \
             patch("app.services.live_broadcast.logger"):
            mock_mgr.broadcast = AsyncMock(side_effect=Exception("WS down"))
            # Should not raise — exceptions are caught and logged
            await broadcast_vehicle_position(
                vehicle_id=1,
                plate_number="TEST",
                lat=0,
                lon=0,
                speed=0,
                route_id=None,
            )
            await broadcast_cv_result(
                vehicle_id=1,
                plate_number="TEST",
                cv_result={
                    "people_count": 0,
                    "crowd_density": 0,
                    "is_crowded": False,
                    "method": "fallback",
                    "confidence": 0,
                    "foreground_ratio": 0,
                },
            )


class TestRedisCVStorage:
    """Test Redis CV result storage helpers."""

    @pytest.mark.asyncio
    async def test_update_and_get_cv_result(self):
        from app.services.redis_cache import get_cv_result, update_cv_result

        mock_client = AsyncMock()
        mock_client.hset = AsyncMock()
        mock_client.expire = AsyncMock()
        mock_client.hgetall = AsyncMock(
            return_value={
                "occupancy_level": "2",
                "people_count": "8",
                "crowd_density": "2",
                "confidence": "0.85",
                "method": "hog+foreground",
                "updated_at": "1700000000",
            }
        )

        with patch("app.services.redis_cache.get_redis", return_value=mock_client):
            await update_cv_result(
                plate="TEST-001",
                occupancy_level=2,
                people_count=8,
                crowd_density=2,
                confidence=0.85,
                method="hog+foreground",
            )

            result = await get_cv_result("TEST-001")
            assert result is not None
            assert result["occupancy_level"] == 2
            assert result["people_count"] == 8
            assert result["crowd_density"] == 2
            assert result["confidence"] == 0.85
            assert result["method"] == "hog+foreground"

    @pytest.mark.asyncio
    async def test_get_cv_result_not_found(self):
        from app.services.redis_cache import get_cv_result

        mock_client = AsyncMock()
        mock_client.hgetall = AsyncMock(return_value={})

        with patch("app.services.redis_cache.get_redis", return_value=mock_client):
            result = await get_cv_result("NONEXISTENT")
            assert result is None
