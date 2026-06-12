"""
Test script: Run CV analysis on the test image, create a test bus,
send telemetry to the backend, and verify Redis occupancy data.

Usage:
    cd backend && env/bin/python test_cv_pipeline.py
"""

import asyncio
import io
import sys
from pathlib import Path

# ── Bootstrap: add project root to path ──
BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

# Load .env manually, stopping at the Azure CLI section
def _load_env_safely(path: Path):
    """Load .env file, stopping when we hit non-env-var lines (Azure CLI block)."""
    import os
    for line in path.read_text().splitlines():
        stripped = line.strip()
        # Stop at the Azure CLI command block
        if stripped.startswith("az "):
            break
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key, _, value = stripped.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and " " not in key:
                os.environ.setdefault(key, value)

_load_env_safely(BACKEND_DIR / ".env")

# NOW patch pydantic_settings to NOT re-read .env (we already loaded it cleanly)
import os
os.environ["_DOTENV_LOADED"] = "1"  # hack: not used, but we need to prevent pydantic from re-reading

import httpx
import redis.asyncio as redis

# Import settings class directly, bypassing the cached get_settings which may have already loaded
from app.core.config import Settings
from app.services.cv_engine import analyze_bus_density_from_image
settings = Settings(_env_file=None)  # don't re-read .env

# ── Config ──
TEST_IMAGE_PATH = BACKEND_DIR / "cvtestimg" / "The London Underground.jpeg"
API_BASE = "https://api.bustrack.dpdns.org/api/v1"
DEVICE_ID = "TEST_BUSOFMY_001"
PLATE_NUMBER = "busofmy"
BUS_TYPE = "TestBus"
BUS_CAPACITY = 40
# Addis Ababa coordinates (near Meskel Square)
TEST_LAT = 9.0192
TEST_LON = 38.7525
TEST_SPEED = 25.5


def _build_redis_kwargs(url: str) -> dict:
    kwargs = {"decode_responses": True}
    if url.startswith("rediss://"):
        import ssl
        kwargs["ssl"] = True
        kwargs["ssl_cert_reqs"] = ssl.CERT_NONE
    return kwargs


async def step1_analyze_image():
    """Step 1: Run CV analysis on the test image."""
    print("=" * 70)
    print("STEP 1: CV Analysis on test image")
    print("=" * 70)

    image_bytes = TEST_IMAGE_PATH.read_bytes()
    print(f"Image: {TEST_IMAGE_PATH.name} ({len(image_bytes):,} bytes)")

    result = analyze_bus_density_from_image(image_bytes, BUS_CAPACITY)

    print("\nCV Result:")
    print(f"  human_count    : {result['human_count']}")
    print(f"  people_count   : {result['people_count']}")
    print(f"  crowd_density  : {result['crowd_density']}  (0=Low, 1=Med, 2=High)")
    print(f"  is_crowded     : {result['is_crowded']}")
    print(f"  method         : {result['method']}")
    print(f"  confidence     : {result['confidence']}")
    print(f"  foreground_ratio: {result['foreground_ratio']}")

    return result


async def step2_check_server():
    """Step 2: Check if the backend server is running."""
    print("\n" + "=" * 70)
    print("STEP 2: Check backend server health")
    print("=" * 70)

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(f"{API_BASE.replace('/api/v1', '')}/health")
            data = resp.json()
            print(f"Status: {data.get('status')}")
            print(f"Database: {data.get('database')}")
            print(f"Redis: {data.get('redis')}")
            if data.get('status') != 'healthy':
                print("⚠️  Server is not fully healthy!")
            return True
        except Exception as e:
            print(f"❌ Cannot reach backend server at {API_BASE}")
            print(f"   Error: {e}")
            print("   Make sure the server is running: uvicorn app.main:app --reload")
            return False


