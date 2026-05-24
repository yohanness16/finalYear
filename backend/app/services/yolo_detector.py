"""YOLOv8-based person detector for bus interior crowd estimation.

Uses the Ultralytics YOLOv8-nano model (yolov8n.pt) for full-body person
detection, augmented with:

  1. Face detection (yolov8n-face.pt) — catches people whose bodies are
     occluded but faces are visible (e.g., seated passengers behind poles).
  2. Head-blob analysis — contour-based detection for top-down camera angles
     where only the top of the head is visible (common in ceiling-mounted bus
     cameras). Uses circularity and area filtering to distinguish heads from
     luggage/shadows.

Detection tiers:
  Tier 1: YOLOv8 full-body person  (most reliable, counted directly)
  Tier 2: Face detection            (face visible, body occluded or out of frame)
  Tier 3: Head-blob detection      (only top of head visible, top-down angle)

The final count = tier1 + tier2 + tier3 (deduplicated by spatial overlap).

The model is downloaded on first use and cached locally under
  storage/models/
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

# Default confidence thresholds
_DEFAULT_CONFIDENCE = 0.35
_FACE_CONFIDENCE = 0.30
_HEAD_CONFIDENCE = 0.25

# IoU threshold for NMS
_DEFAULT_IOU = 0.45

# Model cache directory
MODEL_DIR = Path(__file__).resolve().parents[2] / "storage" / "models"
PERSON_MODEL_NAME = "yolov8n.pt"
FACE_MODEL_NAME = "yolov8n-face.pt"   # face-specific YOLOv8 model

# Head-blob detection parameters (for top-down camera angles)
_HEAD_MIN_AREA = 800      # minimum contour area in pixels (head blob)
_HEAD_MAX_AREA = 25000    # maximum contour area (exclude large shadows/luggage)
_HEAD_MIN_CIRCULARITY = 0.45  # how circle-like the contour must be (head ≈ circle)
_HEAD_ASPECT_RATIO_RANGE = (0.5, 2.0)  # w/h ratio for head-like blobs

# Thread-pool for running blocking YOLO inference off the async event loop.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="yolo-inf")

# Process-wide cached model instances (lazy-loaded)
_person_model: Any = None
_face_model: Any = None
_model_load_error: str | None = None
_face_model_load_error: str | None = None


def _load_person_model() -> Any:
    """Load and cache the YOLOv8 person detection model."""
    global _person_model, _model_load_error

    if _person_model is not None:
        return _person_model

    if _model_load_error is not None:
        return None

    try:
        from ultralytics import YOLO
    except ImportError:
        _model_load_error = "ultralytics package not installed"
        logger.warning("%s — HOG fallback will be used", _model_load_error)
        return None

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODEL_DIR / PERSON_MODEL_NAME

    try:
        if model_path.exists():
            logger.info("Loading YOLOv8 person model from cache: %s", model_path)
            _person_model = YOLO(str(model_path))
        else:
            logger.info("Downloading YOLOv8n person model (one-time, ~6 MB)...")
            _person_model = YOLO(PERSON_MODEL_NAME)
            _cache_model_weights(PERSON_MODEL_NAME, model_path)

        # Warm up
        import numpy as np
        dummy = np.zeros((64, 64, 3), dtype=np.uint8)
        _person_model.predict(dummy, verbose=False)
        logger.info("YOLOv8 person model loaded and warmed up")
        return _person_model

    except Exception as exc:
        _model_load_error = str(exc)
        logger.warning("Failed to load YOLOv8 person model: %s", exc)
        return None


def _load_face_model() -> Any:
    """Load the YOLOv8 face detection model.

    Falls back gracefully if the face model is unavailable — the system
    still works with person + head-blob detection.
    """
    global _face_model, _face_model_load_error

    if _face_model is not None:
        return _face_model

    if _face_model_load_error is not None:
        return None

    try:
        from ultralytics import YOLO
    except ImportError:
        _face_model_load_error = "ultralytics not installed"
        return None

    model_path = MODEL_DIR / FACE_MODEL_NAME

    try:
        if model_path.exists():
            logger.info("Loading YOLOv8 face model from cache: %s", model_path)
            _face_model = YOLO(str(model_path))
        else:
            # Try downloading; if it fails, log and continue without face detection
            logger.info("Downloading YOLOv8n-face model (one-time, ~6 MB)...")
            try:
                _face_model = YOLO(FACE_MODEL_NAME)
                _cache_model_weights(FACE_MODEL_NAME, model_path)
            except Exception as dl_err:
                _face_model_load_error = str(dl_err)
                logger.warning(
                    "Face model download failed (%s) — face detection disabled. "
                    "Person + head-blob detection still active.",
                    dl_err,
                )
                return None

        if _face_model is not None:
            import numpy as np
            dummy = np.zeros((64, 64, 3), dtype=np.uint8)
            _face_model.predict(dummy, verbose=False)
            logger.info("YOLOv8 face model loaded and warmed up")
        return _face_model

    except Exception as exc:
        _face_model_load_error = str(exc)
        logger.warning("Failed to load face model: %s", exc)
        return None


def _cache_model_weights(model_name: str, dest: Path) -> None:
    """Copy downloaded model weights to local cache."""
    import shutil
    try:
        downloaded = Path(model_name)
        if downloaded.exists():
            shutil.copy2(downloaded, dest)
        else:
            cache_home = Path.home() / ".cache" / "ultralytics"
            cached = cache_home / model_name
            if cached.exists():
                shutil.copy2(cached, dest)
    except Exception:
        logger.warning("Failed to cache model weights for %s", model_name, exc_info=True)


def _get_device() -> str:
    """Return the best available device string for PyTorch."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda:0"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


