"""
Performance Benchmark Suite for BusTrack
=========================================

Measures real system performance metrics and writes results to a CSV file.
Run against a LIVE deployed backend (not the test client) so measurements
reflect real network latency, database queries, and Redis operations.

Usage:
  # Run against local backend
  python -m pytest tests/test_performance.py -v -s

  # Run against deployed backend
  API_BASE=https://bustrack.dpdns.org python -m pytest tests/test_performance.py -v -s

  # Run specific benchmark
  python -m pytest tests/test_performance.py::test_api_latency_search -v -s

Output:
  storage/benchmark_results.csv  — all measurements in one file
  storage/benchmark_results.json — same data in JSON (easier to parse)
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import statistics
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin123456")
RESULTS_DIR = Path(__file__).resolve().parents[1] / "storage"
CSV_PATH = RESULTS_DIR / "benchmark_results.csv"
JSON_PATH = RESULTS_DIR / "benchmark_results.json"

# Number of iterations for each benchmark
ITERATIONS = int(os.environ.get("BENCHMARK_ITERATIONS", "30"))
WARMUP_ITERATIONS = 5  # discarded — not counted in results

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BenchmarkResult:
    """Collects measurements and writes CSV + JSON."""

    def __init__(self):
        self.rows: list[dict[str, Any]] = []
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    def add(
        self,
        category: str,
        metric: str,
        unit: str,
        value: float,
        iterations: int,
        details: str = "",
    ):
        self.rows.append({
            "timestamp": _now(),
            "category": category,
            "metric": metric,
            "unit": unit,
            "value": round(value, 4),
            "iterations": iterations,
            "details": details,
            "api_base": API_BASE,
        })

    def add_stats(
        self,
        category: str,
        metric: str,
        unit: str,
        measurements: list[float],
        details: str = "",
    ):
        """Compute summary stats from a list of measurements and write one row."""
        if not measurements:
            return
        self.rows.append({
            "timestamp": _now(),
            "category": category,
            "metric": f"{metric}_mean",
            "unit": unit,
            "value": round(statistics.mean(measurements), 4),
            "iterations": len(measurements),
            "details": details,
            "api_base": API_BASE,
        })
        if len(measurements) >= 2:
            self.rows.append({
                "timestamp": _now(),
                "category": category,
                "metric": f"{metric}_median",
                "unit": unit,
                "value": round(statistics.median(measurements), 4),
                "iterations": len(measurements),
                "details": details,
                "api_base": API_BASE,
            })
            self.rows.append({
                "timestamp": _now(),
                "category": category,
                "metric": f"{metric}_p95",
                "unit": unit,
                "value": round(sorted(measurements)[int(len(measurements) * 0.95)], 4),
                "iterations": len(measurements),
                "details": details,
                "api_base": API_BASE,
            })
            self.rows.append({
                "timestamp": _now(),
                "category": category,
                "metric": f"{metric}_min",
                "unit": unit,
                "value": round(min(measurements), 4),
                "iterations": len(measurements),
                "details": details,
                "api_base": API_BASE,
            })
            self.rows.append({
                "timestamp": _now(),
                "category": category,
                "metric": f"{metric}_max",
                "unit": unit,
                "value": round(max(measurements), 4),
                "iterations": len(measurements),
                "details": details,
                "api_base": API_BASE,
            })
            self.rows.append({
                "timestamp": _now(),
                "category": category,
                "metric": f"{metric}_stddev",
                "unit": unit,
                "value": round(statistics.stdev(measurements), 4),
                "iterations": len(measurements),
                "details": details,
                "api_base": API_BASE,
            })

    def write_csv(self):
        if not self.rows:
            return
        fieldnames = [
            "timestamp", "category", "metric", "unit",
            "value", "iterations", "details", "api_base",
        ]
        write_header = not CSV_PATH.exists()
        with open(CSV_PATH, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            writer.writerows(self.rows)
        print(f"\n  📄 CSV written: {CSV_PATH} ({len(self.rows)} rows)")

    def write_json(self):
        if not self.rows:
            return
        # Append to existing JSON if present
        existing: list[dict] = []
        if JSON_PATH.exists():
            try:
                existing = json.loads(JSON_PATH.read_text())
            except Exception:
                pass
        existing.extend(self.rows)
        JSON_PATH.write_text(json.dumps(existing, indent=2, default=str))
        print(f"  📄 JSON written: {JSON_PATH} ({len(existing)} total rows)")


# Global collector — populated during tests, written in session-scoped fixture
bench = BenchmarkResult()


@pytest.fixture(autouse=True, scope="session")
def _write_results_at_end():
    """Write CSV + JSON after all tests complete."""
    yield
    bench.write_csv()
    bench.write_json()


async def _measure_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
    headers: dict | None = None,
    data: dict | None = None,
    files: dict | None = None,
) -> tuple[float, httpx.Response]:
    """Send a request and return (elapsed_seconds, response)."""
    t0 = time.monotonic()
    if method == "POST":
        if files:
            resp = await client.post(
                f"{API_BASE}{path}", data=data, files=files, headers=headers, timeout=30
            )
        elif json_body is not None:
            resp = await client.post(
                f"{API_BASE}{path}", json=json_body, headers=headers, timeout=30
            )
        else:
            resp = await client.post(
                f"{API_BASE}{path}", data=data, headers=headers, timeout=30
            )
    else:
        resp = await client.get(f"{API_BASE}{path}", headers=headers, timeout=30)
    elapsed = time.monotonic() - t0
    return elapsed, resp


async def _run_benchmark(
    client: httpx.AsyncClient,
    category: str,
    metric_name: str,
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
    headers: dict | None = None,
    expected_status: int = 200,
    warmup: int = WARMUP_ITERATIONS,
    iterations: int = ITERATIONS,
    unit: str = "seconds",
) -> list[float]:
    """Run a request multiple times, discard warmup, collect measurements."""
    measurements: list[float] = []

    # Warmup phase — not recorded
    for _ in range(warmup):
        try:
            _, resp = await _measure_request(
                client, method, path, json_body=json_body, headers=headers
            )
        except Exception:
            pass

    # Measured phase
    errors = 0
    for i in range(iterations):
        try:
            elapsed, resp = await _measure_request(
                client, method, path, json_body=json_body, headers=headers
            )
            if resp.status_code == expected_status:
                measurements.append(elapsed)
            else:
                errors += 1
        except Exception:
            errors += 1

    details = f"errors={errors}/{iterations}"
    bench.add_stats(category, metric_name, unit, measurements, details)
    return measurements


# ===========================================================================
# 1. API LATENCY BENCHMARKS
# ===========================================================================

@pytest.fixture(scope="session")
async def client():
    async with httpx.AsyncClient() as c:
        yield c


@pytest.fixture(scope="session")
async def admin_token(client: httpx.AsyncClient) -> str:
    """Login as admin and return JWT token."""
    resp = await client.post(f"{API_BASE}/api/v1/auth/login", json={
        "username": ADMIN_USER, "password": ADMIN_PASS
    })
    if resp.status_code != 200:
        pytest.skip(f"Admin login failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()["access_token"]


@pytest.fixture(scope="session")
async def setup_test_data(client: httpx.AsyncClient, admin_token: str) -> dict:
    """Create test stops, route, vehicle, driver, assignment. Returns IDs."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    data: dict[str, Any] = {}

    # Create stops
    stop_names = [
        ("Bench A", 9.020, 38.730),
        ("Bench B", 9.030, 38.740),
        ("Bench C", 9.040, 38.750),
        ("Bench D", 9.050, 38.760),
    ]
    stop_ids = []
    for name, lat, lon in stop_names:
        resp = await client.post(f"{API_BASE}/api/v1/routes/stops", headers=headers, json={
            "name": name, "lat": lat, "lon": lon,
            "base_dwell_time": 30, "is_terminal": False, "peak_multiplier": 1.0,
        })
        if resp.status_code == 200:
            stop_ids.append(resp.json()["id"])
        else:
            # Try to find existing
            r = await client.get(f"{API_BASE}/api/v1/routes/stops?limit=200", headers=headers)
            if r.status_code == 200:
                for s in r.json():
                    if s["name"] == name:
                        stop_ids.append(s["id"])
                        break
    data["stop_ids"] = stop_ids

    # Create route
    route_stops = [{"stop_id": sid, "sequence_order": i + 1} for i, sid in enumerate(stop_ids)]
    resp = await client.post(f"{API_BASE}/api/v1/routes", headers=headers, json={
        "route_number": f"BENCH-{uuid.uuid4().hex[:6]}",
        "name": "Benchmark Route",
        "origin": stop_names[0][0],
        "destination": stop_names[-1][0],
        "stops": route_stops,
    })
    if resp.status_code == 200:
        data["route_id"] = resp.json()["id"]
    else:
        r = await client.get(f"{API_BASE}/api/v1/routes?limit=200", headers=headers)
        if r.status_code == 200 and r.json():
            data["route_id"] = r.json()[0]["id"]

    # Create vehicle
    plate = f"BENCH-{uuid.uuid4().hex[:6]}"
    resp = await client.post(f"{API_BASE}/api/v1/vehicles", headers=headers, json={
        "plate_number": plate,
        "device_id": f"BENCH-DEV-{uuid.uuid4().hex[:8]}",
        "bus_type": "Benchmark",
        "capacity": 52,
        "is_active": True,
    })
    if resp.status_code == 200:
        data["vehicle_id"] = resp.json()["id"]
        data["device_id"] = f"BENCH-DEV-{uuid.uuid4().hex[:8]}"
        # Assign route
        await client.put(
            f"{API_BASE}/api/v1/vehicles/{data['vehicle_id']}",
            headers=headers,
            json={"route_id": data["route_id"]},
        )

    # Create driver
    resp = await client.post(f"{API_BASE}/api/v1/admin/users/create", headers=headers, json={
        "username": f"bench_{uuid.uuid4().hex[:8]}",
        "email": f"bench_{uuid.uuid4().hex[:8]}@test.local",
        "password": "bench123456",
        "role": "driver",
    })
    if resp.status_code == 200:
        data["driver_id"] = resp.json()["id"]

    # Start assignment
    if all(k in data for k in ("driver_id", "vehicle_id", "route_id")):
        resp = await client.post(f"{API_BASE}/api/v1/assignments/start", headers=headers, json={
            "driver_id": data["driver_id"],
            "vehicle_id": data["vehicle_id"],
            "route_id": data["route_id"],
        })
        if resp.status_code == 200:
            data["assignment_id"] = resp.json()["id"]

    return data


