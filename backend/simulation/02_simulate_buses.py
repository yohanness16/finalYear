"""
BusTrack Bus Movement Simulator
Mimics real buses driving along routes in Addis Ababa.
Each bus:
  1. Driver logs in
  2. Admin starts an assignment (check-in) for driver + vehicle + route
  3. Sends GPS pings along the route with realistic pixel_count and speed (km/h)
  4. Ends the trip at the terminal

Usage:
    python 02_simulate_buses.py
    python 02_simulate_buses.py --buses 3
    python 02_simulate_buses.py --loops 5
    python 02_simulate_buses.py --sync-routes   # refresh stop geometry from API
"""

import sys
import json
import math
import time
import random
import argparse
import threading
from datetime import datetime

from api_client import APIClient
from config import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    GPS_PING_INTERVAL,
    SIMULATION_SPEED,
)
from gps_utils import haversine_m, interpolate_gps
from route_loader import fetch_route_stops


def load_state(filename: str = "simulation_state.json") -> dict:
    try:
        with open(filename) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ {filename} not found. Run 01_setup.py first.")
        sys.exit(1)


def pixel_count_for_occupancy(occupancy: int) -> int:
    """
    Simulate ESP32-CAM pixel count for given occupancy level.
    0=Low(<3000), 1=Medium(3000-7000), 2=High(>7000)
    """
    if occupancy == 0:
        return random.randint(500, 2900)
    elif occupancy == 1:
        return random.randint(3100, 6900)
    else:
        return random.randint(7100, 12000)


def get_occupancy_for_time(hour: int) -> int:
    """Realistic occupancy based on time of day (Addis Ababa patterns)."""
    if 7 <= hour <= 9:
        return random.choices([1, 2], weights=[0.3, 0.7])[0]
    elif 12 <= hour <= 13:
        return random.choices([0, 1], weights=[0.4, 0.6])[0]
    elif 16 <= hour <= 19:
        return random.choices([1, 2], weights=[0.4, 0.6])[0]
    else:
        return random.choices([0, 1], weights=[0.6, 0.4])[0]


