"""YOLOv8-based person detector for bus interior crowd estimation.

Uses the Ultralytics YOLOv8-nano model (yolov8n.pt) which provides an
excellent speed/accuracy tradeoff for edge deployment:

  - ~80 FPS on GPU, ~5-8 FPS on CPU (acceptable for bus telemetry at 1-3s intervals)
  - 3.2M parameters, ~6 MB model weights
  - Pre-trained on COCO with strong person-class (idx 0) detection accuracy

The model is downloaded on first use and cached locally under
  storage/models/yolov8n.pt
so re-deployments without internet fall back to the cached copy.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# COCO class index for "person"
_PERSON_CLASS = 0

# Default confidence threshold for person detection
_DEFAULT_CONFIDENCE = 0.35

# IoU threshold for NMS
_DEFAULT_IOU = 0.45

# Model cache directory
MODEL_DIR = Path(__file__).resolve().parents[2] / "storage" / "models"
MODEL_NAME = "yolov8n.pt"

# Thread-pool for running blocking YOLO inference off the async event loop.
# A single worker is sufficient: inference is serialised per-telemetry item,
# and the GIL-released PyTorch ops within YOLO don't benefit from >1 thread.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="yolo-inf")

# Process-wide cached model instance (lazy-loaded)
_model: Any = None
_model_load_error: str | None = None


def _load_model() -> Any:
    """Load and cache the YOLOv8 model.

    Downloads weights on first call if not present locally.
    Subsequent calls return the cached instance.

    Returns:
        The Ultralytics YOLO model, or None if loading failed.
    """
    global _model, _model_load_error

    if _model is not None:
        return _model

    if _model_load_error is not None:
        return None

    try:
        from ultralytics import YOLO
    except ImportError:
        _model_load_error = "ultralytics package not installed"
        logger.warning("%s — HOG fallback will be used", _model_load_error)
        return None

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODEL_DIR / MODEL_NAME

    try:
        if model_path.exists():
            logger.info("Loading YOLOv8 model from local cache: %s", model_path)
            _model = YOLO(str(model_path))
        else:
            logger.info("Downloading YOLOv8n model (one-time, ~6 MB)...")
            _model = YOLO(MODEL_NAME)  # triggers auto-download
            # Persist to disk for offline re-use
            try:
                # Ultralytics downloads to cwd or its own cache dir.
                # Copy/symlink the weight file into our storage dir.
                import shutil

                downloaded = Path(MODEL_NAME)
                if downloaded.exists():
                    shutil.copy2(downloaded, model_path)
                    logger.info("Cached model weights to %s", model_path)
                else:
                    # Newer ultralytics versions download to a cache dir.
                    cache_home = Path.home() / ".cache" / "ultralytics"
                    cached_weight = cache_home / MODEL_NAME
                    if cached_weight.exists():
                        shutil.copy2(cached_weight, model_path)
                        logger.info("Cached model weights to %s", model_path)
                    else:
                        logger.warning(
                            "Could not locate downloaded weights to cache; "
                            "will re-download next time"
                        )
            except Exception:
                logger.warning("Failed to cache model weights", exc_info=True)

        # Warm up the model with a tiny dummy image — avoids first-request latency
        import numpy as np

        dummy = np.zeros((64, 64, 3), dtype=np.uint8)
        _model.predict(dummy, verbose=False)
        logger.info("YOLOv8 model loaded and warmed up successfully")
        return _model

    except Exception as exc:
        _model_load_error = str(exc)
        logger.warning("Failed to load YOLOv8 model: %s — HOG fallback active", exc)
        return None


def _sync_detect_persons(image_bytes: bytes, confidence: float) -> dict[str, Any]:
    """Synchronous YOLOv8 person detection (runs inside thread-pool).

    Args:
        image_bytes: Raw JPEG/PNG bytes.
        confidence: Minimum detection confidence (0-1).

    Returns:
        Dict with:
            person_count: int  — number of person detections
            confidence: float  — mean detection confidence (0-1)
            boxes: list[list[int]]  — bounding boxes [x1, y1, x2, y2]
            inference_ms: float  — wall-clock inference time
            method: str         — "yolov8"
    """
    import cv2
    import numpy as np

    t0 = time.monotonic()

    model = _load_model()
    if model is None:
        return {
            "person_count": 0,
            "confidence": 0.0,
            "boxes": [],
            "inference_ms": 0.0,
            "method": "yolov8_unavailable",
        }

    nparr = np.frombuffer(image_bytes, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if frame is None:
        return {
            "person_count": 0,
            "confidence": 0.0,
            "boxes": [],
            "inference_ms": 0.0,
            "method": "yolov8_decode_failed",
        }

    results = model.predict(
        frame,
        classes=[_PERSON_CLASS],
        conf=confidence,
        iou=_DEFAULT_IOU,
        verbose=False,
        device=_get_device(),
    )

    boxes = []
    scores = []
    for result in results:
        if result.boxes is None:
            continue
        for box in result.boxes:
            xyxy = box.xyxy.cpu().numpy().astype(int).tolist()[0]
            conf = float(box.conf.cpu().numpy()[0])
            boxes.append(xyxy)
            scores.append(conf)

    elapsed_ms = (time.monotonic() - t0) * 1000.0
    mean_conf = sum(scores) / len(scores) if scores else 0.0

    return {
        "person_count": len(boxes),
        "confidence": round(mean_conf, 3),
        "boxes": boxes,
        "inference_ms": round(elapsed_ms, 1),
        "method": "yolov8",
    }


def _get_device() -> str:
    """Return the best available device string for PyTorch."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda:0"
        # Apple Silicon MPS — available in PyTorch >= 1.12
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