async def step3_register_vehicle():
    """Step 3: Register the test vehicle in the database."""
    print("\n" + "=" * 70)
    print("STEP 3: Register test vehicle")
    print("=" * 70)

    async with httpx.AsyncClient(timeout=10) as client:
        # Try to register
        resp = await client.post(f"{API_BASE}/vehicles", json={
            "plate_number": PLATE_NUMBER,
            "device_id": DEVICE_ID,
            "bus_type": BUS_TYPE,
            "capacity": BUS_CAPACITY,
            "is_active": True,
        })
        print(f"Register vehicle response: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"  Vehicle ID  : {data.get('id')}")
            print(f"  Plate       : {data.get('plate_number')}")
            print(f"  Device ID   : {data.get('device_id')}")
            print(f"  Bus Type    : {data.get('bus_type')}")
            print(f"  Capacity    : {data.get('capacity')}")
        elif resp.status_code == 400:
            print(f"  Vehicle already exists (400): {resp.text}")
        else:
            print(f"  Response: {resp.text}")


async def step4_send_telemetry_image(cv_result):
    """Step 4: Send multipart telemetry with image to /gateway/esp32/telemetry."""
    print("\n" + "=" * 70)
    print("STEP 4: Send ESP32-CAM telemetry (with image)")
    print("=" * 70)

    image_bytes = TEST_IMAGE_PATH.read_bytes()

    # Build multipart form data
    data = {
        "device_id": DEVICE_ID,
        "plate_number": PLATE_NUMBER,
        "bus_type": BUS_TYPE,
        "lat": str(TEST_LAT),
        "lon": str(TEST_LON),
        "speed": str(TEST_SPEED),
        "bus_capacity": str(BUS_CAPACITY),
        "occupancy_level": str(cv_result["crowd_density"]),
    }

    files = {
        "image": ("test_frame.jpg", io.BytesIO(image_bytes), "image/jpeg"),
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{API_BASE}/gateway/esp32/telemetry",
            data=data,
            files=files,
        )
        print(f"Response status: {resp.status_code}")
        if resp.status_code == 200:
            result = resp.json()
            print("\nBackend response:")
            print(f"  status          : {result.get('status')}")
            print(f"  vehicle_id      : {result.get('vehicle_id')}")
            print(f"  plate_number    : {result.get('plate_number')}")
            print(f"  occupancy_level : {result.get('occupancy_level')}")
            print(f"  cv_occupancy    : {result.get('cv_occupancy_level')}")
            print(f"  image_saved     : {result.get('image_saved')}")
            print(f"  route_checked   : {result.get('route_checked')}")
            print(f"  eta_computed    : {result.get('eta_computed')}")
            if result.get('cv'):
                cv = result['cv']
                print(f"  cv.people_count  : {cv.get('people_count')}")
                print(f"  cv.crowd_density : {cv.get('crowd_density')}")
                print(f"  cv.is_crowded    : {cv.get('is_crowded')}")
                print(f"  cv.method        : {cv.get('method')}")
                print(f"  cv.confidence    : {cv.get('confidence')}")
                print(f"  cv.fg_ratio      : {cv.get('foreground_ratio')}")
            return result
        else:
            print(f"Error response: {resp.text}")
            return None


async def step5_send_telemetry_gps(cv_result):
    """Step 5: Send GPS-only telemetry to /telemetry."""
    print("\n" + "=" * 70)
    print("STEP 5: Send GPS-only telemetry (no image)")
    print("=" * 70)

    payload = {
        "device_id": DEVICE_ID,
        "lat": TEST_LAT + 0.001,  # slightly different position
        "lon": TEST_LON + 0.001,
        "speed": TEST_SPEED + 5.0,
        "pixel_count": cv_result["people_count"] * 500,  # simulate pixel count
        "raw_payload": {
            "source": "test_script",
            "occupancy_level": cv_result["crowd_density"],
            "cv": {
                "people_count": cv_result["people_count"],
                "crowd_density": cv_result["crowd_density"],
                "is_crowded": cv_result["is_crowded"],
                "method": cv_result["method"],
                "confidence": cv_result["confidence"],
            }
        }
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"{API_BASE}/telemetry", json=payload)
        print(f"Response status: {resp.status_code}")
        if resp.status_code == 200:
            result = resp.json()
            print("\nBackend response:")
            print(f"  status          : {result.get('status')}")
            print(f"  vehicle_id      : {result.get('vehicle_id')}")
            print(f"  occupancy_level : {result.get('occupancy_level')}")
            print(f"  route_checked   : {result.get('route_checked')}")
            return result
        else:
            print(f"Error response: {resp.text}")
            return None


async def step6_check_redis():
    """Step 6: Read back from Redis to verify occupancy data was written."""
    print("\n" + "=" * 70)
    print("STEP 6: Verify Redis data")
    print("=" * 70)

    kwargs = _build_redis_kwargs(settings.REDIS_URL)
    r = redis.from_url(settings.REDIS_URL, **kwargs)

    try:
        await r.ping()
        print("✅ Redis connected")
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        return

    # Check bus:live:{plate}
    live_key = f"bus:live:{PLATE_NUMBER}"
    print(f"\n--- Redis Hash: {live_key} ---")
    live_data = await r.hgetall(live_key)
    if live_data:
        for k, v in live_data.items():
            print(f"  {k}: {v}")
        occ = live_data.get("occupancy_level")
        if occ is not None and occ != "":
            print(f"\n  ✅ occupancy_level = {occ}")
        else:
            print("\n  ❌ occupancy_level is missing or empty!")
    else:
        print(f"  ❌ Key {live_key} does not exist or is empty!")

    # Check veh:cv:{plate}
    cv_key = f"veh:cv:{PLATE_NUMBER}"
    print(f"\n--- Redis Hash: {cv_key} ---")
    cv_data = await r.hgetall(cv_key)
    if cv_data:
        for k, v in cv_data.items():
            print(f"  {k}: {v}")
        occ = cv_data.get("occupancy_level")
        if occ is not None and occ != "":
            print(f"\n  ✅ occupancy_level = {occ}")
        else:
            print("\n  ❌ occupancy_level is missing or empty!")
    else:
        print(f"  ❌ Key {cv_key} does not exist or is empty!")

    # Check veh:pos:{plate}
    pos_key = f"veh:pos:{PLATE_NUMBER}"
    print(f"\n--- Redis String: {pos_key} ---")
    pos_data = await r.get(pos_key)
    if pos_data:
        print(f"  position: {pos_data}")
    else:
        print(f"  ❌ Key {pos_key} does not exist!")

    # Check pipe:positions stream
    print("\n--- Redis Stream: pipe:positions (last 3 entries) ---")
    stream_data = await r.xrevrange("pipe:positions", count=3)
    if stream_data:
        for entry_id, fields in stream_data:
            if fields.get("plate") == PLATE_NUMBER:
                print(f"  [{entry_id}]")
                for k, v in fields.items():
                    print(f"    {k}: {v}")
    else:
        print("  No entries in stream")

    # Check TTL
    ttl_live = await r.ttl(live_key)
    ttl_cv = await r.ttl(cv_key)
    print("\n--- TTL ---")
    print(f"  {live_key}: {ttl_live}s")
    print(f"  {cv_key}: {ttl_cv}s")

    await r.aclose()


async def step7_check_api_positions():
    """Step 7: Query the REST API to verify positions endpoint returns occupancy."""
    print("\n" + "=" * 70)
    print("STEP 7: Query GET /vehicles/positions (what the app polls)")
    print("=" * 70)

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{API_BASE}/vehicles/positions")
        print(f"Response status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            positions = data.get("positions", {})
            print(f"Timestamp: {data.get('timestamp')}")
            print(f"Total vehicles: {len(positions)}")

            # Find our test bus
            for key, pos in positions.items():
                if pos.get("plate_number") == PLATE_NUMBER or key == PLATE_NUMBER:
                    print(f"\n  ✅ Found test bus (key={key}):")
                    print(f"    vehicle_id     : {pos.get('vehicle_id')}")
                    print(f"    plate_number   : {pos.get('plate_number')}")
                    print(f"    lat            : {pos.get('lat')}")
                    print(f"    lon            : {pos.get('lon')}")
                    print(f"    speed          : {pos.get('speed')}")
                    print(f"    occupancy_level: {pos.get('occupancy_level')}")
                    print(f"    route_id       : {pos.get('route_id')}")
                    print(f"    assignment_id  : {pos.get('assignment_id')}")
                    print(f"    timestamp      : {pos.get('timestamp')}")

                    occ = pos.get("occupancy_level")
                    if occ is not None and occ != 0:
                        print(f"\n    ✅✅ occupancy_level = {occ} — THE APP WILL SHOW THIS!")
                    elif occ == 0:
                        print("\n    ⚠️ occupancy_level = 0 (Low/empty — CV may have detected no crowd)")
                    else:
                        print("\n    ❌ occupancy_level is missing!")
                    return

            print(f"\n  ❌ Test bus {PLATE_NUMBER} not found in positions response!")
            print(f"  Available plates: {[p.get('plate_number') for p in positions.values()]}")
        else:
            print(f"Error: {resp.text}")


async def main():
    print("🚌 CV Pipeline Test — Full End-to-End")
    print(f"   Image: {TEST_IMAGE_PATH}")
    print(f"   Plate: {PLATE_NUMBER}")
    print(f"   API:   {API_BASE}")
    print(f"   Redis: {settings.REDIS_URL[:50]}...")

    # Step 1: Analyze image
    cv_result = await step1_analyze_image()

    # Step 2: Check server
    server_ok = await step2_check_server()
    if not server_ok:
        print("\n❌ Backend server is not running. Start it with:")
        print("   cd backend && env/bin/uvicorn app.main:app --reload --port 8000")
        sys.exit(1)

    # Step 3: Register vehicle
    await step3_register_vehicle()

    # Step 4: Send telemetry with image
    await step4_send_telemetry_image(cv_result)

    # Step 5: Send GPS-only telemetry
    await step5_send_telemetry_gps(cv_result)

    # Wait a moment for async operations to complete
    print("\n⏳ Waiting 2 seconds for async Redis writes...")
    await asyncio.sleep(2)

    # Step 6: Check Redis
    await step6_check_redis()

    # Step 7: Check API
    await step7_check_api_positions()

    print("\n" + "=" * 70)
    print("🏁 TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
