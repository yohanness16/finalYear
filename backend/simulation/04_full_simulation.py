"""Full system simulation built around the live backend API.

The simulator does three things at once:
1. Drives buses along real route stops and sends telemetry.
2. Publishes live ETA snapshots that the passenger search endpoint reads.
3. Lets passengers search routes, inspect live buses, and act like mobile users.
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
        with open(state_path) as handle:
            return json.load(handle)
    except FileNotFoundError:
        print(f"❌ {state_path} not found. Run 01_setup.py first.")
        sys.exit(1)


def route_sleep(seconds: float) -> None:
    time.sleep(max(0.1, seconds / max(SIMULATION_SPEED, 0.1)))


def occupancy_level_for_load(load: int, capacity: int | None) -> int:
    if not capacity or capacity <= 0:
        ratio = min(max(load / 50.0, 0.0), 1.0)
    else:
        ratio = min(max(load / float(capacity), 0.0), 1.0)
    if ratio < 0.35:
        return 0
    if ratio < 0.72:
        return 1
    return 2


def pixel_count_for_occupancy(occupancy: int) -> int:
    if occupancy == 0:
        return random.randint(900, 2800)
    if occupancy == 1:
        return random.randint(3200, 6500)
    return random.randint(7200, 11800)


def format_eta_snapshot(etas: dict[str, dict[str, Any]]) -> str:
    if not etas:
        return "no live ETA snapshot"
    first = sorted(
        etas.values(),
        key=lambda item: int(item.get("eta_seconds", 10**9)),
    )[0]
    return (
        f"route {first.get('route_number')} stop {first.get('stop_name')} "
        f"eta={first.get('eta_seconds')}s density={first.get('occupancy_level')}"
    )


def load_routes_from_api(client: APIClient, route_state: dict[str, Any]) -> dict[str, Any]:
    synced: dict[str, Any] = {}
    for route_number, data in route_state.items():
        route_id = data.get("route_id")
        if not route_id:
            synced[route_number] = data
            continue
        route_detail = client.get(f"/routes/{route_id}")
        if isinstance(route_detail, dict):
            stops = fetch_route_stops(client, int(route_id)) or data.get("stops", [])
            synced[route_number] = {
                **data,
                "name": route_detail.get("name", data.get("name")),
                "stops": stops,
            }
        else:
            synced[route_number] = data
    return synced


@dataclass
class BusWorkItem:
    driver: dict[str, Any]
    vehicle: dict[str, Any]
    route: dict[str, Any]


class BusSimulation:
    def __init__(self, item: BusWorkItem, trip_count: int = 3):
        self.item = item
        self.trip_count = trip_count
        self.client = APIClient(label=f"bus/{item.vehicle['plate_number']}")
        self.admin_client = APIClient(label=f"admin/{item.vehicle['plate_number']}")
        self.assignment_id: int | None = None
        self.stop = threading.Event()
        capacity = int(item.vehicle.get("capacity") or 60)
        self.current_load = max(4, min(capacity // 3, random.randint(6, 18)))

    @property
    def vehicle(self) -> dict[str, Any]:
        return self.item.vehicle

    @property
    def driver(self) -> dict[str, Any]:
        return self.item.driver

    @property
    def route(self) -> dict[str, Any]:
        return self.item.route

    def log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [{ts}] 🚌 {self.vehicle['plate_number']} | {message}")

    def _ensure_admin(self) -> bool:
        if self.admin_client.token:
            return True
        if self.admin_client.login(ADMIN_USERNAME, ADMIN_PASSWORD):
            return True
        self.log("❌ Admin login failed")
        return False

    def _end_stale_assignments_for_vehicle(self) -> bool:
        if not self._ensure_admin():
            return False
        active = self.admin_client.get("/assignments/active")
        if not isinstance(active, list):
            return False
        ended = False
        for item in active:
            if item.get("vehicle_id") != self.vehicle.get("id"):
                continue
            assignment_id = item.get("id")
            if assignment_id is None:
                continue
            result = self.admin_client.post(
                "/assignments/end",
                {"assignment_id": assignment_id},
            )
            if result is not None:
                ended = True
                self.log(f"Ended stale assignment id={assignment_id}")
        return ended

    def driver_login(self) -> bool:
        if self.client.login(self.driver["username"], self.driver["password"]):
            self.log(f"Driver {self.driver['username']} logged in")
            return True
        self.log(f"❌ Login failed for {self.driver['username']}")
        return False

    def start_assignment(self) -> bool:
        if not self._ensure_admin():
            return False
        body = {
            "driver_id": self.driver["id"],
            "vehicle_id": self.vehicle["id"],
            "route_id": self.route["route_id"],
        }
        code, result = self.admin_client.post_status("/assignments/start", body)
        if code in (200, 201) and isinstance(result, dict):
            self.assignment_id = int(result["id"])
            self.log(f"Assignment started (id={self.assignment_id})")
            return True
        if code == 409:
            self.log("Vehicle already has an active assignment - attempting cleanup")
            if self._end_stale_assignments_for_vehicle():
                retry_code, retry_result = self.admin_client.post_status("/assignments/start", body)
                if retry_code in (200, 201) and isinstance(retry_result, dict):
                    self.assignment_id = int(retry_result["id"])
                    self.log(f"Assignment started after cleanup (id={self.assignment_id})")
                    return True
        detail = result.get("detail") if isinstance(result, dict) else result
        self.log(f"❌ Start assignment failed (HTTP {code}): {detail or 'no body'}")
        return False

    def assign_vehicle_route_for_validation(self) -> bool:
        route_id = self.route.get("route_id")
        vehicle_id = self.vehicle.get("id")
        if route_id is None or vehicle_id is None:
            return True
        if not self._ensure_admin():
            return False
        result = self.admin_client.put(f"/vehicles/{vehicle_id}", {"route_id": route_id})
        if result is None:
            self.log("⚠️ Could not set vehicle route_id for validation")
            return False
        self.log(f"Vehicle route_id set to {route_id}")
        return True

    def end_assignment(self) -> None:
        if not self.assignment_id:
            return
        if self._ensure_admin():
            self.admin_client.post("/assignments/end", {"assignment_id": self.assignment_id})
        self.assignment_id = None

    def occupancy_snapshot(self) -> tuple[int, int]:
        capacity = int(self.vehicle.get("capacity") or 60)
        occupancy = occupancy_level_for_load(self.current_load, capacity)
        return occupancy, pixel_count_for_occupancy(occupancy)

    def adjust_load_at_stop(self, stop: dict[str, Any]) -> None:
        capacity = int(self.vehicle.get("capacity") or 60)
        if stop.get("is_terminal"):
            if stop.get("name") == self.route["stops"][0]["name"]:
                self.current_load = max(6, int(capacity * random.uniform(0.50, 0.85)))
            else:
                self.current_load = max(0, int(capacity * random.uniform(0.08, 0.28)))
            return
        delta = random.randint(-5, 9)
        self.current_load = max(0, min(capacity, self.current_load + delta))

    def send_telemetry(self, lat: float, lon: float, pixel_count: int, speed_kmh: float, stop_name: str) -> None:
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
                "stop": stop_name,
                "load": self.current_load,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }
        self.client.post("/telemetry", payload)

    def drive_leg(self, stop_a: dict[str, Any], stop_b: dict[str, Any]) -> None:
        if self.stop.is_set():
            return
        dlat = stop_b["lat"] - stop_a["lat"]
        dlon = stop_b["lon"] - stop_a["lon"]
        distance_deg = (dlat * dlat + dlon * dlon) ** 0.5
        steps = max(4, int(distance_deg / 0.00035))
        leg_distance_m = haversine_m(stop_a["lat"], stop_a["lon"], stop_b["lat"], stop_b["lon"])
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
            f"~{int(leg_distance_m)}m"
        )
        prev: tuple[float, float] | None = None
        for lat, lon in route_points:
            if self.stop.is_set():
                return
            occupancy, pixel_count = self.occupancy_snapshot()
            if prev is not None:
                distance_m = haversine_m(prev[0], prev[1], lat, lon)
                speed_kmh = (distance_m / leg_seconds) * 3.6 if leg_seconds > 0 else 0.0
            else:
                speed_kmh = 0.0
            prev = (lat, lon)
            self.send_telemetry(lat, lon, pixel_count, speed_kmh, stop_a["name"])
            route_sleep(GPS_PING_INTERVAL)

    def dwell_at_stop(self, stop: dict[str, Any]) -> None:
        self.adjust_load_at_stop(stop)
        occupancy, pixel_count = self.occupancy_snapshot()
        dwell_seconds = (stop.get("dwell") or 30) * (1.0 + occupancy * 0.15)
        dwell_seconds = min(dwell_seconds / max(SIMULATION_SPEED, 0.1), 10.0)
        self.log(
            f"  Stop {stop['name']} | load={self.current_load} occupancy={occupancy} "
            f"dwell={dwell_seconds:.1f}s"
        )
        self.send_telemetry(stop["lat"], stop["lon"], pixel_count, 0.0, stop["name"])
        route_sleep(dwell_seconds)

    def run_trip(self, route_stops: list[dict[str, Any]], reverse: bool = False) -> None:
        stops = list(reversed(route_stops)) if reverse else list(route_stops)
        direction = "return" if reverse else "forward"
        self.log(f"Trip direction={direction} with {len(stops)} stops")
        self.dwell_at_stop(stops[0])
        for idx in range(len(stops) - 1):
            if self.stop.is_set():
                return
            self.drive_leg(stops[idx], stops[idx + 1])
            self.dwell_at_stop(stops[idx + 1])

    def run(self) -> None:
        try:
            if not self.driver_login():
                return
            if not self.start_assignment():
                return
            if not self.assign_vehicle_route_for_validation():
                return

            route_stops = self.route.get("stops", [])
            if len(route_stops) < 2:
                self.log("⚠️ Route has no usable stops")
                return

            for trip_number in range(self.trip_count):
                if self.stop.is_set():
                    break
                self.log(f"Trip {trip_number + 1}/{self.trip_count} beginning")
                self.run_trip(route_stops, reverse=False)
                if self.stop.is_set():
                    break
                route_sleep(random.uniform(4, 10))
                self.run_trip(route_stops, reverse=True)
                if self.stop.is_set():
                    break
                self.log(f"Trip {trip_number + 1} complete")
                route_sleep(random.uniform(5, 12))
        finally:
            self.end_assignment()
            self.client.close()
            self.admin_client.close()
            self.log("Done 🏁")


class PassengerSimulation:
    def __init__(self, passenger: dict[str, Any], routes: list[dict[str, Any]], action_count: int = 10):
        self.passenger = passenger
        self.routes = routes
        self.action_count = action_count
        self.client = APIClient(label=f"pax/{passenger['username']}")
        self.stop = threading.Event()
        self.user_id: int | None = None

    def log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [{ts}] 👤 {self.passenger['username']} | {message}")

    def login(self) -> bool:
        if self.client.login(self.passenger["username"], self.passenger["password"]):
            me = self.client.get("/auth/me")
            if isinstance(me, dict):
                self.user_id = me.get("id")
            self.log(f"Logged in (id={self.user_id})")
            return True
        self.log("❌ Login failed")
        return False

    def _pick_route(self) -> dict[str, Any] | None:
        candidates = [route for route in self.routes if len(route.get("stops", [])) >= 2]
        if not candidates:
            return None
        return random.choice(candidates)

    def search_journey(self) -> None:
        route = self._pick_route()
        if not route:
            return
        stops = route["stops"]
        start_index = random.randint(0, len(stops) - 2)
        end_index = random.randint(start_index + 1, len(stops) - 1)
        start_stop = stops[start_index]
        end_stop = stops[end_index]
        result = self.client.post(
            "/search/point-to-point",
            {
                "start_stop_id": start_stop["id"],
                "end_stop_id": end_stop["id"],
            },
        )
        if not result:
            self.log(f"🔍 Search {start_stop['name']} → {end_stop['name']} returned nothing")
            return

        routes = result.get("routes", []) if isinstance(result, dict) else []
        if not routes:
            self.log(f"🔍 Search {start_stop['name']} → {end_stop['name']} had no matching bus")
            return

        live_positions = self.client.get("/vehicles/positions") or {}
        positions = live_positions.get("positions", {}) if isinstance(live_positions, dict) else {}
        matching_positions = [
            pos
            for pos in positions.values()
            if pos.get("route_id") == route.get("route_id")
        ]

        self.log(
            f"🔍 {start_stop['name']} → {end_stop['name']} | "
            f"{len(routes)} route(s), {len(matching_positions)} live bus(es)"
        )
        for item in routes[:3]:
            etas = item.get("etas", {}) if isinstance(item, dict) else {}
            self.log(f"    {item.get('route_number')}: {format_eta_snapshot(etas)}")

        for pos in matching_positions[:2]:
            self.log(
                f"    bus {pos.get('plate_number')} at ({pos.get('lat'):.4f}, {pos.get('lon'):.4f}) "
                f"speed={pos.get('speed', 0):.1f}km/h"
            )

    def browse_routes(self) -> None:
        routes = self.client.get("/routes?skip=0&limit=30")
        if isinstance(routes, list):
            self.log(f"🗺️ Browsed {len(routes)} routes")

    def browse_stops(self) -> None:
        stops = self.client.get("/stops?skip=0&limit=40")
        if isinstance(stops, list):
            self.log(f"📍 Browsed {len(stops)} stops")

    def save_favorite(self) -> None:
        if not self.user_id or not self.routes:
            return
        route = self._pick_route()
        if not route:
            return
        result = self.client.post(
            "/favorites",
            {
                "user_id": self.user_id,
                "route_id": route["route_id"],
                "nickname": random.choice(["Work commute", "Home route", "Daily bus", "My route"]),
            },
        )
        if result:
            self.log(f"⭐ Saved favorite for route {route['route_number']}")

    def set_notification(self) -> None:
        if not self.user_id or not self.routes:
            return
        route = self._pick_route()
        if not route:
            return
        lead_time = random.choice([5, 10, 15, 20])
        result = self.client.post(
            "/notifications/settings",
            {
                "user_id": self.user_id,
                "route_id": route["route_id"],
                "lead_time_minutes": lead_time,
            },
        )
        if result:
            self.log(f"🔔 Notification set for route {route['route_number']} ({lead_time}min)")

    def rate_journey(self) -> None:
        if not self.user_id:
            return
        assignment_id = random.randint(1, 40)
        score = random.choices([1, 2, 3, 4, 5], weights=[0.05, 0.1, 0.2, 0.35, 0.3])[0]
        result = self.client.post(
            "/ratings",
            {
                "user_id": self.user_id,
                "assignment_id": assignment_id,
                "score": score,
                "comment": random.choice([
                    "Excellent service.",
                    "Good ride.",
                    "Average trip.",
                    "Late but usable.",
                ]),
            },
        )
        if result:
            self.log(f"🎯 Rated assignment {assignment_id} with {score}/5")

    def run(self) -> None:
        if not self.login():
            return

        actions = [
            (self.search_journey, 42),
            (self.browse_routes, 15),
            (self.browse_stops, 10),
            (self.save_favorite, 10),
            (self.set_notification, 8),
            (self.rate_journey, 15),
        ]
        funcs = [fn for fn, _ in actions]
        weights = [weight for _, weight in actions]

        self.log(f"Starting {self.action_count} passenger actions...")
        try:
            for _ in range(self.action_count):
                if self.stop.is_set():
                    break
                random.choices(funcs, weights=weights)[0]()
                route_sleep(random.uniform(3, 12))
        finally:
            self.client.close()
            self.log("Session ended")


def build_bus_jobs(state: dict[str, Any], count: int) -> list[BusWorkItem]:
    drivers = [driver for driver in state["drivers"] if driver.get("id")]
    vehicles = [vehicle for vehicle in state["vehicles"] if vehicle.get("id")]
    routes = list(state["routes"].values())
    jobs: list[BusWorkItem] = []
    for index in range(min(count, len(drivers), len(vehicles), len(routes))):
        jobs.append(
            BusWorkItem(
                driver=drivers[index % len(drivers)],
                vehicle=vehicles[index % len(vehicles)],
                route=routes[index % len(routes)],
            )
        )
    return jobs


def build_passenger_simulations(state: dict[str, Any], count: int, action_count: int) -> list[PassengerSimulation]:
    passengers = state["passengers"]
    routes = list(state["routes"].values())
    sims: list[PassengerSimulation] = []
    for index in range(min(count, len(passengers))):
        sims.append(
            PassengerSimulation(
                passenger=passengers[index % len(passengers)],
                routes=routes,
                action_count=action_count,
            )
        )
    return sims


def maybe_sync_route_geometry(client: APIClient, state_routes: dict[str, Any], enabled: bool) -> dict[str, Any]:
    if not enabled:
        return state_routes
    print("  ↻ Syncing route geometry from API...")
    synced = load_routes_from_api(client, state_routes)
    for route_number, route in synced.items():
        print(f"    ✓ {route_number}: {len(route.get('stops', []))} stops")
    return synced


def main() -> None:
    parser = argparse.ArgumentParser(description="BusTrack Full System Simulation")
    parser.add_argument("--buses", type=int, default=4)
    parser.add_argument("--passengers", type=int, default=6)
    parser.add_argument("--trips", type=int, default=3)
    parser.add_argument("--actions", type=int, default=14)
    parser.add_argument("--duration", type=int, default=None, help="Stop after N seconds")
    parser.add_argument("--sync-routes", action="store_true", help="Refresh route geometry from the API")
    args = parser.parse_args()

    state = load_state()
    api = APIClient(label="simulation-bootstrap")
    state["routes"] = maybe_sync_route_geometry(api, state["routes"], args.sync_routes)
    api.close()

    bus_jobs = build_bus_jobs(state, args.buses)
    passenger_jobs = build_passenger_simulations(state, args.passengers, args.actions)

    if not bus_jobs or not passenger_jobs:
        print("❌ Simulation state is incomplete. Run 01_setup.py first.")
        sys.exit(1)

    print(
        f"""
