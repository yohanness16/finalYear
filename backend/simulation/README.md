# BusTrack Simulation Suite

Simulates a complete Addis Ababa bus network — drivers, passengers, GPS movement, and real API interactions.

For a concise overview of env vars, endpoints, the admin map, and troubleshooting, see **[docs/SIMULATION_AND_ADMIN_MAP.md](../../docs/SIMULATION_AND_ADMIN_MAP.md)**.

## Files

| File | Purpose |
|------|---------|
| `config.py` | All routes, vehicles, drivers, passengers for Addis Ababa |
| `api_client.py` | HTTP client with JWT auth (`POST` treats **200** and **201** as success; `get` returns **dict or list**) |
| `gps_utils.py` | Haversine distance and interpolated GPS points |
| `route_loader.py` | Build stop lists from **`GET /routes/{id}`** (same shape as `drive_route`) |
| `00_check.py` | Health check — verify API is up |
| `01_setup.py` | **Run once** — creates all users, routes, stops, vehicles; writes `simulation_state.json` |
| `02_simulate_buses.py` | Drives buses along routes with GPS pings and **speed (km/h)** |
| `03_simulate_passengers.py` | Simulates passenger app usage |
| `04_full_simulation.py` | Runs everything together |

## Quick Start

```bash
cd backend/simulation/

# Install dependency
pip install httpx

# 1. Set your admin credentials (or rely on defaults in config.py)
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD=admin123
export BUSTRACK_API_URL=http://localhost:8000/api/v1

# 2. Check the API is running
python 00_check.py

# 3. Create all users, routes, stops, vehicles (run ONCE)
python 01_setup.py

# 3b. Larger synthetic fleet (+5 extra driver + bus pairs)
python 01_setup.py --extra-fleet 5

# 4a. Run just the buses
python 02_simulate_buses.py

# 4b. Refresh stop coordinates from the API before driving (recommended after DB edits)
python 02_simulate_buses.py --sync-routes

# 4c. Run just the passengers (in another terminal)
python 03_simulate_passengers.py

# 4d. OR run everything together
python 04_full_simulation.py --buses 4 --passengers 6 --duration 300
```

### Assignments

Starting and ending trips uses **admin** JWT (`ADMIN_USERNAME` / `ADMIN_PASSWORD`). The **`POST /assignments/start`** response uses the assignment field **`id`** (not `assignment_id`) for **`POST /assignments/end`**.

If start returns **409** (vehicle already has an active assignment), the simulator calls **`GET /assignments/active`**, ends any row whose **`vehicle_id`** matches the bus, and **retries start once**.

### Vehicle route and on-route checks

After a successful start, the simulator calls **`PUT /vehicles/{vehicle_id}`** with `{ "route_id": ... }` so `vehicle.route_id` matches the driven corridor and **`POST /telemetry`** on-route validation aligns with the same geometry.

## What Gets Created

### Users
- **10 drivers** (driver_tadesse, driver_almaz, driver_kebede, ...)
- **15 passengers** (passenger_sara, passenger_abebe, ...)

### Routes (Real Addis Ababa)
| Route | Path |
|-------|------|
| 12 | Megenagna → Mexico |
| 45 | Stadium → Ayat |
| 21 | Merkato → Bole Airport |
| 67 | Saris → Piassa |
| 89 | Kazanchis → Lideta |
| 33 | Megenagna → Saris |

### Vehicles
- 10 buses (Anbessa, Sheger, Minibus types)
- Each with a unique SIM7600 IMEI device ID

## Simulation Behavior

### Buses
- Drivers log in; **admin** starts an assignment for driver + vehicle + route
- Bus sends GPS pings every 5s along the route (interval from `GPS_PING_INTERVAL`)
- **Speed** is derived from segment distance / ping interval and sent as **km/h** (same unit as the admin map popup)
- Pixel count mimics ESP32-CAM occupancy (Low/Medium/High)
- Occupancy changes realistically by time of day
- GPS has realistic jitter (±22m noise)
- Buses do round trips (forward then reverse)

### Passengers
- Log in and browse the system
- Search point-to-point routes
- Save favorite routes
- Set notification preferences
- Rate journeys (1–5 stars with realistic distribution)

## Configuration

Edit `config.py` to change:
- `GPS_PING_INTERVAL` — seconds between GPS pings (default: 5)
- `SIMULATION_SPEED` — 1.0 = real time, 2.0 = 2x faster
- `CONCURRENT_BUSES` — default concurrent bus count
- Add more routes, vehicles, drivers, passengers

## Advanced Options

```bash
# Run 6 buses doing 5 round trips each
python 02_simulate_buses.py --buses 6 --loops 5

# Run 10 passengers doing 20 actions each
python 03_simulate_passengers.py --concurrent 10 --loops 20

# Full simulation for 10 minutes
python 04_full_simulation.py --buses 5 --passengers 8 --duration 600
```

## Smoke check (no bus loop)

From the repository root:

```bash
bash backend/scripts/smoke_simulation.sh
```

## Backend tests (simulation helpers)

From `backend/`:

```bash
python -m pytest tests/test_simulation_helpers.py -v
```
