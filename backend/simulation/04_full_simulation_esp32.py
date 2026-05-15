"""
Full system simulation using ESP32 gateway - all-in-one integration test.

The simulator does three things at once:
1. Drives buses via ESP32 gateway with real synthetic images (CV analysis)
2. Publishes live positions that passenger search reads
3. Lets passengers search, track, rate, and interact with live system

Usage:
    python 04_full_simulation_esp32.py
    python 04_full_simulation_esp32.py --buses 4 --passengers 6 --duration 300
    python 04_full_simulation_esp32.py --buses 5 --passengers 8 --duration 600
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from api_client import APIClient
from bus_image_generator import generate_bus_image
from config import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    BASE_URL,
    GPS_PING_INTERVAL,
    SIMULATION_SPEED,
)
from gps_utils import haversine_m, interpolate_gps
from route_loader import fetch_route_stops


def load_state(filename: str = "simulation_state.json") -> dict[str, Any]:
    state_path = Path(filename)
    if not state_path.is_absolute():
        state_path = SCRIPT_DIR / filename
    try:
        with open(state_path) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ {state_path} not found. Run 01_setup.py first.")
        sys.exit(1)


def route_sleep(seconds: float) -> None:
    time.sleep(max(0.1, seconds / max(SIMULATION_SPEED, 0.1)))


def occupancy_level_for_load(load: int, capacity: int | None) -> int:
    """Determine occupancy level from current load."""
    if not capacity or capacity <= 0:
        ratio = min(max(load / 50.0, 0.0), 1.0)
    else:
        ratio = min(max(load / float(capacity), 0.0), 1.0)
    if ratio < 0.35:
        return 0
    if ratio < 0.72:
        return 1
    return 2


def format_eta_snapshot(etas: dict[str, dict[str, Any]]) -> str:
    """Format ETA snapshot for display."""
    if not etas:
        return "no live ETA snapshot"
    first = sorted(
        etas.values(),
        key=lambda item: int(item.get("eta_seconds", 10**9)),
    )[0]
    return (
        f"route {first.get('route_number')} stop {first.get('stop_name')} "
        f"eta={first.get('eta_seconds')}s occupancy={first.get('occupancy_level')}"
    )


# =============================================================================
# BUS SIMULATOR (ESP32 GATEWAY)
# =============================================================================


class ESP32BusSimulator:
    """Bus simulator using ESP32 gateway telemetry."""

    def __init__(self, driver: dict, vehicle: dict, route: dict, trip_count: int = 1):
        self.driver = driver
        self.vehicle = vehicle
        self.route = route
        self.trip_count = trip_count
        self.client = APIClient(label=f"esp32-bus/{vehicle['plate_number']}")
        self.admin_client = APIClient(label=f"admin/{vehicle['plate_number']}")
        self.assignment_id = None
        self.stop_event = threading.Event()
        self.current_load = 0

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [{ts}] 🚌 {self.vehicle['plate_number']} | {msg}")

    def driver_login(self) -> bool:
        if self.client.login(self.driver["username"], self.driver["password"]):
            self.log(f"Driver logged in")
            return True
        self.log(f"❌ Login failed")
        return False

    def _ensure_admin(self) -> bool:
        if self.admin_client.token:
            return True
        if self.admin_client.login(ADMIN_USERNAME, ADMIN_PASSWORD):
            return True
        self.log("❌ Admin login failed")
        return False

    def start_trip(self) -> bool:
        if not self._ensure_admin():
            return False

        body = {
            "driver_id": self.driver.get("id"),
            "vehicle_id": self.vehicle.get("id"),
            "route_id": self.route.get("route_id"),
        }

        code, result = self.admin_client.post_status("/assignments/start", body)
        if code == 201:
            self.assignment_id = result.get("id")
            return True

        if code == 409:
            active = self.admin_client.get("/assignments/active")
            if active and isinstance(active, list):
                for assign in active:
                    if assign.get("vehicle_id") == self.vehicle.get("id"):
                        self.admin_client.post("/assignments/end", {"assignment_id": assign.get("id")})
                        time.sleep(0.5)

            retry_code, retry_result = self.admin_client.post_status("/assignments/start", body)
            if retry_code == 201:
                self.assignment_id = retry_result.get("id")
                return True

        return False

    def set_vehicle_route(self) -> bool:
        if not self._ensure_admin():
            return False
        vehicle_id = self.vehicle.get("id")
        result = self.admin_client.put(f"/vehicles/{vehicle_id}", {"route_id": self.route.get("route_id")})
        return result is not None

    def end_trip(self) -> bool:
        if not self.assignment_id or not self._ensure_admin():
            return False
        self.admin_client.post("/assignments/end", {"assignment_id": self.assignment_id})
        self.assignment_id = None
        return True

    def update_occupancy_at_stop(self, stop: dict) -> None:
        capacity = int(self.vehicle.get("capacity") or 60)
        if stop.get("is_terminal"):
            if stop.get("name") == self.route["stops"][0]["name"]:
                self.current_load = max(6, int(capacity * random.uniform(0.50, 0.85)))
            else:
                self.current_load = max(0, int(capacity * random.uniform(0.08, 0.28)))
            return
        delta = random.randint(-5, 9)
        self.current_load = max(0, min(capacity, self.current_load + delta))

    def send_esp32_telemetry(self, lat: float, lon: float, speed_kmh: float) -> dict | None:
        """Send telemetry via ESP32 gateway. Returns full response with CV data."""
        try:
            capacity = int(self.vehicle.get("capacity") or 60)
            occupancy_level = occupancy_level_for_load(self.current_load, capacity)
            image_bytes = generate_bus_image(occupancy_level)

            form_data = {
                "device_id": self.vehicle["device_id"],
                "plate_number": self.vehicle["plate_number"],
                "bus_type": self.vehicle.get("bus_type", "Anbessa"),
                "lat": str(lat),
                "lon": str(lon),
                "speed": str(round(speed_kmh, 2)),
                "bus_capacity": str(capacity),
            }

            files = {"image": ("bus_frame.jpg", image_bytes, "image/jpeg")}
            result = self.client.post_multipart("/gateway/esp32/telemetry", form_data, files)
            return result
        except Exception as e:
            self.log(f"❌ Telemetry error: {e}")
            return None

    def drive_leg(self, stop_a: dict[str, Any], stop_b: dict[str, Any]) -> None:
        if self.stop_event.is_set():
            return

        dlat = stop_b["lat"] - stop_a["lat"]
        dlon = stop_b["lon"] - stop_a["lon"]
        distance_deg = (dlat * dlat + dlon * dlon) ** 0.5
        steps = max(4, int(distance_deg / 0.00035))
        leg_distance_m = haversine_m(
            stop_a["lat"], stop_a["lon"], stop_b["lat"], stop_b["lon"]
        )
        leg_seconds = max(5.0, min(leg_distance_m / 5.0, 18.0)) / max(SIMULATION_SPEED, 0.1)

        route_points = interpolate_gps(
            stop_a["lat"],
            stop_a["lon"],
            stop_b["lat"],
            stop_b["lon"],
            steps=steps,
        )

        prev: tuple[float, float] | None = None
        for lat, lon in route_points:
            if self.stop_event.is_set():
                return

            speed_kmh = 0.0
            if prev:
                dist_m = haversine_m(prev[0], prev[1], lat, lon)
                speed_kmh = (dist_m / 1000.0) / (GPS_PING_INTERVAL / 3600.0)

            self.send_esp32_telemetry(lat, lon, speed_kmh)
            prev = (lat, lon)
            route_sleep(leg_seconds / len(route_points))

        self.update_occupancy_at_stop(stop_b)

    def run_loop(self) -> None:
        if not self.driver_login():
            return

        stops = self.route.get("stops", [])
        if len(stops) < 2:
            return

        if not self.start_trip():
            return

        self.set_vehicle_route()
        self.update_occupancy_at_stop(stops[0])

        # Forward
        for i in range(len(stops) - 1):
            self.drive_leg(stops[i], stops[i + 1])

        # Return
        for i in range(len(stops) - 1, 0, -1):
            self.drive_leg(stops[i], stops[i - 1])

        self.end_trip()

    def run(self) -> None:
        for trip_num in range(self.trip_count):
            if self.stop_event.is_set():
                break
            self.run_loop()
            if trip_num < self.trip_count - 1:
                route_sleep(5)

        self.client.close()
        self.admin_client.close()


# =============================================================================
# PASSENGER SIMULATOR
# =============================================================================


class PassengerSimulator:
    """Passenger using the app: search, track, rate."""

    def __init__(self, passenger: dict, action_count: int = 10):
        self.passenger = passenger
        self.action_count = action_count
        self.client = APIClient(label=f"passenger/{passenger['username']}")
        self.stop_event = threading.Event()

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [{ts}] 👤 {self.passenger['username']} | {msg}")

    def login(self) -> bool:
        if self.client.login(self.passenger["username"], self.passenger["password"]):
            me = self.client.get("/auth/me")
            self.log(f"✅ Logged in")
            return True
        self.log(f"❌ Login failed")
        return False

    def search_routes(self) -> bool:
        """Search for available routes."""
        try:
            routes = self.client.get("/routes?skip=0&limit=30")
            stops = self.client.get("/stops?skip=0&limit=40")
            if routes and stops:
                self.log(f"🔍 Found {len(routes)} routes, {len(stops)} stops")
                return True
        except Exception as e:
            self.log(f"Search error: {e}")
        return False

    def check_positions(self) -> bool:
        """Check live bus positions."""
        try:
            positions = self.client.get("/vehicles/positions") or {}
            if positions:
                count = len(positions)
                self.log(f"📍 Live buses: {count}")
                return True
        except Exception:
            pass
        return False

    def check_crowd_density(self) -> bool:
        """Check crowd density for a random vehicle."""
        try:
            vehicles = self.client.get("/vehicles?skip=0&limit=20") or []
            if vehicles:
                vehicle = random.choice(vehicles)
                plate = vehicle.get("plate_number")
                if plate:
                    cv = self.client.get(f"/admin/crowd/{plate}")
                    if cv:
                        density = cv.get("cv", {}).get("crowd_density", "?")
                        people = cv.get("cv", {}).get("people_count", "?")
                        self.log(f"👥 Crowd {plate}: density={density} people={people}")
                    else:
                        self.log(f"👥 No CV data for {plate}")
                    return True
        except Exception:
            pass
        return False

    def search_journey(self) -> bool:
        """Search for a journey."""
        try:
            stops = self.client.get("/stops?skip=0&limit=40")
            if not stops or len(stops) < 2:
                return False

            from_stop = random.choice(stops[:len(stops)//2])
            to_stop = random.choice(stops[len(stops)//2:])

            payload = {
                "from_stop_id": from_stop.get("id"),
                "to_stop_id": to_stop.get("id"),
            }

            result = self.client.post("/search/point-to-point", payload)
            if result:
                options = result.get("options", [])
                self.log(f"🗺️  Journey search: {len(options)} options")
                return True
        except Exception as e:
            self.log(f"Journey error: {e}")
        return False

    def save_favorite(self) -> bool:
        """Save a favorite route."""
        try:
            routes = self.client.get("/routes?skip=0&limit=30")
            if not routes:
                return False

            route = random.choice(routes)
            payload = {"route_id": route.get("id")}
            result = self.client.post("/favorites", payload)
            if result:
                self.log(f"⭐ Saved favorite route")
                return True
        except Exception:
            pass
        return False

    def rate_journey(self) -> bool:
        """Rate a completed journey."""
        try:
            rating = random.randint(1, 5)
            payload = {
                "assignment_id": random.randint(1, 100),
                "rating": rating,
                "comment": "Good service!" if rating >= 4 else "Could be better",
            }
            result = self.client.post("/ratings", payload)
            if result:
                self.log(f"⭐ Rated journey: {rating}/5")
                return True
        except Exception:
            pass
        return False

    def run(self) -> None:
        if not self.login():
            return

        actions = [
            self.search_routes,
            self.check_positions,
            self.check_crowd_density,
            self.search_journey,
            self.save_favorite,
            self.rate_journey,
        ]

        for action_num in range(self.action_count):
            if self.stop_event.is_set():
                break

            action = random.choice(actions)
            action()
            route_sleep(random.uniform(2, 5))

        self.log(f"✅ Completed {self.action_count} actions")
        self.client.close()


# =============================================================================
# MONITORING
# =============================================================================


def monitor_dashboard(admin_client: APIClient, duration: float, check_interval: int = 30) -> None:
    """Periodically check admin dashboard stats and crowd density."""
    start = time.time()
    check_count = 0

    while time.time() - start < duration:
        try:
            summary = admin_client.get("/admin/dashboard/summary")
            if summary:
                active = summary.get("active_assignments", 0)
                total_telemetry = summary.get("total_telemetry_points", 0)
                print(
                    f"  [Monitor] 📊 Dashboard: "
                    f"active_trips={active}, telemetry_points={total_telemetry}"
                )
                check_count += 1
        except Exception:
            pass

        time.sleep(check_interval)

    print(f"  [Monitor] ✅ Monitored for {int(time.time() - start)}s ({check_count} checks)")


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="Full simulation with ESP32 gateway")
    parser.add_argument("--buses", type=int, default=2, help="Concurrent buses")
    parser.add_argument("--passengers", type=int, default=3, help="Concurrent passengers")
    parser.add_argument("--duration", type=int, default=120, help="Simulation duration (seconds)")
    args = parser.parse_args()

    state = load_state()
    admin_client = APIClient(label="admin")
    if not admin_client.login(ADMIN_USERNAME, ADMIN_PASSWORD):
        print("❌ Admin login failed")
        sys.exit(1)

    threads = []

    # Spawn buses
    drivers = state.get("drivers", [])
    vehicles = state.get("vehicles", [])
    routes = state.get("routes", {})

    bus_count = min(args.buses, len(drivers), len(vehicles))
    print(f"\n{'='*70}")
    print(f"🚀 FULL SIMULATION (ESP32 GATEWAY EDITION)")
    print(f"   Buses: {bus_count} | Passengers: {args.passengers} | Duration: {args.duration}s")
    print(f"{'='*70}\n")

    print(f"🚌 Spawning {bus_count} buses...")
    for i in range(bus_count):
        driver = drivers[i % len(drivers)]
        vehicle = vehicles[i % len(vehicles)]
        route_num = list(routes.keys())[i % len(routes)]
        route = routes[route_num]

        sim = ESP32BusSimulator(driver, vehicle, route, trip_count=1)
        thread = threading.Thread(target=sim.run, daemon=True)
        thread.start()
        threads.append((thread, sim))

    # Spawn passengers
    passengers = state.get("passengers", [])
    passenger_count = min(args.passengers, len(passengers))

    print(f"👤 Spawning {passenger_count} passengers...\n")
    for i in range(passenger_count):
        passenger = passengers[i % len(passengers)]
        sim = PassengerSimulator(passenger, action_count=random.randint(5, 15))
        thread = threading.Thread(target=sim.run, daemon=True)
        thread.start()
        threads.append((thread, sim))

    # Monitor dashboard in background
    monitor_thread = threading.Thread(
        target=monitor_dashboard, args=(admin_client, args.duration), daemon=True
    )
    monitor_thread.start()

    # Wait for duration
    try:
        time.sleep(args.duration)
    except KeyboardInterrupt:
        print("\n⏹️  Stopping simulation...")

    print(f"\n✅ Simulation complete!")
    admin_client.close()


if __name__ == "__main__":
    main()