@pytest.mark.asyncio
async def test_api_latency_health(client: httpx.AsyncClient):
    """GET /health — should be the fastest endpoint."""
    await _run_benchmark(
        client, "api_latency", "health_check", "GET", "/health",
        iterations=ITERATIONS,
    )


@pytest.mark.asyncio
async def test_api_latency_login(client: httpx.AsyncClient):
    """POST /api/v1/auth/login — authentication latency."""
    await _run_benchmark(
        client, "api_latency", "auth_login", "POST", "/api/v1/auth/login",
        json_body={"username": ADMIN_USER, "password": ADMIN_PASS},
        iterations=ITERATIONS,
    )


@pytest.mark.asyncio
async def test_api_latency_vehicles_list(client: httpx.AsyncClient, admin_token: str):
    """GET /api/v1/vehicles — list vehicles."""
    await _run_benchmark(
        client, "api_latency", "vehicles_list", "GET", "/api/v1/vehicles?limit=100",
        headers={"Authorization": f"Bearer {admin_token}"},
        iterations=ITERATIONS,
    )


@pytest.mark.asyncio
async def test_api_latency_routes_list(client: httpx.AsyncClient, admin_token: str):
    """GET /api/v1/routes — list routes."""
    await _run_benchmark(
        client, "api_latency", "routes_list", "GET", "/api/v1/routes?limit=200",
        headers={"Authorization": f"Bearer {admin_token}"},
        iterations=ITERATIONS,
    )


