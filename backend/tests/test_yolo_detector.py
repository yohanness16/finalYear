"""Tests for the YOLOv8 person detector and its integration."""

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image


def _make_test_image(
    width: int = 640, height: int = 480, color: tuple = (128, 128, 128)
) -> bytes:
    """Create a synthetic JPEG image for testing."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_black_image(width: int = 640, height: int = 480) -> bytes:
    return _make_test_image(width, height, color=(30, 30, 30))


class TestYoloDetectorFallback:
    """Test that YoloDetector gracefully falls back to HOG when YOLO is unavailable."""

    @pytest.mark.asyncio
    async def test_detect_returns_valid_schema(self):
        """detect() must return all required keys even when YOLO is unavailable."""
        from app.services.yolo_detector import YoloDetector

        detector = YoloDetector()
        result = await detector.detect(_make_test_image(), bus_capacity=40)

        assert "people_count" in result
        assert "face_count" in result
        assert "head_blob_count" in result
        assert "crowd_density" in result
        assert "is_crowded" in result
        assert "method" in result
        assert "confidence" in result
        assert "foreground_ratio" in result
        assert "inference_ms" in result
        assert "boxes" in result
        assert "face_boxes" in result
        assert "head_boxes" in result

    @pytest.mark.asyncio
    async def test_crowd_density_range(self):
        """crowd_density must always be 0, 1, or 2."""
        from app.services.yolo_detector import YoloDetector

        detector = YoloDetector()
        result = await detector.detect(_make_test_image())
        assert result["crowd_density"] in (0, 1, 2)

    @pytest.mark.asyncio
    async def test_people_count_non_negative(self):
        """people_count must be >= 0."""
        from app.services.yolo_detector import YoloDetector

        detector = YoloDetector()
        result = await detector.detect(_make_test_image())
        assert result["people_count"] >= 0

    @pytest.mark.asyncio
    async def test_confidence_range(self):
        """confidence must be between 0.0 and 1.0."""
        from app.services.yolo_detector import YoloDetector

        detector = YoloDetector()
        result = await detector.detect(_make_test_image())
        assert 0.0 <= result["confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_is_crowded_bool(self):
        """is_crowded must be a boolean."""
        from app.services.yolo_detector import YoloDetector

        detector = YoloDetector()
        result = await detector.detect(_make_test_image())
        assert isinstance(result["is_crowded"], bool)

    @pytest.mark.asyncio
    async def test_is_crowded_matches_density(self):
        """is_crowded must be True iff crowd_density == 2."""
        from app.services.yolo_detector import YoloDetector

        detector = YoloDetector()
        result = await detector.detect(_make_test_image())
        assert result["is_crowded"] == (result["crowd_density"] == 2)

    @pytest.mark.asyncio
    async def test_invalid_image_returns_defaults(self):
        """Invalid image bytes should return a valid result with 0 people."""
        from app.services.yolo_detector import YoloDetector

        detector = YoloDetector()
        result = await detector.detect(b"not-an-image")
        assert result["people_count"] == 0
        assert result["crowd_density"] == 0
        assert result["is_crowded"] is False

    @pytest.mark.asyncio
    async def test_method_is_string(self):
        """method must be a non-empty string."""
        from app.services.yolo_detector import YoloDetector

        detector = YoloDetector()
        result = await detector.detect(_make_test_image())
        assert isinstance(result["method"], str)
        assert len(result["method"]) > 0

    @pytest.mark.asyncio
    async def test_boxes_is_list(self):
        """boxes must be a list."""
        from app.services.yolo_detector import YoloDetector

        detector = YoloDetector()
        result = await detector.detect(_make_test_image())
        assert isinstance(result["boxes"], list)

    @pytest.mark.asyncio
    async def test_inference_ms_non_negative(self):
        """inference_ms must be >= 0."""
        from app.services.yolo_detector import YoloDetector

        detector = YoloDetector()
        result = await detector.detect(_make_test_image())
        assert result["inference_ms"] >= 0

    @pytest.mark.asyncio
    async def test_people_count_exists(self):
        """people_count must be present in result."""
        from app.services.yolo_detector import YoloDetector

        detector = YoloDetector()
        result = await detector.detect(_make_test_image())
        assert "people_count" in result


class TestYoloDetectorWithMockedModel:
    """Test YoloDetector with a mocked YOLO model."""

    @pytest.mark.asyncio
    async def test_detect_with_mocked_yolo_detections(self):
        """When YOLO detects people, result should reflect the count."""
        from app.services.yolo_detector import YoloDetector

        # Build a mock result that simulates 3 person detections
        mock_box = MagicMock()
        mock_box.xyxy.cpu.return_value.numpy.return_value.astype.return_value.tolist.return_value = [
            [10, 20, 50, 80]
        ]
        mock_box.conf.cpu.return_value.numpy.return_value = [0.92]

        mock_result = MagicMock()
        mock_result.boxes = [mock_box, mock_box, mock_box]

        mock_model = MagicMock()
        mock_model.predict.return_value = [mock_result]

        with patch("app.services.yolo_detector._load_person_model", return_value=mock_model), \
             patch("app.services.yolo_detector._load_face_model", return_value=None):
            detector = YoloDetector()
            import app.services.yolo_detector as yd
            yd._person_model = mock_model
            yd._model_load_error = None

            result = await detector.detect(_make_test_image(), bus_capacity=40)

            assert result["people_count"] >= 3
            assert "person:" in result["method"]
            assert result["confidence"] > 0.9
            assert len(result["boxes"]) >= 3

    @pytest.mark.asyncio
    async def test_detect_with_no_detections(self):
        """When YOLO detects 0 people, density should be Low."""
        from app.services.yolo_detector import YoloDetector

        mock_result = MagicMock()
        mock_result.boxes = None  # no detections

        mock_model = MagicMock()
        mock_model.predict.return_value = [mock_result]

        import app.services.yolo_detector as yd
        original_model = yd._person_model
        original_error = yd._model_load_error
        yd._person_model = mock_model
        yd._model_load_error = None

        try:
            with patch("app.services.yolo_detector._load_face_model", return_value=None):
                detector = YoloDetector()
                result = await detector.detect(_make_test_image(), bus_capacity=40)
                assert result["people_count"] == 0
                assert result["crowd_density"] == 0
                assert result["is_crowded"] is False
                assert result["face_count"] == 0
                assert result["head_blob_count"] == 0
        finally:
            yd._person_model = original_model
            yd._model_load_error = original_error


class TestBroadcastPayloadShape:
    """Test that broadcast functions produce the correct payload shapes."""

    @pytest.mark.asyncio
    async def test_broadcast_vehicle_position_includes_occupancy_level(self):
        """vehicle_position must include occupancy_level."""
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
            payload = mock_mgr.broadcast.call_args[0][0]
            assert payload["type"] == "vehicle_position"
            assert payload["occupancy_level"] == 2

    @pytest.mark.asyncio
    async def test_broadcast_vehicle_position_without_occupancy(self):
        """When occupancy_level is None, occupancy_level should not be present."""
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
                occupancy_level=None,
            )
            payload = mock_mgr.broadcast.call_args[0][0]
            assert "occupancy_level" not in payload

    @pytest.mark.asyncio
    async def test_broadcast_cv_result_shape(self):
        """cv_result must include all fields expected by frontend CvData type."""
        from app.services.live_broadcast import broadcast_cv_result

        with patch("app.services.live_broadcast.manager") as mock_mgr:
            mock_mgr.broadcast = AsyncMock()
            cv_result = {
                "people_count": 12,
                "face_count": 3,
                "head_blob_count": 1,
                "crowd_density": 2,
                "is_crowded": True,
                "method": "yolov8_multi(person:8+face:3+head:1)",
                "confidence": 0.92,
                "foreground_ratio": 0.0,
                "boxes": [[10, 20, 50, 80]],
                "face_boxes": [[100, 200, 150, 250]],
                "head_boxes": [[300, 400, 350, 450]],
            }
            await broadcast_cv_result(
                vehicle_id=1,
                plate_number="TEST-001",
                cv_result=cv_result,
                image_path="storage/esp32_images/test.jpg",
            )
            payload = mock_mgr.broadcast.call_args[0][0]
            assert payload["type"] == "cv_result"
            cv = payload["cv"]
            assert cv["people_count"] == 12
            assert cv["crowd_density"] == 2
            assert cv["is_crowded"] is True
            assert cv["method"] == "yolov8_multi(person:8+face:3+head:1)"
            assert cv["confidence"] == 0.92
            assert cv["foreground_ratio"] == 0.0
            assert payload["image_path"] == "storage/esp32_images/test.jpg"

    @pytest.mark.asyncio
    async def test_broadcast_cv_result_defaults(self):
        """cv_result with missing fields should use safe defaults."""
        from app.services.live_broadcast import broadcast_cv_result

        with patch("app.services.live_broadcast.manager") as mock_mgr:
            mock_mgr.broadcast = AsyncMock()
            await broadcast_cv_result(
                vehicle_id=1,
                plate_number="TEST-001",
                cv_result={},  # empty
            )
            payload = mock_mgr.broadcast.call_args[0][0]
            cv = payload["cv"]
            assert cv["people_count"] == 0
            assert cv["crowd_density"] == 0
            assert cv["is_crowded"] is False
            assert cv["method"] == "unknown"
            assert cv["confidence"] == 0.0
            assert cv["foreground_ratio"] == 0.0
            assert "image_path" not in payload


class TestCrowdEndpoint:
    """Test the crowd density REST endpoint."""

    @pytest.mark.asyncio
    async def test_get_cv_result_extended_with_image_path(self):
        """get_cv_result with extended keys should include image_path."""
        from app.services.redis_cache import get_cv_result

        mock_client = AsyncMock()
        mock_client.hgetall = AsyncMock(
            return_value={
                "occupancy_level": "2",
                "people_count": "8",
                "crowd_density": "2",
                "confidence": "0.85",
                "method": "yolov8",
                "updated_at": "1700000000",
                "image_path": "storage/esp32_images/test.jpg",
            }
        )

        with patch("app.services.redis_cache.get_redis", return_value=mock_client):
            result = await get_cv_result(
                "TEST-001",
                keys=("occupancy_level", "people_count", "crowd_density",
                       "confidence", "method", "updated_at", "image_path"),
                defaults={"occupancy_level": 0, "people_count": 0, "crowd_density": 0,
                          "confidence": 0.0, "method": "unknown", "updated_at": 0,
                          "image_path": ""},
            )
            assert result is not None
            assert result["image_path"] == "storage/esp32_images/test.jpg"
            assert result["people_count"] == 8
            assert result["method"] == "yolov8"

    @pytest.mark.asyncio
    async def test_get_cv_result_extended_missing_key_gets_default(self):
        """Missing keys in extended mode should use defaults."""
        from app.services.redis_cache import get_cv_result

        mock_client = AsyncMock()
        mock_client.hgetall = AsyncMock(
            return_value={
                "occupancy_level": "1",
                # people_count missing
            }
        )

        with patch("app.services.redis_cache.get_redis", return_value=mock_client):
            result = await get_cv_result(
                "TEST-001",
                keys=("occupancy_level", "people_count"),
                defaults={"occupancy_level": 0, "people_count": 0},
            )
            assert result["occupancy_level"] == 1
            assert result["people_count"] == 0  # default


class TestUpdateCvResult:
    """Test update_cv_result with image_path."""

    @pytest.mark.asyncio
    async def test_update_cv_result_with_image_path(self):
        """update_cv_result should include image_path in Redis hash when provided."""
        from app.services.redis_cache import update_cv_result

        mock_client = AsyncMock()
        mock_client.hset = AsyncMock()
        mock_client.expire = AsyncMock()

        with patch("app.services.redis_cache.get_redis", return_value=mock_client):
            await update_cv_result(
                plate="TEST-001",
                occupancy_level=2,
                people_count=8,
                crowd_density=2,
                confidence=0.85,
                method="yolov8",
                image_path="storage/esp32_images/test.jpg",
            )

            call_args = mock_client.hset.call_args
            mapping = call_args.kwargs.get("mapping") or call_args[1].get("mapping")
            assert "image_path" in mapping
            assert mapping["image_path"] == "storage/esp32_images/test.jpg"

    @pytest.mark.asyncio
    async def test_update_cv_result_without_image_path(self):
        """update_cv_result should not include image_path when None."""
        from app.services.redis_cache import update_cv_result

        mock_client = AsyncMock()
        mock_client.hset = AsyncMock()
        mock_client.expire = AsyncMock()

        with patch("app.services.redis_cache.get_redis", return_value=mock_client):
            await update_cv_result(
                plate="TEST-001",
                occupancy_level=0,
                people_count=0,
                crowd_density=0,
                confidence=0.25,
                method="fallback",
                image_path=None,
            )

            call_args = mock_client.hset.call_args
            mapping = call_args.kwargs.get("mapping") or call_args[1].get("mapping")
            assert "image_path" not in mapping
