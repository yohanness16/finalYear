"""
BusTrack Simulation Configuration
Addis Ababa Public Transport Simulation
"""

import os

# ── API Configuration ──────────────────────────────────────────────────────────
BASE_URL = os.getenv("BUSTRACK_API_URL", "http://localhost:8000/api/v1")

# ── Simulation Settings ────────────────────────────────────────────────────────
SIMULATION_SPEED = 1.0          # 1.0 = real time, 2.0 = 2x faster
GPS_PING_INTERVAL = 5           # seconds between GPS pings
TRIP_DURATION_MINUTES = 30      # approx time per bus trip
CONCURRENT_BUSES = 5            # how many buses drive simultaneously

# ── ESP32 Image Simulation ─────────────────────────────────────
ESP32_IMAGE_WIDTH = 640         # synthetic image width (optimal for HOG)
ESP32_IMAGE_HEIGHT = 480        # synthetic image height
ESP32_IMAGE_QUALITY = 85        # JPEG quality (0-100)
ESP32_IMAGE_NOISE = 12          # sensor noise intensity (0-40)

# ── Addis Ababa GPS Bounds ─────────────────────────────────────────────────────
AA_CENTER = (9.0222, 38.7468)
AA_BOUNDS = {
    "min_lat": 8.93,
    "max_lat": 9.12,
    "min_lon": 38.65,
    "max_lon": 38.85,
}

