# Simulation and admin map

This document ties together the **Python bus simulation** under `backend/simulation/`, the **FastAPI** endpoints they use, and the **Next.js admin map** at `/map`.

## Prerequisites

- **PostgreSQL** — database URL configured for the backend (see backend settings).
- **Redis** — used for live bus state and route-stop cache; start `redis-server` before running the API if your environment expects it.
- **Backend** — `uvicorn app.main:app` (or your process manager) with migrations applied.
- **Admin user** — the setup scripts log in as admin (`ADMIN_USERNAME` / `ADMIN_PASSWORD`, defaults in `backend/simulation/config.py`).

## Environment variables

| Variable | Used by | Purpose |
|----------|---------|---------|
| `BUSTRACK_API_URL` | Simulation `config.py` | API base, default `http://localhost:8000/api/v1` |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | `01_setup.py`, `02_simulate_buses.py` | Admin JWT for creating data, starting/ending assignments, vehicle `route_id`, conflict recovery |
| `NEXT_PUBLIC_API_URL` | Admin app | Browser-facing API origin for `/map` and other pages |
| `NEXT_PUBLIC_WS_URL` | Admin app (optional) | Full WebSocket URL for fleet stream; if unset, derived as `ws(s)://<api-host>/api/v1/ws/live` |
| Admin JWT | WebSocket | Dashboard/map open **`/api/v1/ws/live?token=<access_token>`** (same token as `Authorization: Bearer`). Only **`admin`** role connections are accepted. |

## Live dashboard (WebSocket)

After each successful **`POST /telemetry`** or **`POST /vehicles/telemetry`** position write, the API **`broadcast`s** a JSON message:

`{ "type": "vehicle_position", "vehicle_id", "plate_number", "lat", "lon", "speed", "route_id", "timestamp" }`

The admin **`RealTimeBusMap`** merges these over REST-polled positions (REST remains a slower fallback). The map shows a small **Live: open | connecting | error** badge when WebSocket mode is enabled.

## Script order

1. **`backend/simulation/00_check.py`** — Verifies the API is reachable.
2. **`backend/simulation/01_setup.py`** — One-time (or idempotent) creation of drivers, passengers, stops, routes, vehicles; writes `simulation_state.json`. Use **`--extra-fleet N`** to add **N** synthetic driver+vehicle pairs (`driver_sim_200+…`, `AA-SIM-00200+…`) for heavier load tests.
3. **`backend/simulation/02_simulate_buses.py`** — Concurrent buses: driver login, **admin** starts assignment, optional **admin** `PUT /vehicles/{id}` with `route_id`, GPS pings to **`POST /telemetry`**, admin ends assignment.

Optional flags for `02_simulate_buses.py`:

- **`--sync-routes`** — After loading `simulation_state.json`, refreshes each bus route’s ordered stops from **`GET /routes/{route_id}`** so coordinates match the database.
- **`--buses`**, **`--loops`** — Concurrency and round trips per bus.

## API surface relevant to simulation

- **`POST /auth/login`** — Driver (and admin) tokens.
- **`POST /assignments/start`** (admin) — Body: `driver_id`, `vehicle_id`, `route_id`. Response includes assignment **`id`** (use this for **`POST /assignments/end`**).
- **`GET /assignments/active`** (admin) — Used when start returns **409** (vehicle already has an active assignment): end matching rows, then retry start once.
- **`PUT /vehicles/{vehicle_id}`** (admin) — Body: `{ "route_id": <int> }` (optional). Sets the corridor used by **`POST /telemetry`** on-route validation when `vehicle.route_id` is set.
- **`POST /telemetry`** — Body includes `device_id`, `lat`, `lon`, optional **`speed`** (km/h in simulation, consistent with the admin map labels), `pixel_count`, `raw_payload`.

## Admin map (`/map`)

The map page loads the vehicle registry and polls positions:

- **`GET /vehicles`** — Fleet metadata (`route_id`, `route_number`, last known position fields).
- **`GET /vehicles/positions`** — Live envelope with `positions` keyed by vehicle id string.

When a **route filter** is selected, the UI calls **`GET /routes/{id}`** and draws a **polyline** through stop coordinates. With WebSocket on, REST position polling is relaxed (**~8s** dashboard, **~4s** map page) since pings update markers in real time.

## Troubleshooting

- **409 on `/assignments/start`** — A previous run left an active assignment. The simulator ends assignments for that `vehicle_id` via admin and retries once; if it persists, call **`POST /assignments/end`** with the active assignment `id` or inspect **`GET /assignments/active`**.
- **Telemetry `off_route` / rejected** — `vehicle.route_id` is set but GPS is outside the corridor. Ensure the simulator refreshed stops (`--sync-routes`) and that **`PUT /vehicles/{id}`** assigned the same `route_id` as the assignment (the simulator does this after a successful start).
- **Admin map shows no movement** — Confirm telemetry returns `received`, Redis/DB are up, and increase refresh cadence on `/map` (`positionIntervalMs`).

## Quick smoke check

From the repo root:

```bash
bash backend/scripts/smoke_simulation.sh
```

Runs the API health script and imports the simulation HTTP client (no live bus loop).
