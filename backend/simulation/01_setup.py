"""
BusTrack Setup Script
Creates all users, routes, stops, and vehicles via API.
Run this ONCE before starting the simulation.

Usage:
    python 01_setup.py
    python 01_setup.py --reset   # skips existing items silently
"""

import argparse
import sys
import json
import time
from pathlib import Path
from config import (
    ADMIN_USERNAME,
    ADMIN_PASSWORD,
    DRIVERS,
    PASSENGERS,
    ROUTES,
    VEHICLES,
    expand_fleet,
)
from api_client import APIClient


SCRIPT_DIR = Path(__file__).resolve().parent


def banner(text: str):
    print(f"\n{'═'*60}")
    print(f"  {text}")
    print(f"{'═'*60}")


def step(text: str):
    print(f"\n▶ {text}")


def ok(text: str):
    print(f"  ✓ {text}")


def skip(text: str):
    print(f"  ─ {text} (already exists)")


def fail(text: str):
    print(f"  ✗ {text}")


def setup_users(admin: APIClient, drivers: list[dict]) -> dict:
    """Create drivers and passengers. Returns {username: user_data}."""
    banner("STEP 1 — Creating Users")
    created = {}

    step("Creating drivers...")
    for d in drivers:
        result = admin.create_admin_user(
            username=d["username"],
            email=d["email"],
            password=d["password"],
            role="driver",
        )
        if result:
            if result.get("already_exists"):
                skip(d["username"])
            else:
                ok(f"Driver: {d['username']}")
            created[d["username"]] = {**d, "role": "driver", "id": result.get("id")}
        else:
            fail(f"Driver: {d['username']}")
        time.sleep(0.1)

    step("Creating passengers...")
    for p in PASSENGERS:
        result = admin.register(
            username=p["username"],
            email=p["email"],
            password=p["password"],
        )
        if result:
            if result.get("already_exists"):
                skip(p["username"])
            else:
                ok(f"Passenger: {p['username']}")
            created[p["username"]] = {**p, "role": "passenger", "id": result.get("id")}
        else:
            fail(f"Passenger: {p['username']}")
        time.sleep(0.1)

    return created


def setup_vehicles(admin: APIClient, vehicles: list[dict]) -> dict:
    """Register buses. Returns {plate_number: vehicle_data}."""
    banner("STEP 2 — Registering Vehicles")
    registered = {}

    for v in vehicles:
        payload = {
            "plate_number": v["plate_number"],
            "device_id": v["device_id"],
            "bus_type": v["bus_type"],
            "capacity": v["capacity"],
            "is_active": True,
        }
        result = admin.post("/vehicles", payload)
        if result:
            ok(f"Bus {v['plate_number']} ({v['bus_type']}, cap {v['capacity']})")
            registered[v["plate_number"]] = result
        else:
            # Might already exist — fetch list to confirm
            skip(v["plate_number"])
            registered[v["plate_number"]] = v
        time.sleep(0.15)

    return registered


def setup_routes(admin: APIClient) -> dict:
    """Create routes and stops. Returns {route_number: {route, stops}}."""
    banner("STEP 3 — Creating Routes & Stops")
    route_map = {}

    # First pass: create all stops (they're shared)
    step("Creating stops...")
    stop_map = {}  # name -> stop_id
    all_stop_names = set()
    for r in ROUTES:
        for s in r["stops"]:
            all_stop_names.add(s["name"])

    # Build unique stops
    unique_stops = {}
    for r in ROUTES:
        for s in r["stops"]:
            key = s["name"]
            if key not in unique_stops:
                unique_stops[key] = s

    for name, stop_data in unique_stops.items():
        payload = {
            "name": stop_data["name"],
            "lat": stop_data["lat"],
            "lon": stop_data["lon"],
            "base_dwell_time": stop_data["dwell"],
            "is_terminal": stop_data["is_terminal"],
            "peak_multiplier": stop_data["peak_mult"],
        }
        result = admin.post("/stops", payload)
        if result and result.get("id"):
            ok(f"Stop: {name} (id={result['id']})")
            stop_map[name] = result["id"]
        else:
            # Already exists — look it up from GET /stops
            skip(name)
        time.sleep(0.1)

    # Fetch all stops to fill in missing IDs
    if len(stop_map) < len(unique_stops):
        step("Fetching existing stops...")
        existing = admin.get("/stops?skip=0&limit=500")
        if existing and isinstance(existing, list):
            for s in existing:
                if s.get("name") in unique_stops and s["name"] not in stop_map:
                    stop_map[s["name"]] = s["id"]
                    ok(f"Found existing stop: {s['name']} (id={s['id']})")

    # Second pass: create routes
    step("Creating routes...")
    for r in ROUTES:
        stop_sequence = []
        for idx, stop in enumerate(r["stops"]):
            sid = stop_map.get(stop["name"])
            if sid:
                stop_sequence.append({"stop_id": sid, "sequence_order": idx + 1})
            else:
                fail(f"Stop not found for route {r['route_number']}: {stop['name']}")

        payload = {
            "route_number": r["route_number"],
            "direction": "forward",
            "name": r["name"],
            "origin": r["origin"],
            "destination": r["destination"],
            "stops": stop_sequence,
        }
        result = admin.post("/routes", payload)
        if result and result.get("id"):
            ok(f"Route {r['route_number']}: {r['name']} (id={result['id']})")
            route_map[r["route_number"]] = {
                "route": result,
                "stops": [{"name": s["name"], "id": stop_map.get(s["name"]), **s} for s in r["stops"]],
                "stop_ids": [stop_map.get(s["name"]) for s in r["stops"]],
            }
        else:
            skip(f"Route {r['route_number']}: {r['name']}")
            # Try to get the existing route
            existing_routes = admin.get("/routes?skip=0&limit=100")
            if existing_routes and isinstance(existing_routes, list):
                for er in existing_routes:
                    if er.get("route_number") == r["route_number"] and er.get("direction") == "forward":
                        route_map[r["route_number"]] = {
                            "route": er,
                            "stops": [{"name": s["name"], "id": stop_map.get(s["name"]), **s} for s in r["stops"]],
                            "stop_ids": [stop_map.get(s["name"]) for s in r["stops"]],
                        }
        time.sleep(0.15)

    return route_map


