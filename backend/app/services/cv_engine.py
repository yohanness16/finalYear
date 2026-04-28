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

    boxes = rects.tolist() if hasattr(rects, "tolist") else [list(rect) for rect in rects]
    scores = weights.tolist() if hasattr(weights, "tolist") else list(weights)
    scores = [float(weight) for weight in scores]
    filtered = [
        box
        for box, score in zip(boxes, scores)
        if score >= 0.2
    ]
    if not filtered:
        return 0

    grouped, _ = cv2.groupRectangles(filtered + filtered, groupThreshold=1, eps=0.4)
    if len(grouped) > 0:
        return len(grouped)

    return len(filtered)


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

    return _count_people_in_frame(img)


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


def estimate_density_from_people_count(people_count: int, bus_capacity: int | None = None) -> int:
    if bus_capacity and bus_capacity > 0:
        load_ratio = people_count / bus_capacity
        if load_ratio < 0.3:
            return 0
        if load_ratio < 0.7:
            return 1
        return 2

    if people_count <= 1:
        return 0
    if people_count <= 3:
        return 1
    return 2


def estimate_density_from_image(image_bytes: bytes) -> int:
    """
    Analyze image bytes (from ESP32-CAM) and return density level.
    Prefer human detection, then fall back to the legacy thresholding heuristic.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return 0

    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return 0

    people_count = _count_people_in_frame(img)
    if people_count > 0:
        return estimate_density_from_people_count(people_count)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 120, 255, cv2.THRESH_BINARY_INV)
    h, w = thresh.shape
    total = h * w
    filled = cv2.countNonZero(thresh)
    pct = (filled / total) * 100 if total > 0 else 0
    if pct < 30:
        return 0
    if pct < 70:
        return 1
    return 2