╔══════════════════════════════════════════════════╗
║        BusTrack Full System Simulation           ║
║   Addis Ababa Public Transport Network           ║
╚══════════════════════════════════════════════════╝
  API:        {BASE_URL}
  Buses:      {len(bus_jobs)}
  Passengers: {len(passenger_jobs)}
  GPS ping:   every {GPS_PING_INTERVAL}s (speed {SIMULATION_SPEED}x)
  Duration:   {"∞" if not args.duration else f"{args.duration}s"}

  Ctrl+C to stop gracefully
"""
    )

    workers: list[tuple[threading.Thread, Any]] = []

    print(f"{'─'*60}")
    for index, job in enumerate(bus_jobs):
        simulation = BusSimulation(job, trip_count=args.trips)
        thread = threading.Thread(target=simulation.run, daemon=True)
        workers.append((thread, simulation))
        thread.start()
        print(
            f"  🚌 Bus {index + 1}: {simulation.vehicle['plate_number']} → Route {simulation.route['route_number']}"
        )
        route_sleep(random.uniform(2, 5))

    print("\n  Waiting 5s then starting passengers...")
    route_sleep(5)

    for index, simulation in enumerate(passenger_jobs):
        thread = threading.Thread(target=simulation.run, daemon=True)
        workers.append((thread, simulation))
        thread.start()
        print(f"  👤 Passenger {index + 1}: {simulation.passenger['username']}")
        route_sleep(random.uniform(1, 3))

    print(f"\n  ✅ {len(bus_jobs)} buses + {len(passenger_jobs)} passengers running\n{'─'*60}\n")

    try:
        if args.duration:
            route_sleep(args.duration)
            raise KeyboardInterrupt
        for thread, _ in workers:
            thread.join()
    except KeyboardInterrupt:
        print("\n🛑 Stopping...")
        for _, simulation in workers:
            simulation.stop.set()
        for thread, _ in workers:
            thread.join(timeout=8)

    print("\n✓ Done. Check your dashboard and passenger search screens.")


if __name__ == "__main__":
    main()
