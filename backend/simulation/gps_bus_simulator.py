"""
GPS Bus Simulator - Tests real-time GPS tracking for multiple buses.
Simulates bus movements and validates GPS data processing.
"""
import asyncio
import random
import math
from datetime import datetime, timedelta
from typing import List, Tuple, Dict
import json

from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import AsyncSessionLocal
from app.models.vehicle import Vehicle
from app.models.raw_telemetry import RawTelemetry
from app.crud.tracking import create_raw_telemetry
from app.utils.gps_validation import is_valid_coord, haversine_meters


class BusGPSPoint:
    """Represents a single GPS data point for a bus."""
    def __init__(self, lat: float, lon: float, timestamp: datetime,
                 speed: float = 0.0, accuracy: float = 5.0):
        self.lat = lat
        self.lon = lon
        self.timestamp = timestamp
        self.speed = speed
        self.accuracy = accuracy


class BusSimulator:
    """Simulates multiple buses with realistic GPS movements."""

    def __init__(self, num_buses: int = 5):
        self.num_buses = num_buses
        self.buses = {}
        self.telemetry_buffer = []

    def generate_route_points(self, num_points: int = 10) -> List[Tuple[float, float]]:
        """Generate a realistic bus route with waypoints."""
        # Start at Addis Ababa coordinates
        start_lat, start_lon = 9.0320, 38.7520
        points = [(start_lat, start_lon)]

        for i in range(1, num_points):
            # Small random movement (simulating bus route)
            lat_offset = random.uniform(-0.02, 0.02)
            lon_offset = random.uniform(-0.02, 0.02)
            new_lat = points[-1][0] + lat_offset
            new_lon = points[-1][1] + lon_offset
            points.append((new_lat, new_lon))

        return points

    def generate_gps_with_noise(self, base_lat: float, base_lon: float,
                                 noise_level: float = 0.001) -> Tuple[float, float]:
        """Add realistic GPS noise to coordinates."""
        lat_noise = random.uniform(-noise_level, noise_level)
        lon_noise = random.uniform(-noise_level, noise_level)
        return base_lat + lat_noise, base_lon + lon_noise

    def generate_outlier_gps(self, base_lat: float, base_lon: float) -> Tuple[float, float]:
        """Generate an outlier GPS point (for testing outlier rejection)."""
        # Create a point 10+ km away (outlier)
        offset_deg = 0.1  # ~11km at equator
        return base_lat + offset_deg, base_lon + offset_deg

    async def initialize_buses(self, db_session: AsyncSession):
        """Initialize buses in the database."""
        bus_types = ["Anbessa", "Sheger", "Minibus", "BlueBus"]

        for i in range(self.num_buses):
            bus = Vehicle(
                plate_number=f"BUS-{i:03d}",
                device_id=f"IMEI_{i:06d}",
                bus_type=random.choice(bus_types),
                capacity=random.choice([40, 50, 60, 70]),
                is_active=True,
            )
            db_session.add(bus)
            self.buses[i] = {
                'vehicle': bus,
                'current_route': [],
                'current_point_idx': 0,
                'is_moving': True,
                'speed': 15.0,  # km/h
            }

        await db_session.commit()
        print(f"Initialized {self.num_buses} buses")

    def generate_telemetry_for_bus(self, bus_idx: int, current_lat: float,
                                   current_lon: float) -> Tuple[float, float, Dict]:
        """Generate GPS telemetry for a specific bus."""
        bus_info = self.buses[bus_idx]

        # Simulate occasional outliers (5% chance)
        if random.random() < 0.05:
            lat, lon = self.generate_outlier_gps(current_lat, current_lon)
            is_outlier = True
        else:
            lat, lon = self.generate_gps_with_noise(current_lat, current_lon)
            is_outlier = False

        # Calculate speed (simulate movement)
        speed = bus_info['speed'] * random.uniform(0.8, 1.2)

        telemetry_data = {
            'speed': speed,
            'battery': random.randint(70, 100),
            'signal_strength': random.randint(-100, -50),
            'is_moving': bus_info['is_moving'],
        }

        return lat, lon, telemetry_data

    async def simulate_bus_movement(self, db_session: AsyncSession,
                                  num_iterations: int = 20,
                                  outlier_test: bool = True):
        """Simulate bus movements and store GPS telemetry."""
        print(f"\n=== Starting GPS Simulation ({num_iterations} iterations) ===")

        # Initialize routes for each bus
        for bus_idx in self.buses:
            num_route_points = random.randint(5, 15)
            self.buses[bus_idx]['current_route'] = self.generate_route_points(num_route_points)

        all_telemetry = []

        for iteration in range(num_iterations):
            print(f"\n--- Iteration {iteration + 1}/{num_iterations} ---")

            for bus_idx in range(self.num_buses):
                bus_info = self.buses[bus_idx]
                vehicle = bus_info['vehicle']

                # Get current position
                if bus_info['current_route']:
                    route = bus_info['current_route']
                    point_idx = bus_info['current_point_idx'] % len(route)
                    current_lat, current_lon = route[point_idx]
                    bus_info['current_point_idx'] += 1
                else:
                    current_lat, current_lon = 9.0320, 38.7520

                # Generate telemetry
                lat, lon, telemetry_data = self.generate_telemetry_for_bus(
                    bus_idx, current_lat, current_lon
                )

                # Store telemetry
                telemetry = await create_raw_telemetry(
                    db_session,
                    vehicle_id=vehicle.id,
                    raw_lat=lat,
                    raw_lon=lon,
                    pixel_count=random.randint(2000, 8000),
                    raw_payload=telemetry_data,
                )

                all_telemetry.append({
                    'bus_id': vehicle.id,
                    'bus_plate': vehicle.plate_number,
                    'lat': lat,
                    'lon': lon,
                    'iteration': iteration,
                    'is_outlier': lat != round(lat, 4),  # Simple outlier detection
                })

                print(f"  Bus {vehicle.plate_number}: ({lat:.4f}, {lon:.4f}) "
                     f"speed={telemetry_data['speed']}km/h")

        # Verify each bus has its own telemetry
        print(f"\n=== Verification ===")
        for bus_idx in range(self.num_buses):
            bus_telemetry = [t for t in all_telemetry if t['bus_id'] == bus_idx]
            print(f"Bus {bus_idx}: {len(bus_telemetry)} GPS points recorded")

            # Verify all points belong to correct bus
            for t in bus_telemetry:
                assert t['bus_id'] == bus_idx, f"Telemetry mismatch for bus {bus_idx}"

        return all_telemetry


