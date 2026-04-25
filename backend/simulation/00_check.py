"""
BusTrack Simulation Health Check
Verifies the API is reachable and the simulation state is valid.

Usage:
    python 00_check.py
"""

import sys
import json
from api_client import APIClient
from config import BASE_URL, ADMIN_USERNAME, ADMIN_PASSWORD


def ok(label: str, val=None):
    suffix = f" → {val}" if val is not None else ""
    print(f"  ✓ {label}{suffix}")


def fail(label: str, hint: str = ""):
    print(f"  ✗ {label}")
    if hint:
        print(f"    ↳ {hint}")


def warn(label: str):
    print(f"  ⚠ {label}")


def main():
    print(f"\n{'═'*60}")
    print(f"  BusTrack Simulation Health Check")
    print(f"{'═'*60}")
    print(f"  API: {BASE_URL}\n")

    all_good = True

    # ── 1. API reachable ───────────────────────────────────────────────────────
    print("▶ Checking API...")
    client = APIClient(label="check")
    try:
        import httpx
        r = httpx.get(BASE_URL.replace("/api/v1", "/docs"), timeout=5)
        ok(f"API reachable ({r.status_code})")
    except Exception as e:
        fail("API not reachable", f"Is the backend running? ({e})")
        all_good = False
        print("\n  ❌ Start backend with: uvicorn app.main:app --reload")
        sys.exit(1)

    # ── 2. Admin login ─────────────────────────────────────────────────────────
    print("\n▶ Checking admin login...")
    if client.login(ADMIN_USERNAME, ADMIN_PASSWORD):
        me = client.get("/auth/me")
        ok(f"Admin login", f"username={me.get('username')}, role={me.get('role')}")
    else:
        fail("Admin login failed", f"Check ADMIN_USERNAME/ADMIN_PASSWORD in config.py")
        all_good = False

    # ── 3. Check simulation state ──────────────────────────────────────────────
    print("\n▶ Checking simulation_state.json...")
    try:
        with open("simulation_state.json") as f:
            state = json.load(f)

        drivers = [d for d in state.get("drivers", []) if d.get("id")]
        vehicles = state.get("vehicles", [])
        routes = state.get("routes", {})

        ok(f"State file found")
        ok(f"Drivers with IDs", len(drivers))
        ok(f"Vehicles", len(vehicles))
        ok(f"Routes", len(routes))

        if len(drivers) == 0:
            warn("No driver IDs found — run 01_setup.py first")
        if len(vehicles) == 0:
            warn("No vehicles found — run 01_setup.py first")

    except FileNotFoundError:
        warn("simulation_state.json not found — run 01_setup.py first")

    # ── 4. Check routes in DB ──────────────────────────────────────────────────
    print("\n▶ Checking routes in database...")
    routes_db = client.get("/routes?skip=0&limit=100")
    if routes_db and isinstance(routes_db, list):
        ok(f"Routes in DB", len(routes_db))
        for r in routes_db[:5]:
            print(f"     Route {r['route_number']}: {r.get('name', 'n/a')}")
    else:
        warn("No routes found — run 01_setup.py")

    # ── 5. Check vehicles in DB ────────────────────────────────────────────────
    print("\n▶ Checking vehicles in database...")
    vehicles_db = client.get("/vehicles?skip=0&limit=100")
    if vehicles_db and isinstance(vehicles_db, list):
        ok(f"Vehicles in DB", len(vehicles_db))
    else:
        warn("No vehicles found — run 01_setup.py")

    # ── 6. Check stops in DB ───────────────────────────────────────────────────
    print("\n▶ Checking stops in database...")
    stops_db = client.get("/stops?skip=0&limit=100")
    if stops_db and isinstance(stops_db, list):
        ok(f"Stops in DB", len(stops_db))
    else:
        warn("No stops found — run 01_setup.py")

    client.close()

    print(f"\n{'═'*60}")
    if all_good:
        print(f"  ✅ All checks passed! Ready to simulate.")
        print(f"\n  Run order:")
        print(f"    1. python 01_setup.py          # one time")
        print(f"    2. python 02_simulate_buses.py  # in terminal A")
        print(f"    3. python 03_simulate_passengers.py  # in terminal B")
        print(f"    OR: python 04_full_simulation.py     # both together")
    else:
        print(f"  ❌ Some checks failed. Fix issues above then retry.")
    print(f"{'═'*60}\n")


if __name__ == "__main__":
    main()