class BusSimulator:
    def __init__(self, driver: dict, vehicle: dict, route: dict, trip_count: int = 3):
        self.driver = driver
        self.vehicle = vehicle
        self.route = route
        self.trip_count = trip_count
        self.client = APIClient(label=f"bus/{vehicle['plate_number']}")
        self.admin_client = APIClient(label=f"admin/{vehicle['plate_number']}")
        self.assignment_id = None
        self.stop = threading.Event()

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [{ts}] 🚌 {self.vehicle['plate_number']} | {msg}")

    def driver_login(self) -> bool:
        if self.client.login(self.driver["username"], self.driver["password"]):
            self.log(f"Driver {self.driver['username']} logged in")
            return True
        self.log(f"❌ Login failed for {self.driver['username']}")
        return False

    def _ensure_admin(self) -> bool:
        if self.admin_client.token:
            return True
        if self.admin_client.login(ADMIN_USERNAME, ADMIN_PASSWORD):
            return True
        self.log("❌ Admin login failed (check ADMIN_USERNAME / ADMIN_PASSWORD)")
        return False

    def _end_stale_assignments_for_vehicle(self) -> bool:
        """End active assignments for this vehicle_id (admin). Returns True if any ended."""
        if not self._ensure_admin():
            return False
        active = self.admin_client.get("/assignments/active")
        if not isinstance(active, list):
            return False
        ended = False
        for a in active:
            if a.get("vehicle_id") != self.vehicle["id"]:
                continue
            aid = a.get("id")
            if aid is None:
                continue
            r = self.admin_client.post("/assignments/end", {"assignment_id": aid})
            if r is not None:
                self.log(f"Ended stale assignment id={aid}")
                ended = True
        return ended

    def start_assignment(self) -> bool:
        if not self._ensure_admin():
            return False
        body = {
            "driver_id": self.driver["id"],
            "vehicle_id": self.vehicle["id"],
            "route_id": self.route["route_id"],
        }
        code, result = self.admin_client.post_status("/assignments/start", body)
        if code in (200, 201) and isinstance(result, dict) and result.get("id") is not None:
            self.assignment_id = int(result["id"])
            self.log(f"Assignment started (id={self.assignment_id})")
            return True
        if code == 409:
            self.log("Vehicle already has an active assignment — reconciling…")
            if self._end_stale_assignments_for_vehicle():
                code2, result2 = self.admin_client.post_status("/assignments/start", body)
                if code2 in (200, 201) and isinstance(result2, dict) and result2.get("id") is not None:
                    self.assignment_id = int(result2["id"])
                    self.log(f"Assignment started after cleanup (id={self.assignment_id})")
                    return True
            self.log("Could not clear conflicting assignment")
            return False
        detail = ""
        if isinstance(result, dict):
            detail = str(result.get("detail", result))
        elif result is not None:
            detail = str(result)[:200]
        self.log(f"❌ Start assignment failed (HTTP {code}): {detail or 'no body'}")
        return False

    def assign_vehicle_route_for_validation(self) -> bool:
        """PUT vehicle route_id so /telemetry on-route checks use the same corridor."""
        rid = self.route.get("route_id")
        vid = self.vehicle.get("id")
        if rid is None or vid is None:
            return True
        if not self._ensure_admin():
            return False
        r = self.admin_client.put(f"/vehicles/{vid}", {"route_id": rid})
        if r is None:
            self.log("⚠️ Could not set vehicle route_id (admin PUT failed)")
            return False
        self.log(f"Vehicle route_id set to {rid} for on-route validation")
        return True

    def end_assignment(self):
        if not self.assignment_id:
            return
        if self._ensure_admin():
            result = self.admin_client.post(
                "/assignments/end", {"assignment_id": self.assignment_id}
            )
            if result:
                self.log(f"Assignment {self.assignment_id} ended ✓")
        self.assignment_id = None

    def send_telemetry(self, lat: float, lon: float, pixel_count: int, speed_kmh: float):
        payload = {
            "device_id": self.vehicle["device_id"],
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "speed": round(speed_kmh, 2),
            "pixel_count": pixel_count,
            "raw_payload": {
                "plate": self.vehicle["plate_number"],
                "driver": self.driver["username"],
                "route": self.route["route_number"],
                "timestamp": datetime.utcnow().isoformat(),
            },
        }
        result = self.client.post("/telemetry", payload)
        return result is not None

    def drive_route(self, stops: list, reverse: bool = False):
        """Drive through all stops, sending GPS pings."""
        route_stops = list(reversed(stops)) if reverse else stops
        hour = datetime.now().hour
        occupancy = get_occupancy_for_time(hour)
        pixel_count = pixel_count_for_occupancy(occupancy)

        occ_label = ["Low 🟢", "Medium 🟡", "High 🔴"][occupancy]
        direction = "↩ return" if reverse else "→ forward"
        self.log(f"Starting {direction} trip | Occupancy: {occ_label}")

        sleep_time = GPS_PING_INTERVAL / SIMULATION_SPEED

        for i in range(len(route_stops) - 1):
            if self.stop.is_set():
                break

            stop_a = route_stops[i]
            stop_b = route_stops[i + 1]

            dlat = stop_b["lat"] - stop_a["lat"]
            dlon = stop_b["lon"] - stop_a["lon"]
            distance_deg = math.sqrt(dlat**2 + dlon**2)
            steps = max(3, int(distance_deg / 0.0004))

            self.log(f"  {stop_a['name']} → {stop_b['name']} ({steps} pings)")

            gps_points = interpolate_gps(
                stop_a["lat"],
                stop_a["lon"],
                stop_b["lat"],
                stop_b["lon"],
                steps=steps,
            )

            prev: tuple[float, float] | None = None
            for lat, lon in gps_points:
                if self.stop.is_set():
                    break
                if random.random() < 0.05:
                    occupancy = get_occupancy_for_time(datetime.now().hour)
                    pixel_count = pixel_count_for_occupancy(occupancy)

                speed_kmh = 0.0
                if prev is not None:
                    dist_m = haversine_m(prev[0], prev[1], lat, lon)
                    speed_kmh = (dist_m / sleep_time) * 3.6 if sleep_time > 0 else 0.0
                prev = (lat, lon)

                self.send_telemetry(lat, lon, pixel_count, speed_kmh)
                time.sleep(sleep_time)

            if not self.stop.is_set():
                dwell = stop_b.get("dwell", 30) / SIMULATION_SPEED
                dwell = min(dwell, 8)
                self.log(f"  Stopped at {stop_b['name']} (dwell {dwell:.1f}s)")
                occupancy = get_occupancy_for_time(datetime.now().hour)
                pixel_count = pixel_count_for_occupancy(occupancy)
                time.sleep(dwell)

    def run(self):
        if not self.driver_login():
            return
        if not self.start_assignment():
            return
        if not self.assign_vehicle_route_for_validation():
            self.end_assignment()
            return

        try:
            stops = self.route["stops"]
            for trip_num in range(self.trip_count):
                if self.stop.is_set():
                    break
                self.log(f"Trip {trip_num + 1}/{self.trip_count} beginning")

                self.drive_route(stops, reverse=False)

                if self.stop.is_set():
                    break

                layover = random.uniform(5, 15) / SIMULATION_SPEED
                self.log(f"Terminal layover {layover:.1f}s")
                time.sleep(layover)

                self.drive_route(stops, reverse=True)

                if self.stop.is_set():
                    break

                self.log(f"Trip {trip_num + 1} complete!")
                time.sleep(random.uniform(5, 10) / SIMULATION_SPEED)

        except KeyboardInterrupt:
            pass
        finally:
            self.end_assignment()
            self.client.close()
            self.admin_client.close()
            self.log("Done 🏁")


