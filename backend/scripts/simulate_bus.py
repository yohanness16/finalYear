#!/usr/bin/env python3
"""
Bus Route Simulation — Kality ↔ Meskel Square (Addis Ababa)

Simulates a bus traveling along a real Addis Ababa corridor:
  Kality Terminal → Mekanisa → Mexico → Stadium → Meskel Square

Usage:
  python scripts/simulate_bus.py                  # full simulation (setup + drive)
  python scripts/simulate_bus.py --drive-only     # skip setup, just drive
  python scripts/simulate_bus.py --status         # check current simulation state
  python scripts/simulate_bus.py --cleanup        # end assignment, reset

Requirements:
  pip install httpx tqdm
  Backend running at localhost:8000 (or set API_BASE env var)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import sys
import time
from typing import Any

try:
    import httpx
except ImportError:
    print("pip install httpx")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
TELEMETRY_ENDPOINT = f"{API_BASE}/api/v1/telemetry"
PING_INTERVAL = 5  # seconds between telemetry pings
SIM_SPEED_KMH = 30  # average bus speed km/h

# Admin credentials (must exist in DB)
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin123456")

# ---------------------------------------------------------------------------
# Route definition: Kality ↔ Meskel Square, Addis Ababa
# GPS coordinates are approximate for real landmarks along the corridor.
# ---------------------------------------------------------------------------
ROUTE_NUMBER = "121-ROUTE"
ROUTE_NAME = "Kality ↔ Meskel Square"
ROUTE_ORIGIN = "Kality Terminal"
ROUTE_DESTINATION = "Meskel Square"

# Stops with real-ish Addis Ababa GPS coordinates (lat, lon)
# Ordered from Kality (southwest) to Meskel Square (northcentral)
STOPS: list[dict[str, Any]] = [
    {"name": "Kality Terminal",  "lat": 8.9520, "lon": 38.7460, "is_terminal": True,  "dwell_time": 60, "peak_mult": 1.5},
    {"name": "Mekanisa",          "lat": 8.9620, "lon": 38.7520, "is_terminal": False, "dwell_time": 30, "peak_mult": 1.5},
    {"name": "Mekanisa Junction", "lat": 8.9710, "lon": 38.7580, "is_terminal": False, "dwell_time": 25, "peak_mult": 1.4},
    {"name": "Mexico Square",     "lat": 8.9820, "lon": 38.7650, "is_terminal": False, "dwell_time": 35, "peak_mult": 1.8},
    {"name": "Lideta",           "lat": 8.9920, "lon": 38.7680, "is_terminal": False, "dwell_time": 30, "peak_mult": 1.6},
    {"name": "Stadium",           "lat": 8.9980, "lon": 38.7720, "is_terminal": False, "dwell_time": 25, "peak_mult": 1.4},
    {"name": "Churchill Avenue",  "lat": 9.0050, "lon": 38.7640, "is_terminal": False, "dwell_time": 30, "peak_mult": 1.5},
    {"name": "Meskel Square",     "lat": 9.0130, "lon": 38.7590, "is_terminal": True,  "dwell_time": 60, "peak_mult": 1.5},
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def interpolate_point(
    lat1: float, lon1: float, lat2: float, lon2: float, fraction: float
) -> tuple[float, float]:
    """Linear interpolation between two GPS points."""
    return (lat1 + (lat2 - lat1) * fraction, lon1 + (lon2 - lon1) * fraction)


def build_route_waypoints(stops: list[dict], points_per_segment: int = 20) -> list[tuple[float, float]]:
    """
    Build a smooth list of GPS waypoints along the route.
    points_per_segment determines resolution between consecutive stops.
    """
    waypoints: list[tuple[float, float]] = []
    for i in range(len(stops) - 1):
        s1, s2 = stops[i], stops[i + 1]
        for j in range(points_per_segment):
            frac = j / points_per_segment
            lat, lon = interpolate_point(s1["lat"], s1["lon"], s2["lat"], s2["lon"], frac)
            waypoints.append((lat, lon))
    waypoints.append((stops[-1]["lat"], stops[-1]["lon"]))
    return waypoints


def compute_eta_to_stops(
    lat: float, lon: float, speed_kmh: float, stops: list[dict], stops_data: list[dict]
) -> list[dict]:
    """Compute ETA from current position to each stop ahead."""
    results = []
    # Find nearest stop index
    nearest_idx = 0
    nearest_dist = float("inf")
    for i, s in enumerate(stops_data):
        d = haversine_meters(lat, lon, s["lat"], s["lon"])
        if d < nearest_dist:
            nearest_dist = d
            nearest_idx = i

    speed_ms = max(speed_kmh / 3.6, 6.0)
    for idx in range(len(stops_data)):
        s = stops_data[idx]
        dist_m = haversine_meters(lat, lon, s["lat"], s["lon"])
        travel_s = dist_m / speed_ms
        dwell_s = 0
        if idx >= nearest_idx:
            for seg in stops_data[nearest_idx + 1: idx + 1]:
                dwell_s += seg.get("dwell_time", 30) * seg.get("peak_mult", 1.0)
        results.append({
            "stop_name": s["name"],
            "distance_m": round(dist_m),
            "eta_seconds": round(travel_s + dwell_s),
            "ahead": idx >= nearest_idx,
        })
    return results


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

async def login_admin(client: httpx.AsyncClient) -> str:
    """Login admin and return JWT token."""
    resp = await client.post(f"{API_BASE}/api/v1/auth/login", json={
        "username": ADMIN_USER, "password": ADMIN_PASS
    })
    if resp.status_code != 200:
        print(f"  ✗ Admin login failed: {resp.status_code} {resp.text}")
        sys.exit(1)
    token = resp.json()["access_token"]
    print(f"  ✓ Admin logged in (token: {token[:20]}...)")
    return token


async def ensure_stops(client: httpx.AsyncClient, token: str) -> list[int]:
    """Create stops if they don't exist. Returns list of stop IDs."""
    headers = {"Authorization": f"Bearer {token}"}

    # Get existing stops
    resp = await client.get(f"{API_BASE}/api/v1/routes/stops?limit=200", headers=headers)
    existing_stops = {}
    if resp.status_code == 200:
        for s in resp.json():
            existing_stops[s["name"]] = s["id"]

    stop_ids = []
    for stop_def in STOPS:
        if stop_def["name"] in existing_stops:
            stop_ids.append(existing_stops[stop_def["name"]])
            print(f"  ✓ Stop exists: {stop_def['name']} (id={existing_stops[stop_def['name']]})")
        else:
            resp = await client.post(f"{API_BASE}/api/v1/routes/stops", headers=headers, json={
                "name": stop_def["name"],
                "lat": stop_def["lat"],
                "lon": stop_def["lon"],
                "base_dwell_time": stop_def["dwell_time"],
                "is_terminal": stop_def["is_terminal"],
                "peak_multiplier": stop_def["peak_mult"],
            })
            if resp.status_code == 200:
                sid = resp.json()["id"]
                stop_ids.append(sid)
                print(f"  ✓ Created stop: {stop_def['name']} (id={sid})")
            else:
                print(f"  ✗ Failed to create stop {stop_def['name']}: {resp.status_code} {resp.text}")
                sys.exit(1)
    return stop_ids