# ── Addis Ababa Bus Routes (Real Route Numbers) ────────────────────────────────
ROUTES = [
    {
        "route_number": "12",
        "name": "Megenagna - Mexico",
        "origin": "Megenagna",
        "destination": "Mexico",
        "stops": [
            {"name": "Megenagna",     "lat": 9.0267,  "lon": 38.7613, "dwell": 60, "is_terminal": True,  "peak_mult": 2.5},
            {"name": "Bole Michael",  "lat": 9.0198,  "lon": 38.7556, "dwell": 30, "is_terminal": False, "peak_mult": 1.5},
            {"name": "Bole Road",     "lat": 9.0144,  "lon": 38.7504, "dwell": 30, "is_terminal": False, "peak_mult": 1.5},
            {"name": "Awareness",     "lat": 9.0065,  "lon": 38.7461, "dwell": 40, "is_terminal": False, "peak_mult": 1.8},
            {"name": "CMC",           "lat": 9.0011,  "lon": 38.7423, "dwell": 35, "is_terminal": False, "peak_mult": 1.6},
            {"name": "Mexico",        "lat": 8.9956,  "lon": 38.7385, "dwell": 60, "is_terminal": True,  "peak_mult": 2.0},
        ]
    },
    {
        "route_number": "45",
        "name": "Stadium - Ayat",
        "origin": "Stadium",
        "destination": "Ayat",
        "stops": [
            {"name": "Stadium",       "lat": 9.0086,  "lon": 38.7610, "dwell": 60, "is_terminal": True,  "peak_mult": 2.0},
            {"name": "Gofa Mebrat",   "lat": 9.0013,  "lon": 38.7678, "dwell": 30, "is_terminal": False, "peak_mult": 1.4},
            {"name": "Kaliti",        "lat": 8.9942,  "lon": 38.7745, "dwell": 35, "is_terminal": False, "peak_mult": 1.5},
            {"name": "Akaki",         "lat": 8.9875,  "lon": 38.7810, "dwell": 40, "is_terminal": False, "peak_mult": 1.6},
            {"name": "Ayat",          "lat": 8.9803,  "lon": 38.7880, "dwell": 60, "is_terminal": True,  "peak_mult": 1.8},
        ]
    },
    {
        "route_number": "21",
        "name": "Merkato - Bole Airport",
        "origin": "Merkato",
        "destination": "Bole Airport",
        "stops": [
            {"name": "Merkato",       "lat": 9.0193,  "lon": 38.7356, "dwell": 70, "is_terminal": True,  "peak_mult": 2.5},
            {"name": "Piassa",        "lat": 9.0245,  "lon": 38.7408, "dwell": 45, "is_terminal": False, "peak_mult": 2.0},
            {"name": "Arada",         "lat": 9.0297,  "lon": 38.7461, "dwell": 40, "is_terminal": False, "peak_mult": 1.8},
            {"name": "Wavel",         "lat": 9.0210,  "lon": 38.7520, "dwell": 30, "is_terminal": False, "peak_mult": 1.4},
            {"name": "Bole Airport",  "lat": 9.0350,  "lon": 38.7990, "dwell": 60, "is_terminal": True,  "peak_mult": 1.5},
        ]
    },
    {
        "route_number": "67",
        "name": "Saris - Piassa",
        "origin": "Saris",
        "destination": "Piassa",
        "stops": [
            {"name": "Saris",         "lat": 8.9920,  "lon": 38.7200, "dwell": 50, "is_terminal": True,  "peak_mult": 1.8},
            {"name": "Gotera",        "lat": 9.0001,  "lon": 38.7262, "dwell": 35, "is_terminal": False, "peak_mult": 1.5},
            {"name": "Tor Hailoch",   "lat": 9.0078,  "lon": 38.7320, "dwell": 30, "is_terminal": False, "peak_mult": 1.4},
            {"name": "Arat Kilo",     "lat": 9.0156,  "lon": 38.7380, "dwell": 40, "is_terminal": False, "peak_mult": 1.6},
            {"name": "Piassa",        "lat": 9.0245,  "lon": 38.7408, "dwell": 60, "is_terminal": True,  "peak_mult": 2.0},
        ]
    },
    {
        "route_number": "89",
        "name": "Kazanchis - Lideta",
        "origin": "Kazanchis",
        "destination": "Lideta",
        "stops": [
            {"name": "Kazanchis",     "lat": 9.0167,  "lon": 38.7631, "dwell": 50, "is_terminal": True,  "peak_mult": 2.0},
            {"name": "Bole Bridge",   "lat": 9.0133,  "lon": 38.7580, "dwell": 30, "is_terminal": False, "peak_mult": 1.4},
            {"name": "Bambis",        "lat": 9.0101,  "lon": 38.7529, "dwell": 30, "is_terminal": False, "peak_mult": 1.5},
            {"name": "Stadium",       "lat": 9.0086,  "lon": 38.7610, "dwell": 35, "is_terminal": False, "peak_mult": 1.6},
            {"name": "Lideta",        "lat": 9.0048,  "lon": 38.7490, "dwell": 50, "is_terminal": True,  "peak_mult": 1.8},
        ]
    },
    {
        "route_number": "33",
        "name": "Megenagna - Saris",
        "origin": "Megenagna",
        "destination": "Saris",
        "stops": [
            {"name": "Megenagna",     "lat": 9.0267,  "lon": 38.7613, "dwell": 60, "is_terminal": True,  "peak_mult": 2.5},
            {"name": "Urael",         "lat": 9.0190,  "lon": 38.7567, "dwell": 30, "is_terminal": False, "peak_mult": 1.5},
            {"name": "Kality",        "lat": 9.0112,  "lon": 38.7523, "dwell": 30, "is_terminal": False, "peak_mult": 1.4},
            {"name": "Gofa",          "lat": 9.0035,  "lon": 38.7345, "dwell": 35, "is_terminal": False, "peak_mult": 1.5},
            {"name": "Saris",         "lat": 8.9920,  "lon": 38.7200, "dwell": 60, "is_terminal": True,  "peak_mult": 1.8},
        ]
    },
]

# ── Vehicles (Buses) ───────────────────────────────────────────────────────────
VEHICLES = [
    {"plate_number": "AA-3-B12345", "device_id": "IMEI001234567890", "bus_type": "Anbessa", "capacity": 80},
    {"plate_number": "AA-3-C23456", "device_id": "IMEI002345678901", "bus_type": "Anbessa", "capacity": 80},
    {"plate_number": "AA-3-D34567", "device_id": "IMEI003456789012", "bus_type": "Sheger",  "capacity": 60},
    {"plate_number": "AA-3-E45678", "device_id": "IMEI004567890123", "bus_type": "Sheger",  "capacity": 60},
    {"plate_number": "AA-3-F56789", "device_id": "IMEI005678901234", "bus_type": "Anbessa", "capacity": 80},
    {"plate_number": "AA-3-G67890", "device_id": "IMEI006789012345", "bus_type": "Minibus", "capacity": 12},
    {"plate_number": "AA-3-H78901", "device_id": "IMEI007890123456", "bus_type": "Anbessa", "capacity": 80},
    {"plate_number": "AA-3-I89012", "device_id": "IMEI008901234567", "bus_type": "Sheger",  "capacity": 60},
    {"plate_number": "AA-3-J90123", "device_id": "IMEI009012345678", "bus_type": "Anbessa", "capacity": 80},
    {"plate_number": "AA-3-K01234", "device_id": "IMEI010123456789", "bus_type": "Minibus", "capacity": 12},
]

