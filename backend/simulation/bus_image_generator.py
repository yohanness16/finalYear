"""
Generate synthetic bus interior images with varying occupancy levels.
Used for ESP32 camera simulation with CV occupancy analysis.

Occupancy levels:
  0 = Empty/Low (< 35% capacity)
  1 = Medium (35-72% capacity)
  2 = Crowded (> 72% capacity)

The images are designed to produce realistic CV detection results:
- HOG people detector responds to human-shaped blobs (head/shoulder profiles)
- Foreground segmentation detects occupied floor area
- Brightness analysis correlates with crowd density (more people = darker)
"""

import io
import random
from typing import Tuple

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:
    raise ImportError("Please install Pillow: pip install pillow")


def _add_noise(img: Image.Image, intensity: int = 15) -> Image.Image:
    """Add subtle sensor noise to simulate real camera output."""
    import random as _rnd
    pixels = img.load()
    w, h = img.size
    for x in range(w):
        for y in range(h):
            r, g, b = pixels[x, y]
            noise = _rnd.randint(-intensity, intensity)
            pixels[x, y] = (
                max(0, min(255, r + noise)),
                max(0, min(255, g + noise)),
                max(0, min(255, b + noise)),
            )
    return img


def _draw_person(draw: ImageDraw.Draw, cx: int, cy: int, size: int = 28):
    """Draw a human-shaped figure (head + torso) for HOG detection."""
    # Head (ellipse)
    head_r = max(6, size // 4)
    draw.ellipse(
        [cx - head_r, cy - size // 2 - head_r, cx + head_r, cy - size // 2 + head_r],
        fill=(180, 140, 120),
        outline=(120, 90, 70),
    )
    # Torso (rounded rectangle)
    body_w = max(10, size // 2)
    body_h = max(14, size * 3 // 4)
    draw.rounded_rectangle(
        [cx - body_w // 2, cy - size // 2 + head_r, cx + body_w // 2, cy - size // 2 + head_r + body_h],
        radius=4,
        fill=(random.randint(80, 160), random.randint(60, 140), random.randint(50, 130)),
        outline=(60, 50, 40),
    )


def _draw_seat(draw: ImageDraw.Draw, x: int, y: int, occupied: bool):
    """Draw a bus seat, optionally with a person sitting."""
    seat_w, seat_h = 44, 36
    if occupied:
        # Person sitting — draw person shape
        _draw_person(draw, x + seat_w // 2, y + seat_h // 2, size=30)
        # Seat underneath (darker)
        draw.rounded_rectangle(
            [x, y, x + seat_w, y + seat_h],
            radius=5,
            fill=(90, 70, 60),
            outline=(60, 50, 40),
        )
    else:
        # Empty seat
        draw.rounded_rectangle(
            [x, y, x + seat_w, y + seat_h],
            radius=5,
            fill=(200, 200, 200),
            outline=(150, 150, 150),
        )


def _generate_bus_interior_empty() -> Image.Image:
    """Generate image of empty/low-occupancy bus interior."""
    img = Image.new("RGB", (640, 480), color=(230, 228, 225))
    draw = ImageDraw.Draw(img)

    # Bus walls
    draw.rectangle([30, 60, 610, 440], outline=(120, 118, 115), width=2)

    # Floor
    draw.rectangle([30, 350, 610, 440], fill=(140, 138, 135))

    # Seats — mostly empty
    seat_positions = [(60, 120), (160, 120), (340, 120), (440, 120),
                      (60, 240), (160, 240), (340, 240), (440, 240)]
    for sx, sy in seat_positions:
        _draw_seat(draw, sx, sy, occupied=random.random() < 0.15)

    # A few standing passengers
    for px, py in [(280, 310), (520, 320)]:
        _draw_person(draw, px, py, size=26)

    # Handrail
    draw.line([(80, 80), (560, 80)], fill=(100, 100, 100), width=4)
    for x in range(120, 560, 80):
        draw.line([(x, 78), (x, 95)], fill=(80, 80, 80), width=2)

    # Window hints
    for wx in [40, 560]:
        draw.rectangle([wx, 100, wx + 30, 200], fill=(180, 200, 220), outline=(100, 100, 100))

    img = _add_noise(img, intensity=10)
    return img


def _generate_bus_interior_medium() -> Image.Image:
    """Generate image of medium-occupancy bus interior."""
    img = Image.new("RGB", (640, 480), color=(220, 218, 215))
    draw = ImageDraw.Draw(img)

    # Bus walls
    draw.rectangle([30, 60, 610, 440], outline=(110, 108, 105), width=2)

    # Floor (partially visible)
    draw.rectangle([30, 350, 610, 440], fill=(130, 128, 125))

    # Seats — about half occupied
    seat_positions = [(60, 120), (160, 120), (340, 120), (440, 120),
                      (60, 240), (160, 240), (340, 240), (440, 240)]
    for sx, sy in seat_positions:
        _draw_seat(draw, sx, sy, occupied=random.random() < 0.55)

    # Standing passengers
    standing_positions = [(250, 300), (320, 310), (400, 305), (480, 315),
                          (200, 330), (530, 325)]
    for px, py in random.sample(standing_positions, k=random.randint(3, 5)):
        _draw_person(draw, px, py, size=random.randint(24, 30))

    # Handrail
    draw.line([(80, 80), (560, 80)], fill=(90, 90, 90), width=4)
    for x in range(120, 560, 80):
        draw.line([(x, 78), (x, 95)], fill=(70, 70, 70), width=2)

    # Window hints
    for wx in [40, 560]:
        draw.rectangle([wx, 100, wx + 30, 200], fill=(170, 190, 210), outline=(100, 100, 100))

    img = _add_noise(img, intensity=12)
    return img


def _generate_bus_interior_crowded() -> Image.Image:
    """Generate image of crowded bus interior."""
    img = Image.new("RGB", (640, 480), color=(200, 198, 195))
    draw = ImageDraw.Draw(img)

    # Bus walls (partially obscured)
    draw.rectangle([30, 60, 610, 440], outline=(100, 98, 95), width=2)

    # Floor (mostly obscured by people)
    draw.rectangle([30, 380, 610, 440], fill=(120, 118, 115))

    # Seats — almost all occupied
    seat_positions = [(60, 120), (160, 120), (340, 120), (440, 120),
                      (60, 240), (160, 240), (340, 240), (440, 240)]
    for sx, sy in seat_positions:
        _draw_seat(draw, sx, sy, occupied=random.random() < 0.85)

    # Many standing passengers (crowded)
    standing_positions = [
        (120, 290), (200, 295), (280, 300), (360, 295), (440, 300), (520, 290),
        (100, 320), (180, 325), (260, 330), (340, 325), (420, 330), (500, 320), (560, 325),
        (150, 350), (300, 355), (450, 350),
    ]
    for px, py in random.sample(standing_positions, k=random.randint(10, 15)):
        _draw_person(draw, px, py, size=random.randint(22, 32))

    # Handrail (partially visible through crowd)
    draw.line([(80, 80), (560, 80)], fill=(80, 80, 80), width=4)

    # Windows (barely visible)
    for wx in [40, 560]:
        draw.rectangle([wx, 100, wx + 30, 200], fill=(150, 170, 190), outline=(100, 100, 100))

    img = _add_noise(img, intensity=15)
    return img


def generate_bus_image(occupancy_level: int) -> bytes:
    """
    Generate synthetic bus interior image based on occupancy level.

    Args:
        occupancy_level: 0=Empty, 1=Medium, 2=Crowded

    Returns:
        JPG image bytes
    """
    if occupancy_level == 0:
        img = _generate_bus_interior_empty()
    elif occupancy_level == 1:
        img = _generate_bus_interior_medium()
    else:  # 2
        img = _generate_bus_interior_crowded()

    # Convert to JPG bytes
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    buffer.seek(0)
    return buffer.getvalue()


def generate_bus_image_with_noise(occupancy_level: int, noise_factor: float = 0.05) -> bytes:
    """
    Generate bus image with added noise to simulate real camera jitter.

    Args:
        occupancy_level: 0=Empty, 1=Medium, 2=Crowded
        noise_factor: 0.0-1.0, how much random noise to add

    Returns:
        JPG image bytes
    """
    img_bytes = generate_bus_image(occupancy_level)
    img = Image.open(io.BytesIO(img_bytes))
    img = _add_noise(img, intensity=int(noise_factor * 40))
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=80)
    buffer.seek(0)
    return buffer.getvalue()