async def ensure_route(
    client: httpx.AsyncClient, token: str, stop_ids: list[int]
) -> int:
    """Create the route if it doesn't exist. Returns route ID."""
    headers = {"Authorization": f"Bearer {token}"}

    # Get existing routes
    resp = await client.get(f"{API_BASE}/api/v1/routes?limit=200", headers=headers)
    if resp.status_code == 200:
        for r in resp.json():
            if r.get("route_number") == ROUTE_NUMBER:
                print(f"  ✓ Route exists: {ROUTE_NUMBER} (id={r['id']})")
                return r["id"]

    # Create route with route_stops
    route_stops = [
        {"stop_id": sid, "sequence_order": i + 1}
        for i, sid in enumerate(stop_ids)
    ]
    resp = await client.post(f"{API_BASE}/api/v1/routes", headers=headers, json={
        "route_number": ROUTE_NUMBER,
        "name": ROUTE_NAME,
        "origin": ROUTE_ORIGIN,
        "destination": ROUTE_DESTINATION,
        "stops": route_stops,
    })
    if resp.status_code == 200:
        rid = resp.json()["id"]
        print(f"  ✓ Created route: {ROUTE_NAME} (id={rid})")
        return rid
    else:
        print(f"  ✗ Failed to create route: {resp.status_code} {resp.text}")
        sys.exit(1)


