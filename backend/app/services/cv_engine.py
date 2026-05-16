"""OpenCV-based passenger density estimation."""

from functools import lru_cache


def _get_people_detector():
    try:
        import cv2
    except ImportError:
        return None

    detector = cv2.HOGDescriptor()
    detector.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    return detector


@lru_cache(maxsize=1)
def _cached_people_detector():
    return _get_people_detector()


def _resize_for_people_detection(frame):
    height, width = frame.shape[:2]
    if width <= 0 or height <= 0:
        return frame

    scale = min(2.5, max(1.0, 800 / float(width)))
    if scale == 1.0:
        return frame

    import cv2

    return cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


def _count_people_in_frame(frame) -> int:
    detector = _cached_people_detector()
    if detector is None:
        return 0

    import cv2

    resized = _resize_for_people_detection(frame)
    rects, weights = detector.detectMultiScale(
        resized,
        winStride=(4, 4),
        padding=(8, 8),
        scale=1.02,
        hitThreshold=-0.25,
    )

    if len(rects) == 0:
        return 0

    boxes = (
        rects.tolist() if hasattr(rects, "tolist") else [list(rect) for rect in rects]
    )
    scores = weights.tolist() if hasattr(weights, "tolist") else list(weights)
    scores = [float(weight) for weight in scores]
    filtered = [box for box, score in zip(boxes, scores) if score >= 0.2]
    if not filtered:
        return 0

    grouped, _ = cv2.groupRectangles(filtered + filtered, groupThreshold=1, eps=0.4)
    if len(grouped) > 0:
        return len(grouped)

    return len(filtered)


def _estimate_foreground_ratio(frame) -> float:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return 0.0

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(blurred)

    _, otsu_mask = cv2.threshold(
        enhanced,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )
    adaptive_mask = cv2.adaptiveThreshold(
        enhanced,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        7,
    )

    mask = cv2.bitwise_and(otsu_mask, adaptive_mask)
    kernel = np.ones((3, 3), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    total_pixels = mask.size
    if total_pixels <= 0:
        return 0.0
    return cv2.countNonZero(mask) / float(total_pixels)


def _estimate_people_from_foreground(frame) -> int:
    try:
        import cv2
    except ImportError:
        return 0

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(blurred)

    _, otsu_mask = cv2.threshold(
        enhanced,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )
    adaptive_mask = cv2.adaptiveThreshold(
        enhanced,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        7,
    )

    mask = cv2.bitwise_and(otsu_mask, adaptive_mask)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    total_pixels = mask.size
    if total_pixels <= 0:
        return 0

    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    min_area = max(18, int(total_pixels * 0.00035))
    max_area = int(total_pixels * 0.12)

    candidates = 0
    for label in range(1, num_labels):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < min_area or area > max_area:
            continue

        width = int(stats[label, cv2.CC_STAT_WIDTH])
        height = int(stats[label, cv2.CC_STAT_HEIGHT])
        if width <= 0 or height <= 0:
            continue

        aspect_ratio = max(width, height) / float(min(width, height))
        if aspect_ratio > 6.0:
            continue

        candidates += 1

    foreground_ratio = cv2.countNonZero(mask) / float(total_pixels)
    coverage_count = 0
    if foreground_ratio >= 0.03:
        coverage_count = max(1, int(round(foreground_ratio * 16)))

    return max(candidates, coverage_count)


def _estimate_density_from_foreground_ratio(foreground_ratio: float) -> int:
    if foreground_ratio < 0.12:
        return 0
    if foreground_ratio < 0.32:
        return 1
    return 2


def _estimate_density_from_brightness(frame) -> int:
    try:
        import cv2
    except ImportError:
        return 0

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    darkness_ratio = 1.0 - (float(gray.mean()) / 255.0)
    if darkness_ratio < 0.30:
        return 0
    if darkness_ratio < 0.70:
        return 1
    return 2


def count_people_from_image(image_bytes: bytes) -> int:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return 0

    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return 0

    hog_count = _count_people_in_frame(img)
    foreground_count = _estimate_people_from_foreground(img)
    return max(hog_count, foreground_count)


def estimate_density(pixel_count: int, total_pixels: int = 10000) -> int:
    """
    Map pixel count to occupancy level.
    0 = Low, 1 = Medium, 2 = High.
    If total_pixels not provided, use thresholds: <3000 Low, <7000 Med, else High.
    """
    if total_pixels and total_pixels > 0:
        pct = (pixel_count / total_pixels) * 100
        if pct < 30:
            return 0
        if pct < 70:
            return 1
        return 2
    if pixel_count < 3000:
        return 0
    if pixel_count < 7000:
        return 1
    return 2


def estimate_density_from_people_count(
    people_count: int, bus_capacity: int | None = None
) -> int:
    if bus_capacity and bus_capacity > 0:
        load_ratio = people_count / bus_capacity
        if load_ratio < 0.3:
            return 0
        if load_ratio < 0.7:
            return 1
        return 2

    if people_count <= 1:
        return 0
    if people_count <= 6:
        return 1
    return 2


def analyze_bus_density_from_image(
    image_bytes: bytes, bus_capacity: int | None = None
) -> dict[str, object]:
    """Analyze an ESP32-CAM frame and return a structured crowd estimate.

    The live path prefers human detections, but also uses a foreground-based
    bird-view heuristic so the system still classifies empty/normal/crowded when
    the HOG detector misses top-down passengers.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return {
            "human_count": 0,
            "people_count": 0,
            "crowd_density": 0,
            "is_crowded": False,
            "method": "unavailable",
            "confidence": 0.0,
            "foreground_ratio": 0.0,
        }

    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return {
            "human_count": 0,
            "people_count": 0,
            "crowd_density": 0,
            "is_crowded": False,
            "method": "decode_failed",
            "confidence": 0.0,
            "foreground_ratio": 0.0,
        }

    hog_count = _count_people_in_frame(img)
    foreground_count = _estimate_people_from_foreground(img)
    people_count = max(hog_count, foreground_count)
    foreground_ratio = _estimate_foreground_ratio(img)

    density_from_people = estimate_density_from_people_count(people_count, bus_capacity)
    density_from_ratio = _estimate_density_from_foreground_ratio(foreground_ratio)
    density_from_brightness = _estimate_density_from_brightness(img)
    crowd_density = max(
        density_from_people, density_from_ratio, density_from_brightness
    )

    confidence = 0.25
    if hog_count > 0:
        confidence += 0.45
    if foreground_count > 0:
        confidence += 0.20
    if foreground_ratio >= 0.12:
        confidence += 0.10
    confidence = min(confidence, 0.99)

    if hog_count > 0 and foreground_count > 0:
        method = "hog+foreground"
    elif hog_count > 0:
        method = "hog"
    elif foreground_count > 0:
        method = "foreground"
    else:
        method = "fallback"

    return {
        "human_count": people_count,
        "people_count": people_count,
        "crowd_density": crowd_density,
        "is_crowded": crowd_density == 2,
        "method": method,
        "confidence": round(confidence, 3),
        "foreground_ratio": round(foreground_ratio, 3),
    }


def estimate_density_from_image(image_bytes: bytes) -> int:
    """
    Analyze image bytes (from ESP32-CAM) and return density level.
    Prefer human detection, then fall back to the legacy thresholding heuristic.
    """
    return int(analyze_bus_density_from_image(image_bytes).get("crowd_density", 0))
