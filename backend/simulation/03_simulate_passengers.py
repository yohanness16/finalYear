"""
BusTrack Passenger Behavior Simulator
Simulates realistic passenger interactions:
  - Login
  - Search point-to-point routes
  - Save favorite routes
  - Set notification preferences
  - Rate journeys

Usage:
    python 03_simulate_passengers.py
    python 03_simulate_passengers.py --loops 10   # each passenger does 10 actions
"""

import sys
import json
import time
import random
import argparse
import threading
from datetime import datetime
from pathlib import Path
from api_client import APIClient
from config import PASSENGERS


SCRIPT_DIR = Path(__file__).resolve().parent


def load_state(filename: str = "simulation_state.json") -> dict:
    state_path = Path(filename)
    if not state_path.is_absolute():
        state_path = SCRIPT_DIR / state_path
    try:
        with open(state_path) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ {state_path} not found. Run 01_setup.py first.")
        sys.exit(1)


class PassengerSimulator:
    def __init__(self, passenger: dict, routes: list, action_count: int = 10):
        self.passenger = passenger
        self.routes = routes
        self.action_count = action_count
        self.client = APIClient(label=f"pax/{passenger['username']}")
        self.stop = threading.Event()
        self.user_id = None

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [{ts}] 👤 {self.passenger['username']} | {msg}")

    def login(self) -> bool:
        if self.client.login(self.passenger["username"], self.passenger["password"]):
            me = self.client.get("/auth/me")
            if me:
                self.user_id = me.get("id")
            self.log(f"Logged in (id={self.user_id})")
            return True
        self.log("❌ Login failed")
        return False

    def search_route(self):
        """Search for a journey using start/end coordinates."""
        routes = self.routes
        if len(routes) < 1:
            return
        route = random.choice(routes)
        stops = route.get("stops", [])
        if len(stops) < 2:
            return

        # Pick random start and end stops
        idx_a = random.randint(0, len(stops) - 2)
        idx_b = random.randint(idx_a + 1, len(stops) - 1)
        if random.random() < 0.35:
            idx_a, idx_b = idx_b, idx_a
        stop_a = stops[idx_a]
        stop_b = stops[idx_b]

        if not stop_a.get("id") or not stop_b.get("id"):
            return

        result = self.client.post(
            "/search/journey",
            {
                "start_lat": stop_a["lat"],
                "start_lon": stop_a["lon"],
                "end_lat": stop_b["lat"],
                "end_lon": stop_b["lon"],
                "max_routes": 3,
                "max_buses": 4,
            },
        )
        if result:
            count = len(result.get("routes", []))
            self.log(f"🔍 Searched {stop_a['name']} → {stop_b['name']} → {count} routes found")
        else:
            self.log(f"🔍 Search {stop_a['name']} → {stop_b['name']} (no result)")

    def save_favorite(self):
        """Save a random route as favorite."""
        if not self.user_id or not self.routes:
            return
        route = random.choice(self.routes)
        route_id = route.get("route_id")
        if not route_id:
            return
        nicknames = ["Work commute", "Home route", "Daily bus", "My route", "Megenagna line"]
        result = self.client.post("/favorites", {
            "user_id": self.user_id,
            "route_id": route_id,
            "nickname": random.choice(nicknames),
        })
        if result:
            self.log(f"⭐ Saved favorite: Route {route['route_number']}")

    def view_favorites(self):
        """View own favorites."""
        if not self.user_id:
            return
        result = self.client.get(f"/favorites/{self.user_id}")
        if result:
            count = len(result) if isinstance(result, list) else 0
            self.log(f"📋 Viewed favorites ({count} saved)")

    def set_notification(self):
        """Set proximity notification for a route."""
        if not self.user_id or not self.routes:
            return
        route = random.choice(self.routes)
        route_id = route.get("route_id")
        if not route_id:
            return
        lead_time = random.choice([5, 10, 15, 20])
        result = self.client.post("/notifications/settings", {
            "user_id": self.user_id,
            "route_id": route_id,
            "lead_time_minutes": lead_time,
        })
        if result:
            self.log(f"🔔 Set notification: Route {route['route_number']}, {lead_time}min lead")

    def check_crowd(self):
        """Check crowd density for a vehicle (passenger checking before boarding)."""
        try:
            vehicles = self.client.get("/vehicles?skip=0&limit=20") or []
            if vehicles:
                vehicle = random.choice(vehicles)
                plate = vehicle.get("plate_number")
                if plate:
                    # Admin-only endpoint — may fail for passenger accounts
                    cv = self.client.get(f"/admin/crowd/{plate}")
                    if cv:
                        density = cv.get("cv", {}).get("crowd_density", 0)
                        people = cv.get("cv", {}).get("people_count", 0)
                        density_label = ["empty", "medium", "crowded"][min(density, 2)]
                        self.log(f"👥 {plate}: {density_label} ({people} people)")
                    else:
                        # Fallback: check live positions for occupancy data
                        positions = self.client.get("/vehicles/positions") or {}
                        pos_dict = positions.get("positions", {}) if isinstance(positions, dict) else {}
                        for pos in pos_dict.values():
                            if pos.get("plate_number") == plate:
                                occ = pos.get("occupancy_level", 0)
                                occ_label = ["empty", "medium", "crowded"][min(occ, 2)]
                                self.log(f"👥 {plate}: {occ_label} (from live position)")
                                break
                        else:
                            self.log(f"👥 {plate}: no CV data yet")
        except Exception:
            pass

    def rate_journey(self, assignment_id: int = None):
        """Rate a journey."""
        if not self.user_id:
            return
        # Use a random assignment_id between 1-20 for simulation
        asgn_id = assignment_id or random.randint(1, 20)
        score = random.choices([1, 2, 3, 4, 5], weights=[0.05, 0.1, 0.2, 0.35, 0.3])[0]
        comments = {
            5: "Excellent service! Very punctual.",
            4: "Good ride, comfortable.",
            3: "Average, could be better.",
            2: "Bus was late and crowded.",
            1: "Very poor service today.",
        }
        result = self.client.post("/ratings", {
            "user_id": self.user_id,
            "assignment_id": asgn_id,
            "score": score,
            "comment": comments[score],
        })
        if result:
            stars = "⭐" * score
            self.log(f"🎯 Rated journey {asgn_id}: {stars} ({score}/5)")

    def view_routes(self):
        """Browse available routes."""
        result = self.client.get("/routes?skip=0&limit=20")
        if result and isinstance(result, list):
            self.log(f"🗺️  Browsed routes ({len(result)} available)")

    def view_stops(self):
        """View stops list."""
        result = self.client.get("/stops?skip=0&limit=20")
        if result and isinstance(result, list):
            self.log(f"📍 Viewed stops ({len(result)} available)")

    def run(self):
        if not self.login():
            return

        # Define passenger action weights (realistic behavior)
        actions = [
            (self.search_route,       30),  # Search most common
            (self.view_routes,        15),  # Browse routes
            (self.view_stops,          8),  # Look at stops
            (self.check_crowd,        12),  # Check crowd density before boarding
            (self.save_favorite,       8),  # Save favorites
            (self.view_favorites,      7),  # View saved routes
            (self.set_notification,    5),  # Set notifications
            (self.rate_journey,       10),  # Rate trips
        ]

        weights = [w for _, w in actions]
        funcs = [f for f, _ in actions]

        self.log(f"Starting {self.action_count} passenger actions...")

        try:
            for i in range(self.action_count):
                if self.stop.is_set():
                    break

                action = random.choices(funcs, weights=weights)[0]
                action()

                # Realistic delay between actions (5-45 seconds)
                delay = random.uniform(3, 15)
                time.sleep(delay)

        except Exception as e:
            self.log(f"Error: {e}")
        finally:
            self.client.close()
            self.log("Session ended")


