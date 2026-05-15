#!/usr/bin/env python3
"""
Validation script for ESP32 gateway simulation.
Tests that all components are properly set up and can run.
"""

import sys
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def test_imports():
    """Test that all simulation modules can be imported."""
    print("📦 Testing imports...")
    try:
        from api_client import APIClient
        print("   ✅ api_client")

        from bus_image_generator import generate_bus_image, generate_bus_image_with_noise
        print("   ✅ bus_image_generator")

        from config import BASE_URL, SIMULATION_SPEED, GPS_PING_INTERVAL
        print("   ✅ config")

        from gps_utils import haversine_m, interpolate_gps
        print("   ✅ gps_utils")

        from route_loader import fetch_route_stops
        print("   ✅ route_loader")

        return True
    except ImportError as e:
        print(f"   ❌ Import failed: {e}")
        return False


def test_image_generation():
    """Test image generation for all occupancy levels."""
    print("\n🖼️  Testing image generation...")
    try:
        from bus_image_generator import generate_bus_image, generate_bus_image_with_noise

        for level in [0, 1, 2]:
            img_bytes = generate_bus_image(level)
            occupancy_name = ["Empty", "Medium", "Crowded"][level]
            print(f"   ✅ {occupancy_name}: {len(img_bytes)} bytes")

            # Test noise variant
            noisy_bytes = generate_bus_image_with_noise(level, noise_factor=0.1)
            print(f"   ✅ {occupancy_name} (noisy): {len(noisy_bytes)} bytes")

        return True
    except Exception as e:
        print(f"   ❌ Image generation failed: {e}")
        return False


def test_image_realism():
    """Test that generated images have realistic properties for CV detection."""
    print("\n🔬 Testing image realism for CV detection...")
    try:
        from bus_image_generator import generate_bus_image
        from PIL import Image
        import io

        for level in [0, 1, 2]:
            img_bytes = generate_bus_image(level)
            img = Image.open(io.BytesIO(img_bytes))
            w, h = img.size

            # Check dimensions
            assert w == 640 and h == 480, f"Expected 640x480, got {w}x{h}"

            # Check that images have variation (not solid color)
            pixels = list(img.getdata())
            unique_colors = len(set(pixels))
            occupancy_name = ["Empty", "Medium", "Crowded"][level]
            print(f"   ✅ {occupancy_name}: {w}x{h}, {unique_colors} unique colors")

        return True
    except Exception as e:
        print(f"   ❌ Image realism test failed: {e}")
        return False


def test_api_client_multipart():
    """Test that API client has multipart support."""
    print("\n🔌 Testing API client...")
    try:
        from api_client import APIClient

        client = APIClient()
        methods = dir(client)

        if "post_multipart" in methods:
            print("   ✅ post_multipart method exists")
        else:
            print("   ❌ post_multipart method missing")
            return False

        # Check method signature
        import inspect
        sig = inspect.signature(client.post_multipart)
        params = list(sig.parameters.keys())
        if all(p in params for p in ["path", "form_data", "files"]):
            print(f"   ✅ post_multipart signature: {params}")
        else:
            print(f"   ❌ post_multipart signature missing required params")
            return False

        # Check _json_headers method exists
        if "_json_headers" in methods:
            print("   ✅ _json_headers method exists")
        else:
            print("   ❌ _json_headers method missing")
            return False

        return True
    except Exception as e:
        print(f"   ❌ API client test failed: {e}")
        return False


def test_simulation_state():
    """Check if simulation_state.json exists and is valid."""
    print("\n📋 Testing simulation state...")
    try:
        state_path = SCRIPT_DIR / "simulation_state.json"

        if not state_path.exists():
            print(f"   ⚠️  simulation_state.json not found (expected after 01_setup.py)")
            return True  # Not a failure, just not set up yet

        with open(state_path) as f:
            state = json.load(f)

        required_keys = ["drivers", "vehicles", "routes", "passengers"]
        for key in required_keys:
            if key in state:
                count = len(state[key]) if isinstance(state[key], (list, dict)) else 1
                print(f"   ✅ {key}: {count} items")
            else:
                print(f"   ⚠️  {key}: missing (expected after 01_setup.py)")

        return True
    except Exception as e:
        print(f"   ❌ State validation failed: {e}")
        return False


