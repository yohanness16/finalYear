import cv2
import numpy as np

from app.services.cv_engine import estimate_density_from_image


def test_estimate_density_from_image_low():
    # Since you use BINARY_INV, a WHITE image becomes 0 pixels after thresholding
    # Create a white image (all 255s)
    img = np.full((100, 100, 3), 255, dtype=np.uint8)
    _, img_encoded = cv2.imencode(".jpg", img)
    image_bytes = img_encoded.tobytes()

    # White image -> Inverted -> 0% filled -> should return 0 (Low)
    assert estimate_density_from_image(image_bytes) == 0


def test_estimate_density_from_image_high():
    # A black image (all 0s) -> Inverted -> 100% filled -> should return 2 (High)
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    _, img_encoded = cv2.imencode(".jpg", img)
    image_bytes = img_encoded.tobytes()

    assert estimate_density_from_image(image_bytes) == 2


def test_estimate_density_from_image_invalid():
    # Test with garbage data
    assert estimate_density_from_image(b"not-an-image") == 0