async def ensure_vehicle(client: httpx.AsyncClient, token: str, route_id: int) -> dict:
    """Create the simulated vehicle. Returns vehicle dict."""
    headers = {"Authorization": f"Bearer {token}"}
    plate = "SIM-BUS-001"
    device_id = "SIM-DEVICE-001"

    # Check if vehicle exists
    resp = await client.get(
        f"{API_BASE}/api/v1/vehicles?limit=100", headers=headers
    )
    if resp.status_code == 200:
        for v in resp.json():
            if v.get("plate_number") == plate:
                v_update = await client.put(
                    f"{API_BASE}/api/v1/vehicles/{v['id']}",
                    headers=headers,
                    json={"route_id": route_id},
                )
                print(f"  ✓ Vehicle exists: {plate} (id={v['id']}, route_id={route_id})")
                return v_update.json() if v_update.status_code == 200 else v

    resp = await client.post(f"{API_BASE}/api/v1/vehicles", headers=headers, json={
        "plate_number": plate,
        "device_id": device_id,
        "bus_type": "Simulator",
        "capacity": 52,
        "is_active": True,
    })
    if resp.status_code == 200:
        vid = resp.json()["id"]
        # Assign route
        v_update = await client.put(
            f"{API_BASE}/api/v1/vehicles/{vid}",
            headers=headers,
            json={"route_id": route_id},
        )
        print(f"  ✓ Created vehicle: {plate} (id={vid}, route_id={route_id})")
        return v_update.json() if v_update.status_code == 200 else resp.json()
    else:
        print(f"  ✗ Failed to create vehicle: {resp.status_code} {resp.text}")
        sys.exit(1)


async def ensure_driver(client: httpx.AsyncClient, token: str) -> int:
    """Create the simulated driver. Returns driver user ID."""
    headers = {"Authorization": f"Bearer {token}"}
    username = "sim_driver"
    email = "sim@bustrack.local"

    # Check if driver exists
    resp = await client.get(f"{API_BASE}/api/v1/admin/users/list", headers=headers)
    if resp.status_code == 200:
        for u in resp.json():
            if u.get("username") == username:
                print(f"  ✓ Driver exists: {username} (id={u['id']})")
                return u["id"]

    resp = await client.post(f"{API_BASE}/api/v1/admin/users/create", headers=headers, json={
        "username": username,
        "email": email,
        "password": "driver123456",
        "role": "driver",
    })
    if resp.status_code == 200:
        did = resp.json()["id"]
        print(f"  ✓ Created driver: {username} (id={did})")
        return did
    else:
        print(f"  ✗ Failed to create driver: {resp.status_code} {resp.text}")
        sys.exit(1)