class YoloDetector:
    """High-level YOLOv8 person detector that runs inference off the async loop.

    Usage:
        detector = YoloDetector()
        result = await detector.detect(image_bytes, bus_capacity=40)

    The detector automatically falls back to HOG if the YOLO model cannot be
    loaded (e.g., missing weights, no PyTorch).
    """

    def __init__(
        self,
        confidence: float = _DEFAULT_CONFIDENCE,
        use_hog_fallback: bool = True,
    ):
        self.confidence = confidence
        self.use_hog_fallback = use_hog_fallback

    async def detect(self, image_bytes: bytes, bus_capacity: int | None = None) -> dict[str, Any]:
        """Run person detection and return structured crowd analysis.

        Args:
            image_bytes: Raw image bytes (JPEG/PNG).
            bus_capacity: Optional seat capacity for density calculation.

        Returns:
            Dict matching the cv_engine.analyze_bus_density_from_image schema:
            {
                "human_count": int,
                "people_count": int,
                "crowd_density": int,     # 0, 1, 2
                "is_crowded": bool,
                "method": str,
                "confidence": float,
                "foreground_ratio": float,  # 0.0 for YOLO (not applicable)
                "inference_ms": float,      # YOLO-only timing
                "boxes": list[list[int]],   # raw detection boxes
            }
        """
        import asyncio

        loop = asyncio.get_running_loop()
        yolo_result = await loop.run_in_executor(
            _executor, _sync_detect_persons, image_bytes, self.confidence,
        )

        person_count = yolo_result["person_count"]
        method = yolo_result["method"]

        # Fall back to HOG if YOLO is unavailable
        raw_foreground_ratio = 0.0
        if method == "yolov8_unavailable" and self.use_hog_fallback:
            from app.services.cv_engine import analyze_bus_density_from_image

            hog_result = analyze_bus_density_from_image(image_bytes, bus_capacity)
            # Augment HOG result with metadata showing it was a fallback
            hog_result["method"] = f"hog_fallback ({hog_result.get('method', 'unknown')})"
            hog_result["inference_ms"] = 0.0
            hog_result["boxes"] = []
            return hog_result

        # Decode foreground ratio for hybrid analysis when YOLO detects 0
        # but there may still be visible crowd (e.g., extreme top-down angle)
        if person_count == 0 and self.use_hog_fallback:
            raw_foreground_ratio = _quick_foreground_ratio(image_bytes)

        # Determine crowd density
        from app.services.cv_engine import estimate_density_from_people_count

        crowd_density = estimate_density_from_people_count(person_count, bus_capacity)
        is_crowded = crowd_density == 2

        return {
            "human_count": person_count,
            "people_count": person_count,
            "crowd_density": crowd_density,
            "is_crowded": is_crowded,
            "method": method,
            "confidence": yolo_result["confidence"],
            "foreground_ratio": raw_foreground_ratio,
            "inference_ms": yolo_result["inference_ms"],
            "boxes": yolo_result["boxes"],
        }


def _quick_foreground_ratio(image_bytes: bytes) -> float:
    """Fast foreground ratio estimate used only when YOLO detects 0 people.

    This catches edge cases where YOLO misses people but there's clearly
    significant foreground activity (motion blur, dark occlusions, etc.).
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return 0.0

    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return 0.0

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(blurred)
    _, mask = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    total = mask.size
    if total <= 0:
        return 0.0
    return round(cv2.countNonZero(mask) / float(total), 3)


# ── Module-level convenience function ──────────────────────────────────────────

async def detect_persons(image_bytes: bytes, bus_capacity: int | None = None) -> dict[str, Any]:
    """One-shot async person detection using the global detector."""
    return await YoloDetector().detect(image_bytes, bus_capacity)