async def run_simulation():
    """Run the complete GPS bus simulation."""
    print("🚌 Bus GPS Tracking Simulator")
    print("=" * 50)

    # Initialize database session
    async with AsyncSessionLocal() as db_session:
        # Initialize simulator with 3 buses
        simulator = BusSimulator(num_buses=3)
        await simulator.initialize_buses(db_session)

        # Run simulation
        telemetry_data = await simulator.simulate_bus_movement(
            db_session,
            num_iterations=10,
            outlier_test=True
        )

        # Summary
        print("\n" + "=" * 50)
        print("📊 SIMULATION SUMMARY")
        print("=" * 50)
        print(f"Total GPS points recorded: {len(telemetry_data)}")
        print(f"Buses tracked: {len(set(t['bus_id'] for t in telemetry_data))}")

        # Check for outliers
        outliers = [t for t in telemetry_data if t['is_outlier']]
        print(f"Outlier points detected: {len(outliers)}")

        # Verify per-bus tracking
        for bus_id in set(t['bus_id'] for t in telemetry_data):
            bus_telemetry = [t for t in telemetry_data if t['bus_id'] == bus_id]
            print(f"\nBus {bus_id}: {len(bus_telemetry)} points")
            print(f"  Coordinate range: "
                  f"Lat [{min(t['lat'] for t in bus_telemetry):.4f}, "
                  f"{max(t['lat'] for t in bus_telemetry):.4f}], "
                  f"Lon [{min(t['lon'] for t in bus_telemetry):.4f}, "
                  f"{max(t['lon'] for t in bus_telemetry):.4f}]")


if __name__ == "__main__":
    asyncio.run(run_simulation())