# ── Detection functions ───────────────────────────────────────────────────────

def _detect_full_body(frame: Any, confidence: float) -> tuple[list, list]]:
    """Run YOLOv8 person detection. Returns (boxes, scores)."""
    model = _load_person_model()
    if model is None:
        return [], []

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

    return boxes, scores


def _detect_faces(frame: Any, confidence: float) -> tuple[list, list]]:
    """Run YOLOv8 face detection. Returns (boxes, scores).

    Face detection catches people whose bodies are occluded or out of frame
    but whose faces are visible (seated behind pillars, luggage, etc.).
    """
    model = _load_face_model()
    if model is None:
        return [], []

    results = model.predict(
        frame,
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
            conf_val = float(box.conf.cpu().numpy()[0])
            if conf_val >= confidence:
                boxes.append(xyxy)
                scores.append(conf_val)

    return boxes, scores


def _detect_head_blobs(frame: Any) -> list:
    """Detect head-shaped blobs for top-down camera angles.

    In a bus with a ceiling-mounted camera, passengers often appear as
    head-shaped blobs (top of head + shoulders). Standard person detection
    may miss them when:
      - The angle is too steep (only head visible)
      - The person is partially occluded
      - The image is low-resolution or blurry

    This uses classical CV (contour analysis) to find head candidates:
      1. Convert to grayscale + CLAHE enhancement
      2. Adaptive threshold to separate heads from background
      3. Morphological ops to clean up noise
      4. Contour filtering by area, circularity, and aspect ratio

    Returns list of [x1, y1, x2, y2] bounding boxes for detected heads.
    """
    import cv2
    import numpy as np

    # Enhance contrast for better head/background separation
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)

    # CLAHE — adaptive histogram equalization (crucial for varying bus lighting)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(blurred)

    # Adaptive threshold: heads are typically darker than bus seats/floor
    # Use both polarities since hair can be light or dark
    thresh_dark = cv2.adaptiveThreshold(
        enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 21, 5,
    )
    thresh_light = cv2.adaptiveThreshold(
        enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 21, 5,
    )

    # Combine both thresholds (a head blob is either darker or lighter than surroundings)
    combined = cv2.bitwise_or(thresh_dark, thresh_light)

    # Morphological cleanup: remove small noise, merge nearby blobs
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    cleaned = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel, iterations=2)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel, iterations=1)

    # Find contours
    contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    h, w = frame.shape[:2]
    frame_area = h * w
    head_boxes = []

    for contour in contours:
        area = cv2.contourArea(contour)

        # Filter by absolute area (ignore tiny noise and huge regions)
        if area < _HEAD_MIN_AREA or area > _HEAD_MAX_AREA:
            continue

        # Filter by relative area (ignore if >5% of frame — not a head)
        if area / frame_area > 0.05:
            continue

        # Circularity check: heads are roughly circular
        perimeter = cv2.arcLength(contour, True)
        if perimeter <= 0:
            continue
        circularity = 4 * 3.14159 * area / (perimeter * perimeter)
        if circularity < _HEAD_MIN_CIRCULARITY:
            continue

        # Aspect ratio check via bounding rect
        bx, by, bw, bh = cv2.boundingRect(contour)
        if bh == 0:
            continue
        aspect = bw / bh
        if aspect < _HEAD_ASPECT_RATIO_RANGE[0] or aspect > _HEAD_ASPECT_RATIO_RANGE[1]:
            continue

        # Solidity check: contour area / convex hull area
        # Heads are fairly solid (not L-shaped or broken)
        hull = cv2.convexHull(contour)
        hull_area = cv2.contourArea(hull)
        if hull_area <= 0:
            continue
        solidity = area / hull_area
        if solidity < 0.5:
            continue

        head_boxes.append([bx, by, bx + bw, by + bh])

    return head_boxes