def run_passenger(sim: PassengerSimulator):
    sim.run()


def main():
    parser = argparse.ArgumentParser(description="BusTrack Passenger Simulator")
    parser.add_argument("--loops", type=int, default=8, help="Actions per passenger")
    parser.add_argument("--concurrent", type=int, default=5, help="Concurrent passengers")
    args = parser.parse_args()

    state = load_state()
    routes = list(state["routes"].values())
    passengers = state["passengers"]

    print(f"\n{'═'*60}")
    print(f"  👥 BusTrack Passenger Simulator")
    print(f"{'═'*60}")
    print(f"  Passengers: {len(passengers)}")
    print(f"  Routes:     {len(routes)}")
    print(f"  Actions each: {args.loops}")
    print(f"  Concurrent:   {args.concurrent}")
    print(f"\n  Press Ctrl+C to stop\n")

    concurrent = min(args.concurrent, len(passengers))

    # Run in waves
    simulations = []
    for p in passengers[:concurrent]:
        sim = PassengerSimulator(
            passenger=p,
            routes=routes,
            action_count=args.loops,
        )
        simulations.append(sim)

    threads = []
    try:
        for i, sim in enumerate(simulations):
            t = threading.Thread(target=run_passenger, args=(sim,), daemon=True)
            threads.append((t, sim))
            t.start()
            print(f"  👤 Started passenger: {sim.passenger['username']}")
            time.sleep(random.uniform(1, 4))

        for t, sim in threads:
            t.join()

    except KeyboardInterrupt:
        print(f"\n\n  🛑 Stopping passengers...")
        for t, sim in threads:
            sim.stop.set()
        for t, sim in threads:
            t.join(timeout=5)

    print(f"\n  ✓ All passenger sessions ended.")


if __name__ == "__main__":
    main()
