"""CV engine density estimation tests."""

from pathlib import Path

import pytest

from app.services.cv_engine import (
    count_people_from_image,
    estimate_density,
    estimate_density_from_image,
)


def test_estimate_density_low():
    assert estimate_density(1000) == 0
    assert estimate_density(2999) == 0


def test_estimate_density_medium():
    assert estimate_density(3000) == 1
    assert estimate_density(5000) == 1
    assert estimate_density(6999) == 1


def test_estimate_density_high():
    assert estimate_density(7000) == 2
    assert estimate_density(10000) == 2


def test_estimate_density_from_image_invalid_bytes_returns_low():
    assert estimate_density_from_image(b"not-an-image") == 0


def test_count_people_from_real_frame_detects_humans():
    pytest.importorskip("cv2")

    image_path = Path("storage/esp32_images/esp32_20260428T150244Z_578c02b0.jpg")
    image_bytes = image_path.read_bytes()

    count = count_people_from_image(image_bytes)
    assert count >= 1

    level = estimate_density_from_image(image_bytes)
    assert level in {0, 1, 2}


@pytest.mark.parametrize(
    "black_ratio, expected",
    [
        (0.10, 0),
        (0.50, 1),
        (0.90, 2),
    ],
)
def test_estimate_density_from_image_levels(black_ratio, expected):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")

    h, w = 100, 100
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    black_pixels = int(h * w * black_ratio)
    rows = black_pixels // w
    if rows > 0:
        img[:rows, :] = 0

    ok, encoded = cv2.imencode(".jpg", img)
    assert ok is True

    level = estimate_density_from_image(encoded.tobytes())
    assert level == expected
