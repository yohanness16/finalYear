# Implementation Log — 2026-06-12

## Commit: `9d36853`

### ✅ What Was Done

#### 1. ETA Calculation Pipeline Fix
- **`eta_engine.py`**: Fixed ML feature mismatch — `peak_multiplier` was hardcoded to `1.0` instead of using the actual value from `get_time_multiplier()`. This caused the ML model to see different inputs than the heuristic calculator, producing wrong adjustments.
- **`eta_engine.py`**: Removed duplicate `haversine_meters()` call — distance was computed twice (once explicitly, once inside `calculate_eta_heuristic`).
- **`route_eta.py`**: Changed O(n²) → O(n) dwell time accumulation — replaced inner re-summing loop with a running accumulator.
- **`route_eta.py`**: Fixed speed minimum — stationary bus (speed=0) no longer gets a fake 6 m/s. Uses 1.0 m/s floor to avoid division-by-zero.
- **`eta_calc.py`**: Removed stray comment fragment.

#### 2. GPS Validation Fix
- **`route_validation.py`**: Relaxed `is_on_route()` threshold from 200m → 500m (GPS drift in cities can be 20-50m, inter-stop segments can be 400-800m).
- **`route_validation.py`**: Added `_point_to_segment_distance_m()` — checks distance to line segments between consecutive stops, not just to stops themselves. This correctly handles buses traveling between stops.
- **`image_pipeline.py`**: Changed `_validate_gps()` to use graceful degradation — instead of outright rejecting off-route points, falls back to last known good position. If no history, accepts the point (doesn't lose data).

#### 3. Redis Stream Fix
- **`redis_cache.py`**: Added `maxlen=10000, approximate=True` to `pipe:positions` stream via `xadd()`. Previously unbounded — would cause Redis OOM.
- **`redis_cache.py`**: Same fix for `push_live_position()` function.
- **`redis_client.py`**: Updated `FakeRedis.xadd()` to support `maxlen` parameter for test accuracy.

#### 4. Security Fixes (No API Changes)
- **`admin_users.py`**: Added `RequireAdmin` to `GET /admin/users/list` (was completely unauthenticated — any user could list all users).
- **`admin.py`**: Added `RequireAdmin` to `GET /admin/use-ml` (was unauthenticated).
- **`performance.py`**: Added `RequireAdmin` to all 4 endpoints (`/admin/performance/csv`, `/json`, `/summary`, `/report`). The previous `_require_admin()` was a no-op placeholder.
- **`trip_history.py`**: Changed `CurrentUser` → `RequireAdmin` on both endpoints. Path is `/admin/trip-history/*` but any authenticated passenger could access.

#### 5. Bug Fixes
- **`yolo_detector.py`**: Added missing `face_count` and `head_blob_count` keys to HOG fallback result. The `analyze_bus_density_from_image()` function doesn't return these keys, but the mobile app expects them.
- **`performance.py`**: Fixed `for row in reader.append(row)` → `for row in reader: rows.append(row)` (syntax + logic error).

### 📊 Test Results
```
163 tests passing (all unit tests, excluding integration/performance)
- tests/test_eta_engine.py: 12 tests (NEW)
- tests/test_gps_validation.py: 18 tests (expanded from 6)
- tests/test_redis_fixes.py: 8 tests (NEW)
- All existing tests: still passing
```

### 📁 Files Changed (16 total)
1. `app/services/eta_engine.py` — ML feature fix, remove duplicate haversine
2. `app/services/route_eta.py` — O(n²)→O(n), speed minimum fix
3. `app/services/eta_calc.py` — Remove stray comment
4. `app/services/route_validation.py` — Relaxed threshold + segment projection
5. `app/services/image_pipeline.py` — Graceful GPS fallback
6. `app/services/redis_cache.py` — Stream MAXLEN
7. `app/services/yolo_detector.py` — Missing face_count key
8. `app/utils/redis_client.py` — FakeRedis xadd maxlen support
9. `app/api/v1/admin.py` — RequireAdmin on /admin/use-ml
10. `app/api/v1/admin_users.py` — RequireAdmin on /list
11. `app/api/v1/performance.py` — RequireAdmin on all 4 endpoints + syntax fix
12. `app/api/v1/trip_history.py` — RequireAdmin on both endpoints
13. `tests/test_eta_engine.py` — NEW: 12 ETA tests
14. `tests/test_gps_validation.py` — Expanded: 6→18 tests
15. `tests/test_redis_fixes.py` — NEW: 8 Redis tests
16. `tests/test_image_pipeline.py` — Updated: 2 tests for new GPS behavior

### ⚠️ Remaining Known Issues
- CI/CD: Migration step (`alembic upgrade head`) fails in CI — likely a conflict with existing indexes or migration chain issue
- ESP32 gateway integration test skipped in CI — requires DB
- YOLO single-thread executor — CV bottleneck
- No geocaching cache — repeated API calls
- Three separate simulation scripts with different API paths — inconsistent
- Simulation never sends images — CV pipeline never exercised
- Silent exception swallowing in `telemetry_ingest.py`
