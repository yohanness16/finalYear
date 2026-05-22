"""
BusTrack Bus Movement Simulator - ESP32 Gateway Edition

Real buses driving along routes, auto-provisioned via ESP32 camera gateway.
Each bus:
  1. Generates device_id based on vehicle
  2. Sends GPS pings along route with realistic bus images
  3. Backend auto-provisions vehicles and performs CV analysis
  4. Receives crowd density results in telemetry response
  5. No pre-setup needed (gateway auto-creates buses)

Usage:
    python 02_simulate_buses_esp32.py
    python 02_simulate_buses_esp32.py --buses 3
    python 02_simulate_buses_esp32.py --loops 5
    python 02_simulate_buses_esp32.py --sync-routes
"""

import sys
import json
import time
import random
import argparse
import threading
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
    """Determine occupancy level (0=empty, 1=medium, 2=crowded) from load."""
    if not capacity or capacity <= 0:
        ratio = min(max(load / 50.0, 0.0), 1.0)
    else:
        ratio = min(max(load / float(capacity), 0.0), 1.0)
    if ratio < 0.35:
        return 0
    if ratio < 0.72:
        return 1
    return 2


class ESP32BusSimulator:
    """Bus simulator using ESP32 gateway endpoint for telemetry."""

    def __init__(self, driver: dict, vehicle: dict, route: dict, trip_count: int = 3):
        self.driver = driver
        self.vehicle = vehicle
        self.route = route
        self.trip_count = trip_count
        self.client = APIClient(label=f"esp32-bus/{vehicle['plate_number']}")
        self.admin_client = APIClient(label=f"admin/{vehicle['plate_number']}")
        self.assignment_id = None
        self.stop = threading.Event()
        self.current_load = 0

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [{ts}] 🚌 {self.vehicle['plate_number']} | {msg}")

    def driver_login(self) -> bool:
        """Log in as the driver."""
        if self.client.login(self.driver["username"], self.driver["password"]):
            self.log(f"Driver {self.driver['username']} logged in")
            return True
        self.log(f"❌ Login failed for {self.driver['username']}")
        return False

    def _ensure_admin(self) -> bool:
        """Ensure admin token is available."""
        if self.admin_client.token:
            return True
        if self.admin_client.login(ADMIN_USERNAME, ADMIN_PASSWORD):
            return True
        self.log("❌ Admin login failed")
        return False

    def start_trip(self) -> bool:
        """Start a new assignment (trip) for this vehicle on the route."""
        if not self._ensure_admin():
            return False

        body = {
            "driver_id": self.driver.get("id"),
            "vehicle_id": self.vehicle.get("id"),
            "route_id": self.route.get("route_id"),
        }

        code, result = self.admin_client.post_status("/assignments/start", body)
        if code in (200, 201):
            self.assignment_id = result.get("id")
            self.log(f"✅ Trip started: {result.get('id')}")
            return True

        if code == 409:
            # Vehicle already has active assignment, try to end it
            self.log("⚠️  Vehicle has active assignment, ending it...")
            active = self.admin_client.get("/assignments/active")
            if active and isinstance(active, list):
                for assign in active:
                    if assign.get("vehicle_id") == self.vehicle.get("id"):
                        self.admin_client.post("/assignments/end", {"assignment_id": assign.get("id")})
                        time.sleep(1)

            retry_code, retry_result = self.admin_client.post_status("/assignments/start", body)
            if retry_code in (200, 201):
                self.assignment_id = retry_result.get("id")
                self.log(f"✅ Trip started (retry): {retry_result.get('id')}")
                return True

        self.log(f"❌ Trip start failed ({code}): {result}")
        return False

    def set_vehicle_route(self, route_id: int) -> bool:
        """Update vehicle.route_id to match the driven corridor."""
        if not self._ensure_admin():
            return False
        vehicle_id = self.vehicle.get("id")
        result = self.admin_client.put(f"/vehicles/{vehicle_id}", {"route_id": route_id})
        return result is not None

    def end_trip(self) -> bool:
        """End the current assignment."""
        if not self.assignment_id or not self._ensure_admin():
            return False

        result = self.admin_client.post("/assignments/end", {"assignment_id": self.assignment_id})
        if result:
            self.log(f"✅ Trip ended: {self.assignment_id}")
            self.assignment_id = None
            return True
        self.log(f"❌ Trip end failed")
        return False

    def update_occupancy_at_stop(self, stop: dict) -> None:
        """Simulate occupancy changes at each stop."""
        capacity = int(self.vehicle.get("capacity") or 60)
        if stop.get("is_terminal"):
            if stop.get("name") == self.route["stops"][0]["name"]:
                self.current_load = max(6, int(capacity * random.uniform(0.50, 0.85)))
            else:
                self.current_load = max(0, int(capacity * random.uniform(0.08, 0.28)))
            return
        delta = random.randint(-5, 9)
        self.current_load = max(0, min(capacity, self.current_load + delta))

    def send_esp32_telemetry(self, lat: float, lon: float, speed_kmh: float, stop_name: str) -> dict | None:
        """Send telemetry via ESP32 gateway endpoint with synthetic bus image.

        Returns the full response dict including CV analysis results, or None on failure.
        """
        try:
            # Determine occupancy from current load
            capacity = int(self.vehicle.get("capacity") or 60)
            occupancy_level = occupancy_level_for_load(self.current_load, capacity)

            # Generate synthetic bus image based on occupancy
            image_bytes = generate_bus_image(occupancy_level)

            # Prepare form data for multipart upload
            form_data = {
                "device_id": self.vehicle["device_id"],
                "plate_number": self.vehicle["plate_number"],
                "bus_type": self.vehicle.get("bus_type", "Anbessa"),
                "lat": str(lat),
                "lon": str(lon),
                "speed": str(round(speed_kmh, 2)),
                "bus_capacity": str(capacity),
                "occupancy_level": str(occupancy_level),
            }

            # Prepare file data
            files = {
                "image": ("bus_frame.jpg", image_bytes, "image/jpeg"),
            }

            # Send via ESP32 gateway endpoint
            result = self.client.post_multipart("/gateway/esp32/telemetry", form_data, files)

            if result:
                # Extract CV results from response
                cv = result.get("cv", {})
                occupancy_str = ["EMPTY", "MEDIUM", "CROWDED"][occupancy_level]
                cv_density = cv.get("crowd_density", "?")
                cv_people = cv.get("people_count", "?")
                cv_method = cv.get("method", "?")
                cv_conf = cv.get("confidence", "?")
                eta_status = "✓" if result.get("eta_computed") else "✗"

                self.log(
                    f"📡 {stop_name} | "
                    f"occupancy={occupancy_str} load={self.current_load}/{capacity} | "
                    f"speed={speed_kmh:.1f}km/h | "
                    f"CV: density={cv_density} people={cv_people} "
                    f"method={cv_method} conf={cv_conf} | "
                    f"ETA={eta_status} | "
                    f"vehicle_id={result.get('vehicle_id')}"
                )
                return result
            else:
                self.log(f"⚠️  No response from gateway at {stop_name}")
        except Exception as e:
            self.log(f"❌ Telemetry error: {e}")

        return None

    def drive_leg(self, stop_a: dict[str, Any], stop_b: dict[str, Any]) -> None:
        """Drive from one stop to another, sending telemetry."""
        if self.stop.is_set():
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

        self.log(
            f"  {stop_a['name']} → {stop_b['name']} | {len(route_points)} pings | "
            f"~{int(leg_distance_m)}m | {leg_seconds:.1f}s"
        )

        prev: tuple[float, float] | None = None
        for idx, (lat, lon) in enumerate(route_points):
            if self.stop.is_set():
                return

            speed_kmh = 0.0
            if prev:
                dist_m = haversine_m(prev[0], prev[1], lat, lon)
                speed_kmh = (dist_m / 1000.0) / (GPS_PING_INTERVAL / 3600.0)

            # Send telemetry and get CV results back
            self.send_esp32_telemetry(lat, lon, speed_kmh, stop_a['name'])

            prev = (lat, lon)
            route_sleep(leg_seconds / len(route_points))

        # Arrival at next stop
        self.update_occupancy_at_stop(stop_b)

        # Send a stationary ping at the stop so the frontend sees a continuous update.
        self.send_esp32_telemetry(stop_b["lat"], stop_b["lon"], 0.0, stop_b["name"])

    def run_loop(self) -> None:
        """Run one complete round trip."""
        if not self.driver_login():
            return

        stops = self.route.get("stops", [])
        if len(stops) < 2:
            self.log("❌ Route has fewer than 2 stops")
            return

        # Start trip
        if not self.start_trip():
            return

        # Update vehicle route
        self.set_vehicle_route(self.route.get("route_id"))

        # Initialize load at first stop
        self.update_occupancy_at_stop(stops[0])

        # Forward journey
        for i in range(len(stops) - 1):
            self.drive_leg(stops[i], stops[i + 1])

        # Return journey (reverse)
        for i in range(len(stops) - 1, 0, -1):
            self.drive_leg(stops[i], stops[i - 1])

        # End trip
        self.end_trip()

    def run(self) -> None:
        """Run multiple round trips."""
        for trip_num in range(self.trip_count):
            if self.stop.is_set():
                break
            self.log(f"Starting trip {trip_num + 1}/{self.trip_count}")
            self.run_loop()
            if trip_num < self.trip_count - 1:
                self.log(f"Rest between trips...")
                route_sleep(10)

        self.log("✅ All trips complete")
        self.client.close()
        self.admin_client.close()


