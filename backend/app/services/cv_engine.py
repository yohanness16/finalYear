"""OpenCV-based passenger density estimation."""

from typing import Optional


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


def estimate_density_from_image(image_bytes: bytes) -> int:
    """
    Analyze image bytes (from ESP32-CAM) and return density level.
    Uses simple thresholding for MVP.
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