def _compute_iou(box_a: list, box_b: list) -> float:
    """Compute Intersection-over-Union between two [x1, y1, x2, y2] boxes."""
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)

    if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
        return 0.0

    inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    union = area_a + area_b - inter_area

    return inter_area / union if union > 0 else 0.0


def _deduplicate_detections(
    primary_boxes: list,
    secondary_boxes: list,
    iou_threshold: float = 0.3,
) -> list:
    """Remove secondary boxes that overlap significantly with primary boxes.

    Used to avoid double-counting: if a face/head-blob overlaps a full-body
    detection, it's the same person.
    """
    kept = []
    for sec_box in secondary_boxes:
        overlaps = False
        for pri_box in primary_boxes:
            if _compute_iou(sec_box, pri_box) >= iou_threshold:
                overlaps = True
                break
        if not overlaps:
            kept.append(sec_box)
    return kept


def _sync_detect_persons(image_bytes: bytes, confidence: float) -> dict[str, Any]:
    """Synchronized multi-tier person detection.

    Runs three detection tiers:
      1. YOLOv8 full-body person detection
      2. YOLOv8 face detection (catches occluded/partial bodies)
      3. Head-blob contour analysis (catches top-down head-only views)

    Returns:
        Dict with person_count, confidence, boxes, per-tier counts, and method.
    """
    import cv2
    import numpy as np

    t0 = time.monotonic()

    nparr = np.frombuffer(image_bytes, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if frame is None:
        return {
            "person_count": 0,
            "face_count": 0,
            "head_blob_count": 0,
            "confidence": 0.0,
            "boxes": [],
            "face_boxes": [],
            "head_boxes": [],
            "inference_ms": 0.0,
            "method": "decode_failed",
        }

    # ── Tier 1: Full-body person detection ──
    person_boxes, person_scores = _detect_full_body(frame, confidence)

    # ── Tier 2: Face detection ──
    face_boxes, face_scores = _detect_faces(frame, _FACE_CONFIDENCE)
    # Deduplicate: remove faces that overlap with full-body detections
    face_boxes_unique = _deduplicate_detections(person_boxes, face_boxes, iou_threshold=0.3)

    # ── Tier 3: Head-blob detection (top-down camera angles) ──
    head_boxes = _detect_head_blobs(frame)
    # Deduplicate: remove head blobs overlapping with person or face detections
    head_boxes_unique = _deduplicate_detections(person_boxes, head_boxes, iou_threshold=0.25)
    head_boxes_unique = _deduplicate_detections(face_boxes_unique, head_boxes_unique, iou_threshold=0.25)

    elapsed_ms = (time.monotonic() - t0) * 1000.0

    total_people = len(person_boxes) + len(face_boxes_unique) + len(head_boxes_unique)

    all_scores = person_scores + face_scores[:len(face_boxes_unique)]
    mean_conf = sum(all_scores) / len(all_scores) if all_scores else 0.0

    method_parts = []
    if person_boxes:
        method_parts.append(f"person:{len(person_boxes)}")
    if face_boxes_unique:
        method_parts.append(f"face:{len(face_boxes_unique)}")
    if head_boxes_unique:
        method_parts.append(f"head:{len(head_boxes_unique)}")
    method = "yolov8_multi(" + "+".join(method_parts) + ")" if method_parts else "yolov8_zero"

    # Merge all boxes for the response (primary boxes first, then face, then head)
    all_boxes = person_boxes + face_boxes_unique + head_boxes_unique

    return {
        "person_count": total_people,
        "face_count": len(face_boxes_unique),
        "head_blob_count": len(head_boxes_unique),
        "confidence": round(mean_conf, 3),
        "boxes": all_boxes,
        "face_boxes": face_boxes_unique,
        "head_boxes": head_boxes_unique,
        "inference_ms": round(elapsed_ms, 1),
        "method": method,
    }


# ── Public API ─────────────────────────────────────────────────────────────────

class YoloDetector:
    """Multi-tier person detector: full body + face + head-blob detection.

    Usage:
        detector = YoloDetector()
        result = await detector.detect(image_bytes, bus_capacity=40)

    Automatically falls back to HOG if YOLO models cannot be loaded.
    """

    def __init__(
        self,
        confidence: float = _DEFAULT_CONFIDENCE,
        use_hog_fallback: bool = True,
    ):
        self.confidence = confidence
        self.use_hog_fallback = use_hog_fallback

    async def detect(self, image_bytes: bytes, bus_capacity: int | None = None) -> dict[str, Any]:
        """Run multi-tier person detection and return structured crowd analysis.

        Args:
            image_bytes: Raw image bytes (JPEG/PNG).
            bus_capacity: Optional seat capacity for density calculation.

        Returns:
            Dict with crowd analysis including per-tier detection counts:
            {
                "human_count": int,       # total detected people
                "people_count": int,      # same as human_count
                "face_count": int,        # faces detected (body occluded)
                "head_blob_count": int,   # head-only detections
                "crowd_density": int,     # 0, 1, 2
                "is_crowded": bool,
                "method": str,            # e.g. "yolov8_multi(person:3+face:2+head:1)"
                "confidence": float,
                "foreground_ratio": float,
                "inference_ms": float,
                "boxes": list[list[int]], # all detection boxes
                "face_boxes": list,       # face-only boxes
                "head_boxes": list,       # head-blob boxes
            }
        """
        import asyncio

        loop = asyncio.get_running_loop()
        yolo_result = await loop.run_in_executor(
            _executor, _sync_detect_persons, image_bytes, self.confidence,
        )

        person_count = yolo_result["person_count"]
        method = yolo_result["method"]

        # Fall back to HOG if YOLO models are unavailable
        if method == "yolov8_unavailable" and self.use_hog_fallback:
            from app.services.cv_engine import analyze_bus_density_from_image
            hog_result = analyze_bus_density_from_image(image_bytes, bus_capacity)
            hog_result["method"] = f"hog_fallback ({hog_result.get('method', 'unknown')})"
            hog_result["inference_ms"] = 0.0
            hog_result["boxes"] = []
            hog_result["face_boxes"] = []
            hog_result["head_boxes"] = []
            return hog_result

        # Decode foreground ratio for edge case when all tiers detect 0
        raw_foreground_ratio = 0.0
        if person_count == 0 and self.use_hog_fallback:
            raw_foreground_ratio = _quick_foreground_ratio(image_bytes)

        # Determine crowd density
        from app.services.cv_engine import estimate_density_from_people_count

        crowd_density = estimate_density_from_people_count(person_count, bus_capacity)
        is_crowded = crowd_density == 2

        return {
            "human_count": person_count,
            "people_count": person_count,
            "face_count": yolo_result.get("face_count", 0),
            "head_blob_count": yolo_result.get("head_blob_count", 0),
            "crowd_density": crowd_density,
            "is_crowded": is_crowded,
            "method": method,
            "confidence": yolo_result["confidence"],
            "foreground_ratio": raw_foreground_ratio,
            "inference_ms": yolo_result["inference_ms"],
            "boxes": yolo_result["boxes"],
            "face_boxes": yolo_result.get("face_boxes", []),
            "head_boxes": yolo_result.get("head_boxes", []),
        }


def _quick_foreground_ratio(image_bytes: bytes) -> float:
    """Fast foreground ratio estimate used when all detection tiers return 0."""
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