def run_bus(bus_sim: BusSimulator):
    bus_sim.run()


def main():
    parser = argparse.ArgumentParser(description="BusTrack Bus Movement Simulator")
    parser.add_argument("--buses", type=int, default=None, help="Number of concurrent buses")
    parser.add_argument("--loops", type=int, default=3, help="Round trips per bus")
    parser.add_argument(
        "--sync-routes",
        action="store_true",
        help="Refresh each bus route's stops from GET /routes/{id} (API is source of truth)",
    )
    args = parser.parse_args()

    state = load_state()

    drivers = [d for d in state["drivers"] if d.get("id")]
    vehicles = state["vehicles"]
    routes = list(state["routes"].values())

    print(f"\n{'═'*60}")
    print(f"  🚌 BusTrack Bus Simulator")
    print(f"{'═'*60}")
    print(f"  Drivers:  {len(drivers)}")
    print(f"  Vehicles: {len(vehicles)}")
    print(f"  Routes:   {len(routes)}")
    print(f"  Ping interval: {GPS_PING_INTERVAL}s (speed={SIMULATION_SPEED}x)")
    if args.sync_routes:
        print(f"  Route sync: enabled (GET /routes/{{id}})")

    max_buses = min(len(drivers), len(vehicles), len(routes))
    num_buses = args.buses or max_buses
    num_buses = min(num_buses, max_buses)

    print(f"  Running {num_buses} concurrent buses, {args.loops} trips each")
    print(f"\n  Press Ctrl+C to stop gracefully\n")

    assignments = []
    for i in range(num_buses):
        driver = drivers[i % len(drivers)]
        vehicle = vehicles[i % len(vehicles)]
        route = routes[i % len(routes)]

        assignments.append(
            BusSimulator(
                driver=driver,
                vehicle=vehicle,
                route=route,
                trip_count=args.loops,
            )
        )

    if args.sync_routes:
        sync_client = APIClient(label="route-sync")
        for sim in assignments:
            rid = sim.route.get("route_id")
            if not rid:
                print(f"  ⚠️ No route_id for route {sim.route.get('route_number')}, skip sync")
                continue
            stops = fetch_route_stops(sync_client, int(rid))
            if stops:
                sim.route["stops"] = stops
                print(f"  ✓ Synced stops for route {sim.route.get('route_number')} (id={rid})")
            else:
                print(f"  ✗ Failed to sync route id={rid}")
        sync_client.close()

    threads = []

    for i, sim in enumerate(assignments):
        t = threading.Thread(target=run_bus, args=(sim,), daemon=True)
        threads.append((t, sim))

    try:
        for i, (t, sim) in enumerate(threads):
            t.start()
            print(f"  🚌 Started bus {i+1}: {sim.vehicle['plate_number']} on Route {sim.route['route_number']}")
            time.sleep(random.uniform(3, 8))

        for t, sim in threads:
            t.join()

    except KeyboardInterrupt:
        print(f"\n\n  🛑 Stopping all buses...")
        for t, sim in threads:
            sim.stop.set()
        for t, sim in threads:
            t.join(timeout=5)

    print(f"\n  ✓ All buses finished.")


if __name__ == "__main__":
    main()
