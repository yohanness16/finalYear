# Simulation and Admin Map

This document is the quickest way to run the backend simulation against either a local backend or a hosted server.

## What the simulation needs

1. A reachable backend API.
2. Admin credentials that can start assignments.
3. A writable `simulation_state.json` created by `simulation/01_setup.py`.

## Local backend

If the backend is running on the same machine:

```bash
export BUSTRACK_API_URL=https://api.bustrack.dpdns.org/api/v1
cd backend/simulation
python 00_check.py
python 01_setup.py
python 04_full_simulation_esp32.py --buses 4 --passengers 6 --duration 300
```

## Hosted backend

If the backend is deployed somewhere else, point the simulator at the hosted API URL:

```bash
export BUSTRACK_API_URL=https://api.bustrack.dpdns.org/api/v1
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD=admin123
cd backend/simulation
python 00_check.py
python 01_setup.py
python 04_full_simulation_esp32.py --buses 4 --passengers 6 --duration 300
```

If you run the simulation from your laptop or another machine, `BUSTRACK_API_URL` must be the public server URL above.

## Recommended order

1. Start the backend.
2. Verify `/health` or `/docs` is reachable.
3. Run `01_setup.py` once.
4. Run the bus or full simulation.

## Common failure points

1. `Connection refused` means the API URL is wrong or the backend is down.
2. `simulation_state.json not found` means `01_setup.py` was not run first.
3. `409` on assignment start usually means a stale active assignment still exists; the simulator now retries after cleaning it up.
4. `403` or login failures usually mean the admin credentials are wrong for the hosted database.

## Helpful checks

```bash
bash scripts/smoke_simulation.sh
curl "$BUSTRACK_API_URL/health"
```

## Notes

The simulator uses the live API; it does not mock backend behavior. That means the hosted backend must have the database, Redis, and auth setup ready before you start the simulation.