def main():
    parser = argparse.ArgumentParser(description="Simulate buses via ESP32 gateway")
    parser.add_argument("--buses", type=int, default=2, help="Number of concurrent buses")
    parser.add_argument("--loops", type=int, default=3, help="Trips per bus")
    parser.add_argument("--sync-routes", action="store_true", help="Refresh stops from API")
    args = parser.parse_args()

    state = load_state()
    admin_client = APIClient(label="setup")
    if not admin_client.login(ADMIN_USERNAME, ADMIN_PASSWORD):
        print("❌ Admin login failed")
        sys.exit(1)

    # Sync routes if requested
    if args.sync_routes:
        print("🔄 Syncing routes from API...")
        for route_num, route_data in state.get("routes", {}).items():
            route_id = route_data.get("route_id")
            if route_id:
                stops = fetch_route_stops(admin_client, int(route_id))
                if stops:
                    state["routes"][route_num]["stops"] = stops
        with open(SCRIPT_DIR / "simulation_state.json", "w") as f:
            json.dump(state, f, indent=2)
        print("✅ Routes synced")

    # Spawn bus simulators
    threads = []
    drivers = state.get("drivers", [])
    vehicles = state.get("vehicles", [])
    routes = state.get("routes", {})

    bus_count = min(args.buses, len(drivers), len(vehicles))
    print(f"\n🚌 Starting {bus_count} buses with ESP32 gateway (up to {args.loops} trips each)...\n")

    for i in range(bus_count):
        driver = drivers[i % len(drivers)]
        vehicle = vehicles[i % len(vehicles)]
        route_num = list(routes.keys())[i % len(routes)]
        route = routes[route_num]

        sim = ESP32BusSimulator(driver, vehicle, route, trip_count=args.loops)
        thread = threading.Thread(target=sim.run, daemon=True)
        thread.start()
        threads.append((thread, sim))

    # Wait for all to finish
    try:
        for thread, sim in threads:
            thread.join()
    except KeyboardInterrupt:
        print("\n⏹️  Stopping buses...")
        for thread, sim in threads:
            sim.stop.set()
        for thread, sim in threads:
            thread.join(timeout=5)

    print("✅ Simulation complete")
    admin_client.close()


if __name__ == "__main__":
    main()