async def ensure_assignment(
    client: httpx.AsyncClient, token: str, driver_id: int, vehicle_id: int, route_id: int
) -> int:
    """Start an assignment if none active for the vehicle. Returns assignment ID."""
    headers = {"Authorization": f"Bearer {token}"}

    # Check if already active
    resp = await client.get(f"{API_BASE}/api/v1/assignments/active", headers=headers)
    if resp.status_code == 200:
        for a in resp.json():
            if a.get("vehicle_id") == vehicle_id and a.get("status") == "active":
                print(f"  ✓ Active assignment exists (id={a['id']})")
                return a["id"]

    resp = await client.post(f"{API_BASE}/api/v1/assignments/start", headers=headers, json={
        "driver_id": driver_id,
        "vehicle_id": vehicle_id,
        "route_id": route_id,
    })
    if resp.status_code == 200:
        aid = resp.json()["id"]
        print(f"  ✓ Started assignment (id={aid}, driver={driver_id}, vehicle={vehicle_id}, route={route_id})")
        return aid
    else:
        print(f"  ✗ Failed to start assignment: {resp.status_code} {resp.text}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Telemetry simulation
# ---------------------------------------------------------------------------

async def send_telemetry(
    client: httpx.AsyncClient,
    device_id: str,
    lat: float,
    lon: float,
    speed: float,
    ping_num: int,
) -> dict | None:
    """Send a single telemetry ping to the backend."""
    payload = {
        "device_id": device_id,
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "speed": round(speed, 1),
        "pixel_count": random.randint(1500, 8000),
        "raw_payload": {
            "cv": {
                "occupancy_level": random.choice([0, 0, 1, 1, 1, 2]),
                "confidence": round(random.uniform(0.7, 0.95), 2),
                "method": random.choice(["background_subtraction", "hog", "blob"]),
            }
        },
    }
    try:
        resp = await client.post(TELEMETRY_ENDPOINT, json=payload, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 429:
            print(f"  ⚠ Rate limited, backing off...")
            await asyncio.sleep(2)
            return None
        else:
            print(f"  ✗ Telemetry rejected: {resp.status_code} {resp.text[:200]}")
            return None
    except httpx.TimeoutException:
        print(f"  ✗ Timeout sending telemetry")
        return None
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return None


def print_progress_bar(
    current: int, total: int, lat: float, lon: float, speed: float,
    stop_name: str, eta_info: list[dict], width: int = 40,
):
    """Print a nice progress bar with live info."""
    frac = current / max(total - 1, 1)
    filled = int(width * frac)
    bar = "█" * filled + "░" * (width - filled)

    # Find next stop ahead
    next_stop = None
    for s in eta_info:
        if s["ahead"] and s["distance_m"] > 50 and next_stop is None:
            next_stop = s
        elif s["ahead"] and s["distance_m"] <= 50 and s["stop_name"] != stop_name:
            stop_name = s["stop_name"]

    eta_str = ""
    if next_stop:
        mins = next_stop["eta_seconds"] // 60
        secs = next_stop["eta_seconds"] % 60
        eta_str = f"  → {next_stop['stop_name']} in {mins}m {secs}s ({next_stop['distance_m']}m)"

    print(
        f"\r  [{bar}] {frac*100:5.1f}%  "
        f"({lat:.5f}, {lon:.5f})  "
        f"⚡ {speed:.0f} km/h  "
        f"📍 {stop_name}{eta_str:<50}",
        end="", flush=True,
    )


async def drive_route(
    client: httpx.AsyncClient,
    vehicle: dict,
    driver_id: int,
    route_id: int,
    stop_at_each: bool = True,
):
    """Simulate driving the full route."""
    device_id = vehicle["device_id"]
    plate = vehicle["plate_number"]
    total_stops = len(STOPS)

    waypoints = build_route_waypoints(STOPS, points_per_segment=30)
    eta_info = compute_eta_to_stops(
        waypoints[0][0], waypoints[0][1], SIM_SPEED_KMH, STOPS, STOPS
    )

    print(f"\n{'='*80}")
    print(f"  🚌 Starting simulation: {plate} (driver={driver_id}, route={route_id})")
    print(f"  Route: {ROUTE_NAME} ({ROUTE_NUMBER})")
    print(f"  Stops: {total_stops} | Waypoints: {len(waypoints)} | Speed: ~{SIM_SPEED_KMH} km/h")
    print(f"  ETA to destination: {eta_info[-1]['eta_seconds'] // 60}m {eta_info[-1]['eta_seconds'] % 60}s")
    print(f"{'='*80}\n")

    ping_count = 0
    last_stop_reached = ""

    for i, (lat, lon) in enumerate(waypoints):
        # Add slight GPS jitter
        lat += random.gauss(0, 0.00003)
        lon += random.gauss(0, 0.00003)

        # Compute current speed (slower near stops)
        speed = SIM_SPEED_KMH + random.gauss(0, 3)
        speed = max(5, min(50, speed))

        # Find nearest stop
        nearest_stop = min(STOPS, key=lambda s: haversine_meters(lat, lon, s["lat"], s["lon"]))
        nearest_dist = haversine_meters(lat, lon, nearest_stop["lat"], nearest_stop["lon"])

        # Recompute ETAs
        eta_info = compute_eta_to_stops(lat, lon, speed, STOPS, STOPS)

        print_progress_bar(i, len(waypoints), lat, lon, speed, nearest_stop["name"], eta_info)

        # Send telemetry
        result = await send_telemetry(client, device_id, lat, lon, speed, ping_count)
        ping_count += 1

        # Print response info occasionally
        if result and i % 15 == 0:
            occ = result.get("occupancy_level", "?")
            status_str = result.get("status", "?")
            # Print on a new line so we don't mess up the progress bar
            print(f"\n    ↳ backend: status={status_str}, occupancy={occ}")

        # Simulate stopping at bus stops
        if stop_at_each and nearest_dist < 80 and last_stop_reached != nearest_stop["name"]:
            last_stop_reached = nearest_stop["name"]
            dwell = nearest_stop.get("dwell_time", 30)
            print(f"\n\n  🛑 Arrived at: {nearest_stop['name']} (dwelling {dwell}s)")
            # Send a few pings while stopped
            for _ in range(min(3, dwell // PING_INTERVAL)):
                await send_telemetry(client, device_id, lat, lon, 0.0, ping_count)
                ping_count += 1
                print(f"  ... stopped at {nearest_stop['name']} ({ping_count} pings total)")
                await asyncio.sleep(PING_INTERVAL)
            print(f"  🚏 Departing {nearest_stop['name']}...\n")
            # Print ETA summary after departing
            eta_info = compute_eta_to_stops(lat, lon, SIM_SPEED_KMH, STOPS, STOPS)
            for es in eta_info:
                if es["ahead"]:
                    mins = es["eta_seconds"] // 60
                    secs = es["eta_seconds"] % 60
                    print(f"    → {es['stop_name']}: {mins}m {secs}s ({es['distance_m']}m)")
            print()
            print_progress_bar(i, len(waypoints), lat, lon, speed, nearest_stop["name"], eta_info)

        await asyncio.sleep(PING_INTERVAL)

    print(f"\n\n{'='*80}")
    print(f"  🏁 ROUTE COMPLETE — Total telemetry pings sent: {ping_count}")
    print(f"  Vehicle {plate} arrived at {STOPS[-1]['name']}")
    print(f"{'='*80}\n")


# ---------------------------------------------------------------------------
# Status & cleanup
# ---------------------------------------------------------------------------

async def check_status(client: httpx.AsyncClient, token: str):
    """Check current simulation state."""
    headers = {"Authorization": f"Bearer {token}"}

    print("\n  ── Simulation Status ──\n")

    # Check vehicle
    resp = await client.get(f"{API_BASE}/api/v1/vehicles?limit=100", headers=headers)
    if resp.status_code == 200:
        vehicles = [v for v in resp.json() if v.get("plate_number") == "SIM-BUS-001"]
        if vehicles:
            v = vehicles[0]
            print(f"  Vehicle: {v['plate_number']} (id={v['id']}, route={v.get('route_id')})")
            if v.get("last_lat"):
                print(f"  Last position: ({v['last_lat']:.5f}, {v['last_lon']:.5f})")
                print(f"  Speed: {v.get('speed', 0)} km/h")
        else:
            print("  No simulated vehicle found")

    # Check active assignments
    resp = await client.get(f"{API_BASE}/api/v1/assignments/active", headers=headers)
    if resp.status_code == 200:
        for a in resp.json():
            if a.get("status") == "active":
                print(f"  Assignment #{a['id']}: driver={a['driver_id']}, vehicle={a['vehicle_id']}, route={a['route_id']}")

    # Check live positions
    resp = await client.get(f"{API_BASE}/api/v1/vehicles/positions", headers=headers)
    if resp.status_code == 200:
        positions = resp.json()
        if isinstance(positions, dict):
            positions = positions.get("positions", {})
        if isinstance(positions, dict):
            sim_pos = [p for p in positions.values() if str(p.get("plate_number")) == "SIM-BUS-001"]
            if sim_pos:
                p = sim_pos[0]
                print(f"  Live: ({p.get('lat')}, {p.get('lon')}) speed={p.get('speed')} occ={p.get('occupancy_level')}")

    print()


async def cleanup(client: httpx.AsyncClient, token: str):
    """End active assignment."""
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.get(f"{API_BASE}/api/v1/assignments/active", headers=headers)
    if resp.status_code == 200:
        for a in resp.json():
            if a.get("vehicle_id"):
                # Check if it's our sim vehicle
                v_resp = await client.get(f"{API_BASE}/api/v1/vehicles/{a['vehicle_id']}", headers=headers)
                if v_resp.status_code == 200 and v_resp.json().get("plate_number") == "SIM-BUS-001":
                    end_resp = await client.post(
                        f"{API_BASE}/api/v1/assignments/end",
                        headers=headers,
                        json={"assignment_id": a["id"]},
                    )
                    if end_resp.status_code == 200:
                        print(f"  ✓ Ended assignment #{a['id']}")
    print("  Done.")


# ---------------------------------------------------------------------------
# Full setup
# ---------------------------------------------------------------------------

async def full_setup(client: httpx.AsyncClient) -> tuple[dict, int, int]:
    """Run complete setup: login, stops, route, vehicle, driver, assignment."""
    print("\n  ── Setting up simulation ──\n")

    token = await login_admin(client)

    print("\n  Creating stops...")
    stop_ids = await ensure_stops(client, token)

    print("\n  Creating route...")
    route_id = await ensure_route(client, token, stop_ids)

    print("\n  Creating vehicle...")
    vehicle = await ensure_vehicle(client, token, route_id)

    print("\n  Creating driver...")
    driver_id = await ensure_driver(client, token)

    print("\n  Starting assignment...")
    assignment_id = await ensure_assignment(client, token, driver_id, vehicle["id"], route_id)

    print(f"\n  ── Setup complete ──")
    print(f"    Vehicle:  {vehicle['plate_number']} (id={vehicle['id']})")
    print(f"    Driver:   sim_driver (id={driver_id})")
    print(f"    Route:    {ROUTE_NUMBER} (id={route_id})")
    print(f"    Assign:   #{assignment_id}")
    print()

    return vehicle, driver_id, route_id


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="Bus Route Simulation")
    parser.add_argument("--drive-only", action="store_true", help="Skip setup, just drive")
    parser.add_argument("--status", action="store_true", help="Check simulation state")
    parser.add_argument("--cleanup", action="store_true", help="End assignment")
    parser.add_argument("--no-stop", action="store_true", help="Don't simulate stops at bus stops")
    parser.add_argument("--speed", type=int, default=SIM_SPEED_KMH, help="Average speed km/h")
    parser.add_argument("--interval", type=int, default=PING_INTERVAL, help="Ping interval seconds")
    parser.add_argument("--rounds", type=int, default=1, help="Number of route rounds")
    args = parser.parse_args()

    global SIM_SPEED_KMH, PING_INTERVAL
    SIM_SPEED_KMH = args.speed
    PING_INTERVAL = args.interval

    async with httpx.AsyncClient() as client:
        if args.status:
            token = await login_admin(client)
            await check_status(client, token)
            return

        if args.cleanup:
            token = await login_admin(client)
            await cleanup(client, token)
            return

        if args.drive_only:
            token = await login_admin(client)
            # Fetch existing vehicle
            headers = {"Authorization": f"Bearer {token}"}
            resp = await client.get(f"{API_BASE}/api/v1/vehicles?limit=100", headers=headers)
            vehicle = None
            driver_id = None
            route_id = None
            for v in resp.json():
                if v.get("plate_number") == "SIM-BUS-001":
                    vehicle = v
                    route_id = v.get("route_id")
                    break
            if not vehicle:
                print("  No sim vehicle found. Run full setup first.")
                sys.exit(1)
            # Get active assignment
            resp = await client.get(f"{API_BASE}/api/v1/assignments/active", headers=headers)
            for a in resp.json():
                if a.get("vehicle_id") == vehicle["id"] and a.get("status") == "active":
                    driver_id = a["driver_id"]
                    break
            if not driver_id:
                print("  No active assignment. Run full setup first.")
                sys.exit(1)
        else:
            vehicle, driver_id, route_id = await full_setup(client)

        # Drive rounds
        for round_num in range(args.rounds):
            if args.rounds > 1:
                print(f"\n  ═══ Round {round_num + 1}/{args.rounds} ═══\n")
            await drive_route(
                client, vehicle, driver_id, route_id,
                stop_at_each=not args.no_stop,
            )


if __name__ == "__main__":
    asyncio.run(main())