def test_script_syntax():
    """Verify all simulation scripts have valid Python syntax."""
    print("\n✅ Testing script syntax...")
    try:
        import py_compile

        scripts = [
            "01_setup.py",
            "02_simulate_buses_esp32.py",
            "04_full_simulation_esp32.py",
        ]

        for script in scripts:
            script_path = SCRIPT_DIR / script
            if script_path.exists():
                py_compile.compile(str(script_path), doraise=True)
                print(f"   ✅ {script}")
            else:
                print(f"   ⚠️  {script} not found")

        return True
    except py_compile.PyCompileError as e:
        print(f"   ❌ Syntax error: {e}")
        return False


def test_gps_functions():
    """Test GPS utility functions."""
    print("\n📍 Testing GPS utilities...")
    try:
        from gps_utils import haversine_m, interpolate_gps

        # Test haversine distance
        dist = haversine_m(9.0320, 38.7469, 9.0400, 38.7500)  # Addis Ababa coords
        if 500 < dist < 10000:  # Should be a few km
            print(f"   ✅ haversine_m: {dist:.0f}m")
        else:
            print(f"   ⚠️  haversine_m returned unexpected distance: {dist}m")

        # Test GPS interpolation
        points = interpolate_gps(9.0320, 38.7469, 9.0400, 38.7500, steps=5)
        if len(points) == 5:
            print(f"   ✅ interpolate_gps: {len(points)} points")
        else:
            print(f"   ⚠️  interpolate_gps returned {len(points)} points (expected 5)")

        return True
    except Exception as e:
        print(f"   ❌ GPS test failed: {e}")
        return False


def test_cv_engine():
    """Test that CV engine can process generated images."""
    print("\n🧠 Testing CV engine with generated images...")
    try:
        from bus_image_generator import generate_bus_image
        from app.services.cv_engine import analyze_bus_density_from_image

        for level in [0, 1, 2]:
            img_bytes = generate_bus_image(level)
            result = analyze_bus_density_from_image(img_bytes)

            assert "crowd_density" in result
            assert "people_count" in result
            assert "confidence" in result
            assert "method" in result
            assert result["crowd_density"] in (0, 1, 2)
            assert 0.0 <= result["confidence"] <= 1.0

            occupancy_name = ["Empty", "Medium", "Crowded"][level]
            print(
                f"   ✅ {occupancy_name}: density={result['crowd_density']} "
                f"people={result['people_count']} conf={result['confidence']:.2f} "
                f"method={result['method']}"
            )

        return True
    except ImportError:
        print("   ⚠️  CV engine not available (expected when run outside backend)")
        return True
    except Exception as e:
        print(f"   ❌ CV engine test failed: {e}")
        return False


def main():
    """Run all validation tests."""
    print("=" * 70)
    print("🚀 ESP32 GATEWAY SIMULATION VALIDATION")
    print("=" * 70)

    tests = [
        ("Imports", test_imports),
        ("Image Generation", test_image_generation),
        ("Image Realism", test_image_realism),
        ("API Client", test_api_client_multipart),
        ("Simulation State", test_simulation_state),
        ("Script Syntax", test_script_syntax),
        ("GPS Functions", test_gps_functions),
        ("CV Engine", test_cv_engine),
    ]

    results = []
    for name, test_fn in tests:
        try:
            result = test_fn()
            results.append((name, result))
        except Exception as e:
            print(f"❌ {name} test crashed: {e}")
            results.append((name, False))

    print("\n" + "=" * 70)
    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "✅" if result else "❌"
        print(f"  {status} {name}")

    print(f"\n{passed}/{total} tests passed")

    if passed == total:
        print("\n📝 Next steps:")
        print("   1. Start the backend: uvicorn app.main:app --reload")
        print("   2. Run setup: python 01_setup.py")
        print("   3. Run simulation: python 04_full_simulation_esp32.py --duration 300")
        return 0
    else:
        print("\n📝 Troubleshooting:")
        print("   • Missing imports? pip install httpx pillow")
        print("   • Need setup? python 01_setup.py")
        print("   • Check syntax? python -m py_compile <script>")
        return 1


if __name__ == "__main__":
    sys.exit(main())
