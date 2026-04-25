"""
BusTrack Full Simulation Orchestrator
Runs buses AND passengers simultaneously.

Usage:
    python 04_full_simulation.py
    python 04_full_simulation.py --duration 300   # stop after 5 min
    python 04_full_simulation.py --buses 4 --passengers 8
"""

import sys
import json
import time
import random
import argparse
import threading
import importlib
import importlib.util
import os

from api_client import APIClient
from config import GPS_PING_INTERVAL, SIMULATION_SPEED


def load_state(filename: str = "simulation_state.json") -> dict:
    try:
        with open(filename) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ {filename} not found. Run: python 01_setup.py first.")
        sys.exit(1)


def load_module(filename: str, module_name: str):
    spec = importlib.util.spec_from_file_location(
        module_name,
        os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    bus_mod = load_module("02_simulate_buses.py", "simulate_buses")
    pax_mod = load_module("03_simulate_passengers.py", "simulate_passengers")
    BusSimulator = bus_mod.BusSimulator
    run_bus = bus_mod.run_bus
    PassengerSimulator = pax_mod.PassengerSimulator
    run_passenger = pax_mod.run_passenger

    parser = argparse.ArgumentParser()
    parser.add_argument("--buses",      type=int, default=4)
    parser.add_argument("--passengers", type=int, default=6)
    parser.add_argument("--trips",      type=int, default=99)
    parser.add_argument("--actions",    type=int, default=50)
    parser.add_argument("--duration",   type=int, default=None, help="Stop after N seconds")
    args = parser.parse_args()

    state = load_state()

    print(f"""
╔══════════════════════════════════════════════════╗
║        BusTrack Full System Simulation           ║
║   Addis Ababa Public Transport Network           ║
╚══════════════════════════════════════════════════╝
  API:        {__import__('config').BASE_URL}
  Buses:      {args.buses}
  Passengers: {args.passengers}
  GPS ping:   every {GPS_PING_INTERVAL}s (speed {SIMULATION_SPEED}x)
  Duration:   {"∞" if not args.duration else f"{args.duration}s"}

  Ctrl+C to stop gracefully
""")

    drivers    = [d for d in state["drivers"] if d.get("id")]
    vehicles   = state["vehicles"]
    routes     = list(state["routes"].values())
    passengers = state["passengers"]

    if not drivers or not vehicles or not routes:
        print("❌ Missing data in simulation_state.json. Run 01_setup.py first.")
        sys.exit(1)

    num_buses = min(args.buses, len(drivers), len(vehicles))
    bus_sims = [
        BusSimulator(
            driver=drivers[i % len(drivers)],
            vehicle=vehicles[i % len(vehicles)],
            route=routes[i % len(routes)],
            trip_count=args.trips,
        )
        for i in range(num_buses)
    ]

    num_pax = min(args.passengers, len(passengers))
    pax_sims = [
        PassengerSimulator(
            passenger=passengers[i % len(passengers)],
            routes=routes,
            action_count=args.actions,
        )
        for i in range(num_pax)
    ]

    all_threads = []

    print(f"{'─'*50}")
    for i, sim in enumerate(bus_sims):
        t = threading.Thread(target=run_bus, args=(sim,), daemon=True)
        all_threads.append((t, sim))
        t.start()
        print(f"  🚌 Bus {i+1}: {sim.vehicle['plate_number']} → Route {sim.route['route_number']}")
        time.sleep(random.uniform(2, 5))

    print(f"\n  Waiting 5s then starting passengers...")
    time.sleep(5)

    for i, sim in enumerate(pax_sims):
        t = threading.Thread(target=run_passenger, args=(sim,), daemon=True)
        all_threads.append((t, sim))
        t.start()
        print(f"  👤 Passenger {i+1}: {sim.passenger['username']}")
        time.sleep(random.uniform(1, 3))

    print(f"\n  ✅ {num_buses} buses + {num_pax} passengers running\n{'─'*50}\n")

    try:
        if args.duration:
            time.sleep(args.duration)
            raise KeyboardInterrupt
        else:
            for t, _ in all_threads:
                t.join()
    except KeyboardInterrupt:
        print(f"\n🛑 Stopping...")
        for _, sim in all_threads:
            sim.stop.set()
        for t, _ in all_threads:
            t.join(timeout=8)

    print(f"\n✓ Done. Check your dashboard at http://localhost:3000")


if __name__ == "__main__":
    main()