@pytest.mark.asyncio
async def test_api_latency_stops_list(client: httpx.AsyncClient, admin_token: str):
    """GET /api/v1/routes/stops — list stops."""
    await _run_benchmark(
        client, "api_latency", "stops_list", "GET", "/api/v1/routes/stops?limit=200",
        headers={"Authorization": f"Bearer {admin_token}"},
        iterations=ITERATIONS,
    )


@pytest.mark.asyncio
async def test_api_latency_point_to_point_search(
    client: httpx.AsyncClient, setup_test_data: dict
):
    """POST /api/v1/search/point-to-point — core search with ETA computation."""
    stop_ids = setup_test_data.get("stop_ids", [])
    if len(stop_ids) < 2:
        pytest.skip("Need at least 2 stops for search benchmark")
    await _run_benchmark(
        client, "api_latency", "search_point_to_point", "POST",
        "/api/v1/search/point-to-point",
        json_body={"start_stop_id": stop_ids[0], "end_stop_id": stop_ids[-1]},
        iterations=ITERATIONS,
    )


@pytest.mark.asyncio
async def test_api_latency_journey_search(
    client: httpx.AsyncClient, setup_test_data: dict
):
    """POST /api/v1/search/journey — geo-to-stop resolution + search."""
    stop_ids = setup_test_data.get("stop_ids", [])
    if len(stop_ids) < 2:
        pytest.skip("Need at least 2 stops for search benchmark")
    await _run_benchmark(
        client, "api_latency", "search_journey", "POST",
        "/api/v1/search/journey",
        json_body={
            "start_lat": 9.020, "start_lon": 38.730,
            "end_lat": 9.050, "end_lon": 38.760,
        },
        iterations=ITERATIONS,
    )