# ── Drivers ────────────────────────────────────────────────────────────────────
DRIVERS = [
    {"username": "driver_tadesse",  "email": "tadesse@bustrack.et",  "password": "Pass@1234"},
    {"username": "driver_almaz",    "email": "almaz@bustrack.et",    "password": "Pass@1234"},
    {"username": "driver_kebede",   "email": "kebede@bustrack.et",   "password": "Pass@1234"},
    {"username": "driver_meron",    "email": "meron@bustrack.et",    "password": "Pass@1234"},
    {"username": "driver_girma",    "email": "girma@bustrack.et",    "password": "Pass@1234"},
    {"username": "driver_senait",   "email": "senait@bustrack.et",   "password": "Pass@1234"},
    {"username": "driver_yohannes", "email": "yohannes@bustrack.et", "password": "Pass@1234"},
    {"username": "driver_hana",     "email": "hana@bustrack.et",     "password": "Pass@1234"},
    {"username": "driver_bekele",   "email": "bekele@bustrack.et",   "password": "Pass@1234"},
    {"username": "driver_tigist",   "email": "tigist@bustrack.et",   "password": "Pass@1234"},
]

# ── Passengers ─────────────────────────────────────────────────────────────────
PASSENGERS = [
    {"username": "passenger_sara",     "email": "sara@gmail.com",     "password": "Pass@1234"},
    {"username": "passenger_abebe",    "email": "abebe@gmail.com",    "password": "Pass@1234"},
    {"username": "passenger_fatuma",   "email": "fatuma@gmail.com",   "password": "Pass@1234"},
    {"username": "passenger_daniel",   "email": "daniel@gmail.com",   "password": "Pass@1234"},
    {"username": "passenger_hiwot",    "email": "hiwot@gmail.com",    "password": "Pass@1234"},
    {"username": "passenger_michael",  "email": "michael@gmail.com",  "password": "Pass@1234"},
    {"username": "passenger_blen",     "email": "blen@gmail.com",     "password": "Pass@1234"},
    {"username": "passenger_dawit",    "email": "dawit@gmail.com",    "password": "Pass@1234"},
    {"username": "passenger_tsion",    "email": "tsion@gmail.com",    "password": "Pass@1234"},
    {"username": "passenger_habtamu", "email": "habtamu@gmail.com",  "password": "Pass@1234"},
    {"username": "passenger_liya",    "email": "liya@gmail.com",     "password": "Pass@1234"},
    {"username": "passenger_nardos",  "email": "nardos@gmail.com",   "password": "Pass@1234"},
    {"username": "passenger_rediet",  "email": "rediet@gmail.com",   "password": "Pass@1234"},
    {"username": "passenger_brook",   "email": "brook@gmail.com",    "password": "Pass@1234"},
    {"username": "passenger_eden",    "email": "eden@gmail.com",     "password": "Pass@1234"},
]

# ── Admin Credentials (pre-existing) ──────────────────────────────────────────
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")


def expand_fleet(extra: int) -> tuple[list[dict], list[dict]]:
    """Generate additional driver + vehicle dicts (unique IMEI / plate) for larger simulations."""
    if extra <= 0:
        return [], []
    drivers: list[dict] = []
    vehicles: list[dict] = []
    for i in range(extra):
        n = 200 + i
        drivers.append(
            {
                "username": f"driver_sim_{n}",
                "email": f"simfleet{n}@bustrack.et",
                "password": "Pass@1234",
            }
        )
        imei_body = f"{n:015d}"
        vehicles.append(
            {
                "plate_number": f"AA-SIM-{n:05d}",
                "device_id": f"IMEI{imei_body}",
                "bus_type": "Anbessa",
                "capacity": 70,
            }
        )
    return drivers, vehicles
