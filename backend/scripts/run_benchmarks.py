#!/usr/bin/env python3
"""
Standalone Benchmark Runner for BusTrack
==========================================

Runs all performance benchmarks and writes results to CSV.
Can be executed directly without pytest.

Usage:
  # Run against local backend (default)
  python scripts/run_benchmarks.py

  # Run against deployed backend
  API_BASE=https://bustrack.dpdns.org python scripts/run_benchmarks.py

  # Quick mode (fewer iterations)
  BENCHMARK_ITERATIONS=10 python scripts/run_benchmarks.py

Output:
  storage/benchmark_results.csv
  storage/benchmark_results.json
  storage/benchmark_report.txt
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

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx")
    sys.exit(1)

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    print("WARNING: cv2/numpy not installed — CV benchmarks will be skipped")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin123456")
ITERATIONS = int(os.environ.get("BENCHMARK_ITERATIONS", "30"))
WARMUP = 5

RESULTS_DIR = Path(__file__).resolve().parents[1] / "storage"
CSV_PATH = RESULTS_DIR / "benchmark_results.csv"
JSON_PATH = RESULTS_DIR / "benchmark_results.json"
REPORT_PATH = RESULTS_DIR / "benchmark_report.txt"

RESULTS_DIR.mkdir(parents=True, exist_ok=True)


class BenchmarkCollector:
    def __init__(self):
        self.rows: list[dict[str, Any]] = []

    def add_stats(self, category, metric, unit, measurements, details=""):
        if not measurements:
            return
        mean = statistics.mean(measurements)
        median = statistics.median(measurements)
        p95 = sorted(measurements)[int(len(measurements) * 0.95)]
        mn = min(measurements)
        mx = max(measurements)
        std = statistics.stdev(measurements) if len(measurements) >= 2 else 0

        row_base = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "category": category,
            "unit": unit,
            "iterations": len(measurements),
            "details": details,
            "api_base": API_BASE,
        }
        for suffix, val in [("mean", mean), ("median", median), ("p95", p95),
                             ("min", mn), ("max", mx), ("stddev", std)]:
            row = dict(row_base)
            row["metric"] = f"{metric}_{suffix}"
            row["value"] = round(val, 6)
            self.rows.append(row)

    def add_single(self, category, metric, unit, value, details=""):
        self.rows.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "category": category,
            "metric": metric,
            "unit": unit,
            "value": round(value, 6),
            "iterations": 1,
            "details": details,
            "api_base": API_BASE,
        })

    def write(self):
        # CSV
        fieldnames = ["timestamp", "category", "metric", "unit", "value",
                       "iterations", "details", "api_base"]
        write_header = not CSV_PATH.exists()
        with open(CSV_PATH, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            writer.writerows(self.rows)
        print(f"\n📄 CSV: {CSV_PATH} ({len(self.rows)} rows)")

        # JSON
        existing = []
        if JSON_PATH.exists():
            try:
                existing = json.loads(JSON_PATH.read_text())
            except Exception:
                pass
        existing.extend(self.rows)
        JSON_PATH.write_text(json.dumps(existing, indent=2, default=str))
        print(f"📄 JSON: {JSON_PATH} ({len(existing)} total rows)")

        # Text report
        self._write_report()

    def _write_report(self):
        lines = []
        lines.append("=" * 70)
        lines.append("BusTrack Performance Benchmark Report")
        lines.append("=" * 70)
        lines.append(f"API Base: {API_BASE}")
        lines.append(f"Time: {datetime.now(timezone.utc).isoformat()}")
        lines.append(f"Total Measurements: {len(self.rows)}")
        lines.append("")

        cats: dict[str, list[dict]] = {}
        for row in self.rows:
            cat = row.get("category", "unknown")
            cats.setdefault(cat, []).append(row)

        for cat, rows in cats.items():
            lines.append(f"--- {cat.upper().replace('_', ' ')} ---")
            metrics: dict[str, dict[str, str]] = {}
            for row in rows:
                m = row["metric"]
                base = m.replace("_mean", "").replace("_median", "").replace("_p95", "").replace("_min", "").replace("_max", "").replace("_stddev", "")
                metrics.setdefault(base, {})[m] = f"{row['value']} {row.get('unit', '')}"

            for base, vals in metrics.items():
                parts = [f"{k.split('_')[-1]}={v}" for k, v in sorted(vals.items())]
                lines.append(f"  {base}: {', '.join(parts)}")
            lines.append("")

        lines.append("=" * 70)
        REPORT_PATH.write_text("\n".join(lines))
        print(f"📄 Report: {REPORT_PATH}")


collector = BenchmarkCollector()


async def measure(client, method, path, **kwargs):
    t0 = time.monotonic()
    if method == "POST":
        resp = await client.post(f"{API_BASE}{path}", **kwargs)
    else:
        resp = await client.get(f"{API_BASE}{path}", **kwargs)
    return time.monotonic() - t0, resp


async def benchmark_request(client, category, name, method, path, **kwargs):
    """Run a request benchmark and collect stats."""
    # Warmup
    for _ in range(WARMUP):
        try:
            await measure(client, method, path, **kwargs)
        except Exception:
            pass

    measurements = []
    errors = 0
    for i in range(ITERATIONS):
        try:
            elapsed, resp = await measure(client, method, path, **kwargs)
            if resp.status_code < 400:
                measurements.append(elapsed)
            else:
                errors += 1
        except Exception:
            errors += 1

    collector.add_stats(category, name, "seconds", measurements,
                        details=f"errors={errors}/{ITERATIONS}")
    mean_ms = statistics.mean(measurements) * 1000 if measurements else 0
    print(f"  ✓ {name}: {mean_ms:.1f}ms avg ({len(measurements)} ok, {errors} errors)")
    return measurements


async def setup_test_data(client, token):
    """Create test stops, route, vehicle, driver, assignment."""
    headers = {"Authorization": f"Bearer {token}"}
    data: dict[str, Any] = {}

    stop_names = [
        ("Bench A", 9.020, 38.730),
        ("Bench B", 9.030, 38.740),
        ("Bench C", 9.040, 38.750),
        ("Bench D", 9.050, 38.760),
    ]
    stop_ids = []
    for name, lat, lon in stop_names:
        resp = await client.post(f"{API_BASE}/api/v1/routes/stops", headers=headers,
                                  json={"name": name, "lat": lat, "lon": lon,
                                        "base_dwell_time": 30, "is_terminal": False,
                                        "peak_multiplier": 1.0})
        if resp.status_code == 200:
            stop_ids.append(resp.json()["id"])
        else:
            r = await client.get(f"{API_BASE}/api/v1/routes/stops?limit=200", headers=headers)
            if r.status_code == 200:
                for s in r.json():
                    if s["name"] == name:
                        stop_ids.append(s["id"])
                        break
    data["stop_ids"] = stop_ids

    route_stops = [{"stop_id": sid, "sequence_order": i + 1} for i, sid in enumerate(stop_ids)]
    resp = await client.post(f"{API_BASE}/api/v1/routes", headers=headers,
                              json={"route_number": f"BENCH-{uuid.uuid4().hex[:6]}",
                                    "name": "Benchmark Route", "origin": stop_names[0][0],
                                    "destination": stop_names[-1][0], "stops": route_stops})
    if resp.status_code == 200:
        data["route_id"] = resp.json()["id"]
    else:
        r = await client.get(f"{API_BASE}/api/v1/routes?limit=200", headers=headers)
        if r.status_code == 200 and r.json():
            data["route_id"] = r.json()[0]["id"]

    plate = f"BENCH-{uuid.uuid4().hex[:6]}"
    dev_id = f"BENCH-DEV-{uuid.uuid4().hex[:8]}"
    resp = await client.post(f"{API_BASE}/api/v1/vehicles", headers=headers,
                              json={"plate_number": plate, "device_id": dev_id,
                                    "bus_type": "Benchmark", "capacity": 52, "is_active": True})
    if resp.status_code == 200:
        data["vehicle_id"] = resp.json()["id"]
        data["device_id"] = dev_id
        await client.put(f"{API_BASE}/api/v1/vehicles/{data['vehicle_id']}",
                         headers=headers, json={"route_id": data["route_id"]})

    resp = await client.post(f"{API_BASE}/api/v1/admin/users/create", headers=headers,
                              json={"username": f"bench_{uuid.uuid4().hex[:8]}",
                                    "email": f"bench_{uuid.uuid4().hex[:8]}@test.local",
                                    "password": "bench123456", "role": "driver"})
    if resp.status_code == 200:
        data["driver_id"] = resp.json()["id"]

    if all(k in data for k in ("driver_id", "vehicle_id", "route_id")):
        resp = await client.post(f"{API_BASE}/api/v1/assignments/start", headers=headers,
                                  json={"driver_id": data["driver_id"],
                                        "vehicle_id": data["vehicle_id"],
                                        "route_id": data["route_id"]})
        if resp.status_code == 200:
            data["assignment_id"] = resp.json()["id"]

    return data


async def main():
    print("=" * 70)
    print("BusTrack Performance Benchmark Suite")
    print("=" * 70)
    print(f"API Base: {API_BASE}")
    print(f"Iterations: {ITERATIONS} (+ {WARMUP} warmup)")
    print("")

    async with httpx.AsyncClient() as client:
        # ── Login ──
        print("[1/8] Authentication...")
        resp = await client.post(f"{API_BASE}/api/v1/auth/login",
                                  json={"username": ADMIN_USER, "password": ADMIN_PASS})
        if resp.status_code != 200:
            print(f"  ✗ Login failed: {resp.status_code} {resp.text[:200]}")
            print("  Set ADMIN_USER and ADMIN_PASS env vars.")
            return
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print(f"  ✓ Logged in")

        # ── Setup test data ──
        print("\n[2/8] Setting up test data...")
        test_data = await setup_test_data(client, token)
        print(f"  ✓ Created {len(test_data.get('stop_ids', []))} stops, route, vehicle, driver")

        # ── 1. API Latency ──
        print("\n[3/8] API Latency Benchmarks...")
        await benchmark_request(client, "api_latency", "health", "GET", "/health")
        await benchmark_request(client, "api_latency", "auth_login", "POST", "/api/v1/auth/login",
                                json={"username": ADMIN_USER, "password": ADMIN_PASS})
        await benchmark_request(client, "api_latency", "vehicles_list", "GET",
                                "/api/v1/vehicles?limit=100", headers=headers)
        await benchmark_request(client, "api_latency", "routes_list", "GET",
                                "/api/v1/routes?limit=200", headers=headers)
        await benchmark_request(client, "api_latency", "stops_list", "GET",
                                "/api/v1/routes/stops?limit=200", headers=headers)

        stop_ids = test_data.get("stop_ids", [])
        if len(stop_ids) >= 2:
            await benchmark_request(client, "api_latency", "search_point_to_point", "POST",
                                    "/api/v1/search/point-to-point",
                                    json={"start_stop_id": stop_ids[0], "end_stop_id": stop_ids[-1]})
            await benchmark_request(client, "api_latency", "search_journey", "POST",
                                    "/api/v1/search/journey",
                                    json={"start_lat": 9.020, "start_lon": 38.730,
                                          "end_lat": 9.050, "end_lon": 38.760})
        else:
            print("  ⚠ Skipping search benchmarks (not enough stops)")

        device_id = test_data.get("device_id")
        if device_id:
            await benchmark_request(client, "api_latency", "telemetry_gps", "POST",
                                    "/api/v1/telemetry",
                                    json={"device_id": device_id, "lat": 9.032, "lon": 38.752,
                                          "speed": 25.0, "pixel_count": 3000})
        else:
            print("  ⚠ Skipping telemetry benchmark (no device_id)")

        await benchmark_request(client, "api_latency", "admin_analytics", "GET",
                                "/api/v1/admin/dashboard/analytics?days=7", headers=headers,
                                timeout=15)

        # ── 2. Telemetry Pipeline ──
        print("\n[4/8] Telemetry Pipeline Latency...")
        if device_id:
            pipe_measurements = []
            for i in range(WARMUP + ITERATIONS):
                t0 = time.monotonic()
                resp = await client.post(f"{API_BASE}/api/v1/telemetry",
                                         json={"device_id": device_id,
                                               "lat": 9.032 + i * 0.0001,
                                               "lon": 38.752 + i * 0.0001,
                                               "speed": 25.0, "pixel_count": 3000})
                elapsed = time.monotonic() - t0
                if i >= WARMUP and resp.status_code == 200:
                    pipe_measurements.append(elapsed)
            collector.add_stats("telemetry_pipeline", "full_ingestion", "seconds",
                                pipe_measurements)
            if pipe_measurements:
                print(f"  ✓ telemetry_pipeline: {statistics.mean(pipe_measurements)*1000:.1f}ms avg")
        else:
            print("  ⚠ Skipped (no device_id)")

        # ── 3. ETA Computation ──
        print("\n[5/8] ETA Computation...")
        from app.services.eta_calc import calculate_eta_heuristic
        from app.services.route_eta import estimate_route_stop_eta_payloads
        from unittest.mock import MagicMock

        # Heuristic
        measurements = []
        for i in range(WARMUP + ITERATIONS * 10):
            t0 = time.monotonic()
            calculate_eta_heuristic(9.03, 38.74, 9.05, 38.76, num_stops=5)
            elapsed = time.monotonic() - t0
            if i >= WARMUP:
                measurements.append(elapsed)
        collector.add_stats("eta_computation", "heuristic_single", "seconds", measurements)
        print(f"  ✓ heuristic: {statistics.mean(measurements)*1000:.3f}ms avg")

        # Route-stop payloads
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
        for i in range(WARMUP + ITERATIONS):
            t0 = time.monotonic()
            estimate_route_stop_eta_payloads(
                9.03, 38.74, 30.0, 1, "TEST", 1, mock_stops,
                plate_number="TEST-001", vehicle_id=1)
            elapsed = time.monotonic() - t0
            if i >= WARMUP:
                measurements.append(elapsed)
        collector.add_stats("eta_computation", "route_stop_10_stops", "seconds", measurements)
        print(f"  ✓ route_stop_10: {statistics.mean(measurements)*1000:.1f}ms avg")

        # ML ETA
        from app.services.ai_predictor import model_loaded
        if model_loaded():
            from app.services.eta_engine import get_final_eta
            measurements = []
            for i in range(WARMUP + ITERATIONS):
                t0 = time.monotonic()
                get_final_eta(9.03, 38.74, 9.05, 38.76, num_stops=5, stop_id=1,
                              occupancy_level=1)
                elapsed = time.monotonic() - t0
                if i >= WARMUP:
                    measurements.append(elapsed)
            collector.add_stats("eta_computation", "ml_eta", "seconds", measurements)
            print(f"  ✓ ml_eta: {statistics.mean(measurements)*1000:.1f}ms avg")
        else:
            print("  ⚠ ML model not loaded — skipped ML ETA benchmark")

        # ── 4. Computer Vision ──
        print("\n[6/8] Computer Vision Inference...")
        if HAS_CV2:
            frame = np.random.randint(50, 200, (480, 640, 3), dtype=np.uint8)
            _, buf = cv2.imencode(".jpg", frame)
            image_bytes = buf.tobytes()

            from app.services.yolo_detector import YoloDetector
            detector = YoloDetector()
            for _ in range(3):
                await detector.detect(image_bytes, bus_capacity=40)

            measurements = []
            for _ in range(max(5, ITERATIONS // 3)):
                t0 = time.monotonic()
                result = await detector.detect(image_bytes, bus_capacity=40)
                elapsed = time.monotonic() - t0
                measurements.append(elapsed)
            method = result.get("method", "unknown")
            collector.add_stats("computer_vision", "yolo_inference", "seconds", measurements,
                                details=f"method={method}")
            print(f"  ✓ yolo: {statistics.mean(measurements)*1000:.1f}ms avg (method={method})")

            from app.services.cv_engine import analyze_bus_density_from_image
            measurements_hog = []
            for _ in range(max(5, ITERATIONS // 3)):
                t0 = time.monotonic()
                analyze_bus_density_from_image(image_bytes, bus_capacity=40)
                elapsed = time.monotonic() - t0
                measurements_hog.append(elapsed)
            collector.add_stats("computer_vision", "hog_fallback", "seconds", measurements_hog)
            print(f"  ✓ hog: {statistics.mean(measurements_hog)*1000:.1f}ms avg")
        else:
            print("  ⚠ cv2 not available — skipped CV benchmarks")

        # ── 5. Throughput ──
        print("\n[7/8] Throughput Test (10 seconds)...")
        if device_id:
            duration = 10
            success = 0
            errors = 0
            end_time = time.monotonic() + duration
            i = 0
            while time.monotonic() < end_time:
                try:
                    resp = await client.post(f"{API_BASE}/api/v1/telemetry",
                                             json={"device_id": device_id,
                                                   "lat": 9.032 + (i % 100) * 0.0001,
                                                   "lon": 38.752 + (i % 100) * 0.0001,
                                                   "speed": 25.0, "pixel_count": 3000},
                                             timeout=5)
                    if resp.status_code == 200:
                        success += 1
                    else:
                        errors += 1
                except Exception:
                    errors += 1
                i += 1
            throughput = success / duration
            collector.add_single("throughput", "telemetry_req_per_sec", "req/s", throughput,
                                 details=f"duration={duration}s, errors={errors}")
            print(f"  ✓ throughput: {throughput:.1f} req/s ({success} ok, {errors} errors)")
        else:
            print("  ⚠ Skipped (no device_id)")

        # ── 6. Redis & DB ──
        print("\n[8/8] Redis & Database Latency...")

        # Redis
        try:
            from app.utils.redis_client import get_redis
            r = await get_redis()
            await r.ping()
            key = f"bench_{uuid.uuid4().hex[:8]}"

            measurements = []
            for i in range(WARMUP + ITERATIONS * 10):
                t0 = time.monotonic()
                await r.set(key, "val")
                elapsed = time.monotonic() - t0
                if i >= WARMUP:
                    measurements.append(elapsed)
            collector.add_stats("redis", "set", "seconds", measurements)

            measurements = []
            for i in range(WARMUP + ITERATIONS * 10):
                t0 = time.monotonic()
                await r.get(key)
                elapsed = time.monotonic() - t0
                if i >= WARMUP:
                    measurements.append(elapsed)
            collector.add_stats("redis", "get", "seconds", measurements)
            await r.delete(key)
            print(f"  ✓ redis set: {statistics.mean(measurements)*1000:.3f}ms avg")
        except Exception as e:
            print(f"  ⚠ Redis unavailable: {e}")

        # Database
        try:
            from app.db.session import AsyncSessionLocal
            from sqlalchemy import text
            async with AsyncSessionLocal() as db:
                measurements = []
                for i in range(WARMUP + ITERATIONS):
                    t0 = time.monotonic()
                    await db.execute(text("SELECT COUNT(*) FROM vehicles"))
                    elapsed = time.monotonic() - t0
                    if i >= WARMUP:
                        measurements.append(elapsed)
                collector.add_stats("database", "count_vehicles", "seconds", measurements)
                print(f"  ✓ db count_vehicles: {statistics.mean(measurements)*1000:.3f}ms avg")
        except Exception as e:
            print(f"  ⚠ DB unavailable: {e}")

    # ── Write results ──
    collector.write()
    print("\n✅ Benchmark complete!")


if __name__ == "__main__":
    asyncio.run(main())