@pytest.mark.asyncio
async def test_api_latency_telemetry_gps_only(client: httpx.AsyncClient, setup_test_data: dict):
    """POST /api/v1/telemetry — GPS-only telemetry ingestion."""
    vehicle_id = setup_test_data.get("vehicle_id")
    if not vehicle_id:
        pytest.skip("Need a vehicle for telemetry benchmark")
    # We need the device_id — use a known one
    device_id = setup_test_data.get("device_id", f"BENCH-DEV-{uuid.uuid4().hex[:8]}")
    await _run_benchmark(
        client, "api_latency", "telemetry_gps_only", "POST", "/api/v1/telemetry",
        json_body={
            "device_id": device_id,
            "lat": 9.032, "lon": 38.752,
            "speed": 25.0, "pixel_count": 3000,
        },
        iterations=ITERATIONS,
    )


@pytest.mark.asyncio
async def test_api_latency_admin_dashboard(
    client: httpx.AsyncClient, admin_token: str
):
    """GET /api/v1/admin/dashboard/analytics — analytics aggregation."""
    await _run_benchmark(
        client, "api_latency", "admin_dashboard_analytics", "GET",
        "/api/v1/admin/dashboard/analytics?days=7",
        headers={"Authorization": f"Bearer {admin_token}"},
        iterations=max(10, ITERATIONS // 3),  # fewer iterations — heavier query
    )


@pytest.mark.asyncio
async def test_api_latency_vehicle_positions(
    client: httpx.AsyncClient, admin_token: str
):
    """GET /api/v1/vehicles/positions — live position aggregation."""
    await _run_benchmark(
        client, "api_latency", "vehicle_positions", "GET",
        "/api/v1/vehicles/positions",
        headers={"Authorization": f"Bearer {admin_token}"},
        iterations=ITERATIONS,
    )


# ===========================================================================
# 2. TELEMETRY PIPELINE LATENCY (end-to-end)
# ===========================================================================

@pytest.mark.asyncio
async def test_telemetry_pipeline_latency(client: httpx.AsyncClient, setup_test_data: dict):
    """
    Measure the full telemetry ingestion pipeline:
    request → vehicle resolution → GPS validation → Redis update →
    ETA computation → DB write → response.
    """
    device_id = setup_test_data.get("device_id")
    if not device_id:
        pytest.skip("Need a device_id for pipeline benchmark")

    measurements: list[float] = []
    for i in range(WARMUP_ITERATIONS + ITERATIONS):
        t0 = time.monotonic()
        resp = await client.post(f"{API_BASE}/api/v1/telemetry", json={
            "device_id": device_id,
            "lat": 9.032 + i * 0.0001,
            "lon": 38.752 + i * 0.0001,
            "speed": 25.0,
            "pixel_count": 3000,
        }, timeout=30)
        elapsed = time.monotonic() - t0
        if i >= WARMUP_ITERATIONS and resp.status_code == 200:
            measurements.append(elapsed)

    bench.add_stats(
        "telemetry_pipeline", "full_ingestion", "seconds", measurements,
        details=f"GPS-only, no image. errors={ITERATIONS - len(measurements)}/{ITERATIONS}",
    )


# ===========================================================================
# 3. ETA COMPUTATION LATENCY
# ===========================================================================

@pytest.mark.asyncio
async def test_eta_computation_latency():
    """
    Measure pure ETA computation time (no network).
    Tests the heuristic and ML ETA engines directly.
    """
    from app.services.eta_calc import calculate_eta_heuristic
    from app.services.route_eta import estimate_route_stop_eta_payloads

    # 3a. Heuristic ETA — single pair
    measurements: list[float] = []
    for _ in range(WARMUP_ITERATIONS + ITERATIONS * 10):
        t0 = time.monotonic()
        calculate_eta_heuristic(9.03, 38.74, 9.05, 38.76, num_stops=5)
        elapsed = time.monotonic() - t0
        if _ >= WARMUP_ITERATIONS:
            measurements.append(elapsed)
    bench.add_stats("eta_computation", "heuristic_single_pair", "seconds", measurements)

    # 3b. Route-stop ETA payloads (multiple stops)
    from unittest.mock import MagicMock
    mock_stops = []
    for i in range(10):
        s = MagicMock()
        s.id = i + 1
        s.name = f"Stop {i+1}"
        s.lat = 9.02 + i * 0.003
        s.lon = 38.73 + i * 0.004
        s.base_dwell_time = 30
        s.peak_multiplier = 1.0
        mock_stops.append(s)

    measurements = []
    for _ in range(WARMUP_ITERATIONS + ITERATIONS):
        t0 = time.monotonic()
        estimate_route_stop_eta_payloads(
            9.03, 38.74, 30.0, 1, "TEST", 1, mock_stops,
            plate_number="TEST-001", vehicle_id=1,
        )
        elapsed = time.monotonic() - t0
        if _ >= WARMUP_ITERATIONS:
            measurements.append(elapsed)
    bench.add_stats(
        "eta_computation", "route_stop_payloads_10_stops", "seconds", measurements,
    )

    # 3c. ML ETA (if model loaded)
    from app.services.ai_predictor import model_loaded
    if model_loaded():
        from app.services.eta_engine import get_final_eta
        measurements = []
        for _ in range(WARMUP_ITERATIONS + ITERATIONS):
            t0 = time.monotonic()
            get_final_eta(9.03, 38.74, 9.05, 38.76, num_stops=5, stop_id=1, occupancy_level=1)
            elapsed = time.monotonic() - t0
            if _ >= WARMUP_ITERATIONS:
                measurements.append(elapsed)
        bench.add_stats("eta_computation", "ml_eta_with_features", "seconds", measurements)
    else:
        bench.add(
            "eta_computation", "ml_eta_with_features", "seconds", 0.0,
            0, details="ML model not loaded — skipped",
        )


# ===========================================================================
# 4. COMPUTER VISION INFERENCE TIME
# ===========================================================================

@pytest.mark.asyncio
async def test_cv_inference_latency():
    """
    Measure YOLOv8 inference time on a synthetic test image.
    Falls back to HOG if YOLO models are unavailable.
    """
    import cv2
    import numpy as np

    # Create a synthetic 640x480 test image (bus interior-like)
    frame = np.random.randint(50, 200, (480, 640, 3), dtype=np.uint8)
    _, buf = cv2.imencode(".jpg", frame)
    image_bytes = buf.tobytes()

    from app.services.yolo_detector import YoloDetector
    detector = YoloDetector()

    # Warmup
    for _ in range(3):
        await detector.detect(image_bytes, bus_capacity=40)

    # Measure
    measurements: list[float] = []
    method_used = ""
    for i in range(max(5, ITERATIONS // 3)):  # CV is slower, fewer iterations
        t0 = time.monotonic()
        result = await detector.detect(image_bytes, bus_capacity=40)
        elapsed = time.monotonic() - t0
        measurements.append(elapsed)
        method_used = result.get("method", "unknown")

    bench.add_stats(
        "computer_vision", "yolo_inference", "seconds", measurements,
        details=f"640x480 synthetic image, method={method_used}",
    )

    # Also measure HOG fallback
    from app.services.cv_engine import analyze_bus_density_from_image
    measurements_hog: list[float] = []
    for i in range(max(5, ITERATIONS // 3)):
        t0 = time.monotonic()
        analyze_bus_density_from_image(image_bytes, bus_capacity=40)
        elapsed = time.monotonic() - t0
        measurements_hog.append(elapsed)

    bench.add_stats(
        "computer_vision", "hog_fallback_inference", "seconds", measurements_hog,
        details="640x480 synthetic image",
    )


# ===========================================================================
# 5. THROUGHPUT TEST
# ===========================================================================

@pytest.mark.asyncio
async def test_throughput_telemetry(client: httpx.AsyncClient, setup_test_data: dict):
    """
    Send telemetry requests as fast as possible for 10 seconds.
    Count how many succeed per second.
    """
    device_id = setup_test_data.get("device_id")
    if not device_id:
        pytest.skip("Need device_id for throughput test")

    duration = 10  # seconds
    success_count = 0
    error_count = 0
    latencies: list[float] = []

    end_time = time.monotonic() + duration
    i = 0
    while time.monotonic() < end_time:
        t0 = time.monotonic()
        try:
            resp = await client.post(f"{API_BASE}/api/v1/telemetry", json={
                "device_id": device_id,
                "lat": 9.032 + (i % 100) * 0.0001,
                "lon": 38.752 + (i % 100) * 0.0001,
                "speed": 25.0,
                "pixel_count": 3000,
            }, timeout=5)
            elapsed = time.monotonic() - t0
            if resp.status_code == 200:
                success_count += 1
                latencies.append(elapsed)
            else:
                error_count += 1
        except Exception:
            error_count += 1
        i += 1

    throughput_per_sec = success_count / duration
    bench.add("throughput", "telemetry_requests_per_second", "req/s", throughput_per_sec,
              success_count, details=f"duration={duration}s, errors={error_count}")
    if latencies:
        bench.add_stats("throughput", "telemetry_request_latency_under_load", "seconds", latencies)


@pytest.mark.asyncio
async def test_throughput_search(client: httpx.AsyncClient, setup_test_data: dict):
    """
    Send search requests as fast as possible for 10 seconds.
    """
    stop_ids = setup_test_data.get("stop_ids", [])
    if len(stop_ids) < 2:
        pytest.skip("Need stops for throughput test")

    duration = 10
    success_count = 0
    error_count = 0
    latencies: list[float] = []

    end_time = time.monotonic() + duration
    while time.monotonic() < end_time:
        t0 = time.monotonic()
        try:
            resp = await client.post(f"{API_BASE}/api/v1/search/point-to-point", json={
                "start_stop_id": stop_ids[0],
                "end_stop_id": stop_ids[-1],
            }, timeout=10)
            elapsed = time.monotonic() - t0
            if resp.status_code == 200:
                success_count += 1
                latencies.append(elapsed)
            else:
                error_count += 1
        except Exception:
            error_count += 1

    throughput_per_sec = success_count / duration
    bench.add("throughput", "search_requests_per_second", "req/s", throughput_per_sec,
              success_count, details=f"duration={duration}s, errors={error_count}")
    if latencies:
        bench.add_stats("throughput", "search_request_latency_under_load", "seconds", latencies)


# ===========================================================================
# 6. CONCURRENT LOAD TEST
# ===========================================================================

@pytest.mark.asyncio
async def test_concurrent_search_load(client: httpx.AsyncClient, setup_test_data: dict):
    """
    Fire 50 concurrent search requests and measure individual latencies.
    """
    stop_ids = setup_test_data.get("stop_ids", [])
    if len(stop_ids) < 2:
        pytest.skip("Need stops for concurrent test")

    concurrency = 50
    latencies: list[float] = []
    errors = 0

    async def _single_search():
        nonlocal errors
        t0 = time.monotonic()
        try:
            resp = await client.post(f"{API_BASE}/api/v1/search/point-to-point", json={
                "start_stop_id": stop_ids[0],
                "end_stop_id": stop_ids[-1],
            }, timeout=15)
            elapsed = time.monotonic() - t0
            if resp.status_code == 200:
                latencies.append(elapsed)
            else:
                errors += 1
        except Exception:
            errors += 1

    # Warmup
    await _single_search()
    latencies.clear()

    # Concurrent burst
    await asyncio.gather(*[_single_search() for _ in range(concurrency)])

    bench.add_stats(
        "concurrent_load", "search_50_concurrent", "seconds", latencies,
        details=f"concurrency={concurrency}, errors={errors}/{concurrency}",
    )


# ===========================================================================
# 7. REDIS OPERATION LATENCY
# ===========================================================================

@pytest.mark.asyncio
async def test_redis_operation_latency():
    """
    Measure Redis SET, GET, HSET, HGETALL operations.
    """
    from app.utils.redis_client import get_redis

    try:
        r = await get_redis()
        await r.ping()
    except Exception as e:
        bench.add("redis_operations", "all", "seconds", 0.0, 0,
                  details=f"Redis unavailable: {e}")
        return

    key = f"bench_{uuid.uuid4().hex[:8]}"

    # SET
    measurements: list[float] = []
    for _ in range(WARMUP_ITERATIONS + ITERATIONS * 10):
        t0 = time.monotonic()
        await r.set(key, "benchmark_value")
        elapsed = time.monotonic() - t0
        if _ >= WARMUP_ITERATIONS:
            measurements.append(elapsed)
    bench.add_stats("redis_operations", "set", "seconds", measurements)

    # GET
    measurements = []
    for _ in range(WARMUP_ITERATIONS + ITERATIONS * 10):
        t0 = time.monotonic()
        await r.get(key)
        elapsed = time.monotonic() - t0
        if _ >= WARMUP_ITERATIONS:
            measurements.append(elapsed)
    bench.add_stats("redis_operations", "get", "seconds", measurements)

    # HSET
    measurements = []
    for _ in range(WARMUP_ITERATIONS + ITERATIONS * 10):
        t0 = time.monotonic()
        await r.hset(key, mapping={"field1": "val1", "field2": "val2", "field3": "val3"})
        elapsed = time.monotonic() - t0
        if _ >= WARMUP_ITERATIONS:
            measurements.append(elapsed)
    bench.add_stats("redis_operations", "hset", "seconds", measurements)

    # HGETALL
    measurements = []
    for _ in range(WARMUP_ITERATIONS + ITERATIONS * 10):
        t0 = time.monotonic()
        await r.hgetall(key)
        elapsed = time.monotonic() - t0
        if _ >= WARMUP_ITERATIONS:
            measurements.append(elapsed)
    bench.add_stats("redis_operations", "hgetall", "seconds", measurements)

    # Cleanup
    await r.delete(key)


# ===========================================================================
# 8. DATABASE QUERY LATENCY
# ===========================================================================

@pytest.mark.asyncio
async def test_db_query_latency():
    """
    Measure common database query times.
    """
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import text

    async with AsyncSessionLocal() as db:
        # Simple SELECT 1
        measurements: list[float] = []
        for _ in range(WARMUP_ITERATIONS + ITERATIONS * 10):
            t0 = time.monotonic()
            await db.execute(text("SELECT 1"))
            elapsed = time.monotonic() - t0
            if _ >= WARMUP_ITERATIONS:
                measurements.append(elapsed)
        bench.add_stats("database", "select_1", "seconds", measurements)

        # Count vehicles
        measurements = []
        for _ in range(WARMUP_ITERATIONS + ITERATIONS):
            t0 = time.monotonic()
            await db.execute(text("SELECT COUNT(*) FROM vehicles"))
            elapsed = time.monotonic() - t0
            if _ >= WARMUP_ITERATIONS:
                measurements.append(elapsed)
        bench.add_stats("database", "count_vehicles", "seconds", measurements)

        # Count stops
        measurements = []
        for _ in range(WARMUP_ITERATIONS + ITERATIONS):
            t0 = time.monotonic()
            await db.execute(text("SELECT COUNT(*) FROM stops"))
            elapsed = time.monotonic() - t0
            if _ >= WARMUP_ITERATIONS:
                measurements.append(elapsed)
        bench.add_stats("database", "count_stops", "seconds", measurements)

        # Join query (route + stops)
        measurements = []
        for _ in range(WARMUP_ITERATIONS + ITERATIONS):
            t0 = time.monotonic()
            await db.execute(text(
                "SELECT r.route_number, COUNT(rs.stop_id) "
                "FROM routes r LEFT JOIN route_stops rs ON r.id = rs.route_id "
                "GROUP BY r.route_number LIMIT 20"
            ))
            elapsed = time.monotonic() - t0
            if _ >= WARMUP_ITERATIONS:
                measurements.append(elapsed)
        bench.add_stats("database", "join_route_stops", "seconds", measurements)


# ===========================================================================
# 9. ML MODEL INFERENCE TIME
# ===========================================================================

@pytest.mark.asyncio
async def test_ml_inference_latency():
    """
    Measure ML model prediction latency (feature building + inference).
    """
    from app.services.ai_predictor import model_loaded, predict_eta_adjustment
    from app.services.ml_features import build_feature_dict

    if not model_loaded():
        bench.add("ml_model", "inference", "seconds", 0.0, 0,
                  details="ML model not loaded — skipped")
        return

    features = build_feature_dict(
        route_id=1, stop_id=1, stop_sequence=5, remaining_stops=4,
        distance_m=1500.0, base_dwell_time=30, peak_multiplier=1.5,
        hour=8, day_of_week=2, is_peak=1, occupancy_level=1,
        heuristic_eta=180.0,
    )

    # Warmup
    for _ in range(WARMUP_ITERATIONS):
        predict_eta_adjustment(features)

    measurements: list[float] = []
    for _ in range(ITERATIONS * 10):
        t0 = time.monotonic()
        predict_eta_adjustment(features)
        elapsed = time.monotonic() - t0
        measurements.append(elapsed)

    bench.add_stats("ml_model", "single_prediction", "seconds", measurements)


# ===========================================================================
# 10. WEBSOCKET CONNECTION TEST
# ===========================================================================

@pytest.mark.asyncio
async def test_websocket_connection_time(admin_token: str):
    """
    Measure WebSocket connection establishment time.
    """
    try:
        import websockets
    except ImportError:
        bench.add("websocket", "connection", "seconds", 0.0, 0,
                  details="websockets package not installed — skipped")
        return

    ws_url = API_BASE.replace("http://", "ws://").replace("https://", "wss://")
    measurements: list[float] = []

    for i in range(max(5, ITERATIONS // 5)):
        t0 = time.monotonic()
        try:
            async with websockets.connect(
                f"{ws_url}/api/v1/ws/live?token={admin_token}",
                ping_interval=None,
                open_timeout=10,
            ) as ws:
                elapsed = time.monotonic() - t0
                measurements.append(elapsed)
                await ws.close()
        except Exception:
            pass

    if measurements:
        bench.add_stats("websocket", "connection_establishment", "seconds", measurements)
    else:
        bench.add("websocket", "connection_establishment", "seconds", 0.0, 0,
                  details="All WebSocket connections failed")