def fetch_user_ids(admin: APIClient, drivers: list[dict]) -> dict:
    """Fetch driver user IDs by logging in as each driver."""
    banner("STEP 4 — Fetching User IDs")
    user_ids = {}

    for d in drivers:
        client = APIClient(label=d["username"])
        if client.login(d["username"], d["password"]):
            me = client.get("/auth/me")
            if me:
                user_ids[d["username"]] = me["id"]
                ok(f"{d['username']} → id={me['id']}")
        client.close()
        time.sleep(0.1)

    return user_ids


def save_state(data: dict, filename: str = "simulation_state.json"):
    """Save setup state to JSON for use by simulation scripts."""
    state_path = Path(filename)
    if not state_path.is_absolute():
        state_path = SCRIPT_DIR / state_path
    with open(state_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\n  💾 State saved to {state_path}")


def main():
    parser = argparse.ArgumentParser(description="BusTrack simulation setup (users, vehicles, routes)")
    parser.add_argument(
        "--extra-fleet",
        type=int,
        default=0,
        help="Create this many additional driver+vehicle pairs (sim_sim_200+, AA-SIM-00200+)",
    )
    args = parser.parse_args()

    extra_d, extra_v = expand_fleet(args.extra_fleet)
    drivers_run = list(DRIVERS) + extra_d
    vehicles_run = list(VEHICLES) + extra_v

    banner("BusTrack Simulation Setup")
    print(f"  API: {__import__('config').BASE_URL}")
    print(f"  Admin: {ADMIN_USERNAME}")
    if args.extra_fleet:
        print(f"  Extra fleet: +{args.extra_fleet} drivers and +{args.extra_fleet} vehicles")

    # Admin login
    admin = APIClient(label="admin")
    print(f"\n▶ Logging in as admin...")
    if not admin.login(ADMIN_USERNAME, ADMIN_PASSWORD):
        print("\n❌ Admin login failed. Is the backend running?")
        print(f"   URL: {__import__('config').BASE_URL}")
        print(f"   Create admin first: see backend/docs/IMPLEMENTATION.md")
        sys.exit(1)
    ok(f"Admin logged in")

    # Run setup steps
    users = setup_users(admin, drivers_run)
    vehicles = setup_vehicles(admin, vehicles_run)
    routes = setup_routes(admin)
    driver_ids = fetch_user_ids(admin, drivers_run)

    # Fetch all vehicle IDs
    step("Fetching vehicle IDs...")
    all_vehicles = admin.get("/vehicles?skip=0&limit=100") or []
    vehicle_map = {}
    if isinstance(all_vehicles, list):
        for v in all_vehicles:
            vehicle_map[v["plate_number"]] = v["id"]
            ok(f"{v['plate_number']} → id={v['id']}")

    # Build state
    state = {
        "drivers": [
            {
                "username": d["username"],
                "email": d["email"],
                "password": d["password"],
                "id": driver_ids.get(d["username"]),
            }
            for d in drivers_run
        ],
        "passengers": [
            {
                "username": p["username"],
                "email": p["email"],
                "password": p["password"],
            }
            for p in PASSENGERS
        ],
        "vehicles": [
            {
                "plate_number": v["plate_number"],
                "device_id": v["device_id"],
                "id": vehicle_map.get(v["plate_number"]),
            }
            for v in vehicles_run
            if v["plate_number"] in vehicle_map
        ],
        "routes": {
            rn: {
                "route_id": rd["route"].get("id"),
                "route_number": rn,
                "name": rd["route"].get("name"),
                "stops": [
                    {
                        "name": s["name"],
                        "id": s.get("id"),
                        "lat": s["lat"],
                        "lon": s["lon"],
                        "is_terminal": s["is_terminal"],
                    }
                    for s in rd["stops"]
                ],
            }
            for rn, rd in routes.items()
        }
    }

    save_state(state)

    banner("Setup Complete!")
    print(f"  ✓ {len([d for d in state['drivers'] if d['id']])} drivers ready")
    print(f"  ✓ {len(state['passengers'])} passengers ready")
    print(f"  ✓ {len(state['vehicles'])} vehicles registered")
    print(f"  ✓ {len(state['routes'])} routes configured")
    print(f"\n  Next: Run  python 02_simulate_buses_esp32.py")

    admin.close()


if __name__ == "__main__":
    main()
