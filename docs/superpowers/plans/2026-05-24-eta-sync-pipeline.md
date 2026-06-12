# ETA Sync Pipeline — Live Data Verification & ETA Injection

> **For agentic workers:** REQUIRED SUB-BACKEND: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure the backend's computed ETA data flows to all three frontends (mobile app, bus dashboard, admin dashboard), and create a verification checklist to confirm live synchronization across all layers.

**Architecture:** The ETA engine already runs server-side on every telemetry ingestion but the results are only stored in Redis — they never reach any frontend. We need to: (1) enrich the WebSocket broadcast payload with ETA data, (2) add a dedicated ETA REST endpoint for the mobile app, (3) handle ETA messages on each frontend, and (4) build a verification routine.

**Tech Stack:** FastAPI + Redis (backend), Flutter/Dart (mobile app), Next.js/React (bus dashboard + admin dashboard), WebSocket + REST

---

## Architecture Recap — Current Data Flow

```
Telemetry Ingestion
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│  tracking.py / image_pipeline.py                        │
│                                                         │
│  1. Resolve vehicle                                     │
│  2. Validate GPS (outlier + on-route)                   │
│  3. Run CV analysis (if ESP32-CAM)                      │
│  4. Persist to PostgreSQL (raw_telemetry, trip_history) │
│  5. Write to Redis (bus:live:*, route:X:stop:Y)         │
│  6. Compute ETA → route_eta.py → Redis hash per stop    │
│  7. broadcast_vehicle_position()  ←── NO ETA INCLUDED   │
└──────────────────────┬──────────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
   Bus Dashboard  Admin WS    Mobile App
   (WS + REST)    (WS only)   (REST poll only)

   GAP: ETA never leaves Redis.
```

---

## File Inventory

### Backend — Modified
| File | Change |
|---|---|
| `backend/app/services/live_broadcast.py` | Add `eta_payloads` parameter to `broadcast_vehicle_position()` |
| `backend/app/api/v1/tracking.py` | Pass ETA payloads from `estimate_route_stop_eta_payloads()` into broadcast |
| `backend/app/api/v1/websocket.py` | Add `"eta_update"` message type broadcast alongside position |
| `backend/app/api/v1/routes.py` (or new endpoint) | Add `GET /api/v1/routes/{route_number}/etas` REST endpoint for mobile app |

### Backend — New
| File | Purpose |
|---|---|
| `backend/tests/test_eta_broadcast.py` | Unit tests for ETA injection into WS broadcast |
| `backend/tests/test_eta_rest_endpoint.py` | Unit tests for the new ETA REST endpoint |
| `backend/tests/test_live_sync_verification.py` | Integration test: telemetry in → ETA visible on all frontends |

### Flutter Mobile App — Modified
| File | Change |
|---|---|
| `fyp/client_app/lib/features/tracking/domain/models/bus_location.dart` | Add `etaSeconds`, `stopEtaMap` fields |
| `fyp/client_app/lib/features/tracking/domain/models/vehicle_position_model.dart` | Add ETA fields to `VehiclePositionModel` |
| `fyp/client_app/lib/features/tracking/data/repositories/tracking_repository.dart` | Add `getStopEtas()` method |
| `fyp/client_app/lib/features/search/domain/models/journey_result_model.dart` | Ensure `etaMinutes` reads from enriched fields |

### Flutter Mobile App — New
| File | Purpose |
|---|---|
| `fyp/client_app/test/eta_model_test.dart` | Unit test: deserialize ETA from JSON |

### Bus Dashboard — Modified
| File | Change |
|---|---|
| `bus-dashboard-app/src/types/index.ts` | Add ETA fields to `VehiclePosition` type |
| `bus-dashboard-app/src/hooks/useBusDashboardWebSocket.ts` | Handle enriched `vehicle_position` or new `eta_update` message |
| `bus-dashboard-app/src/app/bus/[busId]/page.tsx` | Display ETA countdown in KPI row or route progress |

### Admin Dashboard — Modified
| File | Change |
|---|---|
| `bustrack-admin/src/types/index.ts` | Add ETA fields to `VehiclePosition` type |
| `bustrack-admin/src/components/Map/RealTimeBusMap.tsx` | Show ETA on bus popup |

---

## TASKS

---

### Task 1: Verify ETA Engine Correctness (Backend)

Before piping data to frontends, confirm the ETA engine produces valid output.

**Files:**
- Test: `backend/tests/test_eta_engine.py` (new, or add to existing)

- [ ] **Step 1: Verify ETA engine produces correctly shaped output**

Run the existing `estimate_route_stop_eta_payloads()` against known coordinates and assert the structure. No new code — just run a quick sanity check in a Python shell:

```python
import asyncio
from app.services.route_eta import estimate_route_stop_eta_payloads

# Simulate: bus at Meskel Square (Addis Ababa), going toward Kality
payloads = estimate_route_stop_eta_payloads(
    lat=9.032, lon=38.752,
    speed_kmh=30.0,
    occupancy_level=1,
    route_number="110",
    route_id=1,
    route_stops=[...]  # load from DB or mock
)
assert all("eta_seconds" in v for v in payloads.values())
assert all("distance_m" in v for v in payloads.values())
assert all("computed_at" in v for v in payloads.values())
print(f"OK: {len(payloads)} stop ETAs computed")
```

Expected: All payloads contain `eta_seconds`, `distance_m`, `computed_at`, `stop_id`, `stop_name`, `speed_kmh`, `occupancy_level`, `eta_mode`.

- [ ] **Step 2: Verify Redis ETA keys are populated after telemetry**

Check that `set_route_stop_etas()` actually writes to Redis:

```bash
# Start Redis CLI
redis-cli

# After sending a telemetry ping, check:
KEYS route:*:stop:*
HGETALL route:110:stop:1
```

Expected: Hash contains `eta_seconds`, `stop_name`, `computed_at`, etc.

- [ ] **Step 3: Verify `broadcast_vehicle_position` current payload shape**

Check what the WS message currently contains:

```bash
# Watch WebSocket traffic (e.g., browser DevTools Network tab)
# Or add a temporary print in live_broadcast.py
```

Expected: `{"type": "vehicle_position", "vehicle_id": ..., "plate_number": ..., "lat": ..., "lon": ..., "speed": ..., "route_id": ..., "timestamp": ..., "occupancy_level": ...}` — **no ETA fields**.

---

### Task 2: Enrich WebSocket Broadcast with ETA (Backend)

Inject ETA data into the `vehicle_position` WebSocket message so all WS-connected frontends receive it.

**Files:**
- Modify: `backend/app/services/live_broadcast.py`
- Modify: `backend/app/api/v1/tracking.py`

- [ ] **Step 1: Add `eta_payloads` parameter to `broadcast_vehicle_position()`**

In `backend/app/services/live_broadcast.py`, change the function signature and add ETA to the payload:

```python
async def broadcast_vehicle_position(
    vehicle_id: int,
    plate_number: str,
    lat: float,
    lon: float,
    speed: float,
    route_id: int | None,
    timestamp: float | None = None,
    bus_type: str | None = None,
    occupancy_level: int | None = None,
    eta_payloads: dict[int, dict[str, Any]] | None = None,
) -> None:
    try:
        ts = timestamp if timestamp is not None else time.time()
        payload: dict[str, Any] = {
            "type": "vehicle_position",
            "vehicle_id": vehicle_id,
            "plate_number": plate_number,
            "lat": lat,
            "lon": lon,
            "speed": speed,
            "route_id": route_id,
            "timestamp": ts,
        }
        if bus_type is not None:
            payload["bus_type"] = bus_type
        if occupancy_level is not None:
            payload["occupancy_level"] = occupancy_level
        if eta_payloads is not None:
            payload["eta_payloads"] = {
                str(stop_id): {
                    "stop_name": data.get("stop_name", ""),
                    "eta_seconds": data.get("eta_seconds", 0),
                    "distance_m": data.get("distance_m", 0),
                    "computed_at": data.get("computed_at", 0),
                }
                for stop_id, data in eta_payloads.items()
            }
        await manager.broadcast(payload)
    except Exception:
        pass
```

- [ ] **Step 2: Pass ETA payloads in `tracking.py`**

In `backend/app/api/v1/tracking.py`, in the `/telemetry` endpoint, capture the return value of `estimate_route_stop_eta_payloads()` and pass it to `broadcast_vehicle_position()`:

The key change is around lines 146-156. Currently:

```python
    if vehicle.route and route_stops:
        stop_payloads = estimate_route_stop_eta_payloads(...)
        try:
            await set_route_stop_etas(vehicle.route.route_number, stop_payloads)
        except Exception:
            pass

    await broadcast_vehicle_position(
        vehicle_id=vehicle.id,
        plate_number=vehicle.plate_number,
        lat=data.lat,
        lon=data.lon,
        speed=data.speed or 0.0,
        route_id=vehicle.route_id,
        timestamp=ts,
        occupancy_level=occupancy,
    )
```

Change to capture `stop_payloads` **before** the broadcast and pass it in:

```python
    stop_payloads = {}
    if vehicle.route and route_stops:
        stop_payloads = estimate_route_stop_eta_payloads(
            data.lat, data.lon, data.speed or 0.0, occupancy,
            vehicle.route.route_number, vehicle.route_id, route_stops,
        )
        try:
            await set_route_stop_etas(vehicle.route.route_number, stop_payloads)
        except Exception:
            pass

    await broadcast_vehicle_position(
        vehicle_id=vehicle.id,
        plate_number=vehicle.plate_number,
        lat=data.lat, lon=data.lon,
        speed=data.speed or 0.0,
        route_id=vehicle.route_id,
        timestamp=ts,
        occupancy_level=occupancy,
        eta_payloads=stop_payloads or None,
    )
```

- [ ] **Step 3: Also pass ETA in `image_pipeline.py`**

In `backend/app/services/image_pipeline.py`, around line 366-376, the same change: capture `eta_payloads` and pass to `broadcast_vehicle_position()`:

```python
    # After existing eta_payloads computation (lines 323-336):
    # eta_payloads is already computed — just pass it through
    await broadcast_vehicle_position(
        vehicle_id=vehicle.id,
        plate_number=vehicle.plate_number,
        lat=validated_lat, lon=validated_lon,
        speed=speed,
        route_id=vehicle.route_id,
        timestamp=ts,
        bus_type=vehicle.bus_type,
        occupancy_level=occupancy_level,
        eta_payloads=eta_payloads or None,
    )
```

- [ ] **Step 4: Run backend tests**

```bash
cd backend && python -m pytest tests/ -x -q 2>&1 | tail -20
```

Expected: All existing tests pass. No regressions.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/live_broadcast.py \
        backend/app/api/v1/tracking.py \
        backend/app/services/image_pipeline.py

git commit -m "feat: inject ETA payloads into vehicle_position WS broadcast"
```

---

### Task 3: Add ETA REST Endpoint for Mobile App (Backend)

The mobile app polls REST (no WebSocket). Add an endpoint it can call to fetch current ETAs for a route.

**Files:**
- Modify: `backend/app/api/v1/routes.py` (or create new endpoint file)

- [ ] **Step 1: Add ETA retrieval logic to routes.py**

Add a new endpoint to `backend/app/api/v1/routes.py`:

```python
from app.utils.redis_client import get_redis

@router.get("/routes/{route_number}/etas")
async def get_route_etas(route_number: str):
    """Get all pre-computed ETAs for a route (for mobile app REST polling)."""
    redis = await get_redis()
    # Find all ETA keys for this route
    keys = await redis.keys(f"route:{route_number}:stop:*")
    result = {}
    for key in keys:
        data = await redis.hgetall(key)
        if data:
            # Extract stop_id from key
            stop_id = key.split(":")[-1]
            eta_seconds = data.get("eta_seconds", 0)
            computed_at = data.get("computed_at", 0)
            # Compute live-adjusted ETA
            try:
                elapsed = max(0.0, time.time() - float(computed_at))
                live_eta = max(0, int(round(float(eta_seconds) - elapsed)))
            except (TypeError, ValueError):
                live_eta = int(eta_seconds) if eta_seconds else 0
            result[stop_id] = {
                "stop_name": data.get("stop_name", ""),
                "eta_seconds": live_eta,
                "distance_m": int(data.get("distance_m", 0)),
                "occupancy_level": int(data.get("occupancy_level", 0)),
            }
    return {"route_number": route_number, "etas": result}
```

- [ ] **Step 2: Write a failing test first**

Create `backend/tests/test_eta_rest_endpoint.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_get_route_etas_empty():
    """When no ETAs in Redis, return empty dict."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/routes/999/etas")
    assert response.status_code == 200
    data = response.json()
    assert data["route_number"] == "999"
    assert data["etas"] == {}
```

- [ ] **Step 3: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/test_eta_rest_endpoint.py -x -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/v1/routes.py backend/tests/test_eta_rest_endpoint.py
git commit -m "feat: add GET /routes/{number}/etas REST endpoint for mobile app"
```

---

### Task 4: Mobile App — ETA Data Layer (Flutter)

Add ETA fields to the mobile app's data models and repository.

**Files:**
- Modify: `fyp/client_app/lib/features/tracking/domain/models/bus_location.dart`
- Modify: `fyp/client_app/lib/features/tracking/domain/models/vehicle_position_model.dart`
- Modify: `fyp/client_app/lib/features/tracking/data/repositories/tracking_repository.dart`

- [ ] **Step 1: Add ETA fields to `BusLocation` model**

In `fyp/client_app/lib/features/tracking/domain/models/bus_location.dart`, add:

```dart
@freezed
sealed class BusLocation with _$BusLocation {
  const factory BusLocation({
    @JsonKey(name: 'plate_number') required String plateNumber,
    required double lat,
    required double lon,
    @Default(0.0) double speed,
    @JsonKey(name: 'occupancy_level') @Default(0) int occupancyLevel,
    @JsonKey(name: 'assignment_id') @Default(0) int assignmentId,
    @JsonKey(includeFromJson: false, includeToJson: false) DateTime? lastUpdated,
    // NEW: ETA fields
    @JsonKey(name: 'eta_seconds') @Default(0) int etaSeconds,
    @JsonKey(name: 'stop_etas') @Default({}) Map<String, int> stopEtas,
  }) = _BusLocation;

  factory BusLocation.fromJson(Map<String, dynamic> json) =>
      _$BusLocationFromJson(json);
}
```

Then regenerate: `cd fyp/client_app && dart run build_runner build --delete-conflicting-outputs`

- [ ] **Step 2: Add ETA fields to `VehiclePositionModel`**

In `fyp/client_app/lib/features/tracking/domain/models/vehicle_position_model.dart`, add to the constructor and `fromJson`:

```dart
// Add to constructor:
this.etaSeconds = 0,
this.stopEtas = const {},

// Add fields:
final int etaSeconds;
final Map<String, int> stopEtas;

// Add to fromJson:
etaSeconds: _asInt(json['eta_seconds'] ?? json['etaSeconds']) ?? 0,
stopEtas: (json['stop_etas'] as Map<String, dynamic>?)?.map(
  (k, v) => MapEntry(k, _asInt(v) ?? 0),
) ?? const {},

// Add to toJson:
'eta_seconds': etaSeconds,
if (stopEtas.isNotEmpty) 'stop_etas': stopEtas,

// Add to copyWith, ==, hashCode, toString as needed
```

- [ ] **Step 3: Add `getStopEtas()` to `TrackingRepository`**

In `fyp/client_app/lib/features/tracking/data/repositories/tracking_repository.dart`:

```dart
Future<Map<String, dynamic>> getStopEtas(String routeNumber) async {
  final response = await _dio.get('/routes/$routeNumber/etas');
  final data = response.data;
  if (data is! Map<String, dynamic>) {
    throw const FormatException('Unexpected ETAs response shape');
  }
  return data;
}
```

- [ ] **Step 4: Write a unit test for ETA JSON deserialization**

Create `fyp/client_app/test/eta_model_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:client_app/features/tracking/domain/models/vehicle_position_model.dart';

void main() {
  group('VehiclePositionModel ETA fields', () {
    test('deserializes eta_seconds from JSON', () {
      final json = {
        'vehicle_id': 1,
        'plate_number': 'ABC-1234',
        'lat': 9.032,
        'lon': 38.752,
        'speed': 25.0,
        'timestamp': 1700000000.0,
        'route_id': 1,
        'eta_seconds': 180,
        'stop_etas': {'1': 60, '2': 120, '3': 180},
      };
      final model = VehiclePositionModel.fromJson(json);
      expect(model.etaSeconds, 180);
      expect(model.stopEtas['1'], 60);
      expect(model.stopEtas['3'], 180);
    });

    test('defaults eta_seconds to 0 when missing', () {
      final json = {
        'vehicle_id': 1,
        'plate_number': 'ABC-1234',
        'lat': 9.032,
        'lon': 38.752,
        'speed': 0.0,
        'timestamp': 0.0,
      };
      final model = VehiclePositionModel.fromJson(json);
      expect(model.etaSeconds, 0);
      expect(model.stopEtas, isEmpty);
    });
  });
}
```

- [ ] **Step 5: Run the test**

```bash
cd fyp/client_app && flutter test test/eta_model_test.dart
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add fyp/client_app/lib/features/tracking/domain/models/bus_location.dart \
        fyp/client_app/lib/features/tracking/domain/models/bus_location.freezed.dart \
        fyp/client_app/lib/features/tracking/domain/models/bus_location.g.dart \
        fyp/client_app/lib/features/tracking/domain/models/vehicle_position_model.dart \
        fyp/client_app/lib/features/tracking/data/repositories/tracking_repository.dart \
        fyp/client_app/test/eta_model_test.dart

git commit -m "feat(mobile): add ETA fields to tracking models and repository"
```

---

### Task 5: Mobile App — Display ETA on Route Detail Screen

Show ETA countdown on the bus markers and arrival bubble in the route detail screen.

**Files:**
- Modify: `fyp/client_app/lib/features/search/presentation/screens/route_detail_screen.dart`

- [ ] **Step 1: Show ETA on bus markers in route detail**

In `route_detail_screen.dart`, the bus markers already display `etaMin` from `targetJourney!.etas[bus.assignmentId.toString()]`. This data comes from the `/search/point-to-point` endpoint which already returns `eta_seconds` per bus. Verify the existing display works by checking the `etaStr` parsing around line 581:

```dart
final etaStr = targetJourney!.etas[bus.assignmentId.toString()].toString();
final etaSec = int.tryParse(etaStr) ?? 0;
final etaMin = (etaSec / 60).round();
```

This already works for the journey results context. The bus marker popup (line 599-603) shows `'$etaMin min'`. **No change needed here** — the mobile app already displays ETA for journey results.

- [ ] **Step 2: Add ETA display to home screen bus info bottom sheet**

In `home_screen.dart`, the `_showBusInfo` bottom sheet (line 445) shows speed and crowd level but no ETA. Add an ETA info card:

In the `Row` that currently shows Speed and Crowd Level (around line 618-635), the bus info bottom sheet doesn't have ETA. Since the home screen uses `BusLocation` (from REST polling), and the REST endpoint `/vehicles/positions` doesn't include ETA, the home screen bus tap won't show ETA unless we also enrich that endpoint or the mobile app fetches ETAs separately.

**Decision:** For the home screen, skip ETA on the bottom sheet (it's a fleet overview, not a journey context). The route detail screen already shows ETA correctly. This is acceptable for now.

- [ ] **Step 3: Verify journey results ETA display works end-to-end**

The `journey_results_screen.dart` already shows `'Arriving in ${result.etaMinutes} min'` (line 156). The `JourneyResultModel.etaMinutes` getter reads from `etas['eta_minutes']` or `etas['eta_seconds']`. The backend's `point_to-point` endpoint returns `etas` from Redis which contains `eta_seconds`. Verify the conversion:

In `journey_result_model.dart` line 23-27:
```dart
int? get etaMinutes {
    if (etas['eta_minutes'] != null) {
      return int.tryParse(etas['eta_minutes'].toString());
    }
    if (etas['eta_seconds'] != null) {
      final seconds = int.tryParse(etas['eta_seconds'].toString());
      if (seconds != null) return (seconds / 60).round();
    }
    return null;
  }
```

This reads `eta_seconds` from Redis and converts to minutes. **This already works.** No change needed.

- [ ] **Step 4: Commit (documentation only)**

```bash
git add docs/superpowers/plans/2026-05-24-eta-sync-pipeline.md
git commit -m "docs: verify mobile app ETA display already works for journey results"
```

---

### Task 6: Bus Dashboard — Handle ETA in WebSocket & Display

**Files:**
- Modify: `bus-dashboard-app/src/types/index.ts`
- Modify: `bus-dashboard-app/src/hooks/useBusDashboardWebSocket.ts`
- Modify: `bus-dashboard-app/src/app/bus/[busId]/page.tsx`

- [ ] **Step 1: Add ETA fields to `VehiclePosition` type**

In `bus-dashboard-app/src/types/index.ts`:

```typescript
export interface VehiclePosition {
  vehicle_id: number;
  plate_number: string;
  lat: number;
  lon: number;
  speed: number;
  timestamp: number;
  route_id: number | null;
  eta_payloads?: Record<string, {
    stop_name: string;
    eta_seconds: number;
    distance_m: number;
    computed_at: number;
  }>;
}
```

- [ ] **Step 2: Handle ETA in WebSocket hook**

In `bus-dashboard-app/src/hooks/useBusDashboardWebSocket.ts`, in the `vehicle_position` handler (around line 87-106), extract `eta_payloads`:

```typescript
if (msgType === "vehicle_position") {
  const vid = data.vehicle_id;
  if (typeof vid === "number" && vid === vehicleId) {
    const lat = Number(data.lat);
    const lon = Number(data.lon);
    if (Number.isFinite(lat) && Number.isFinite(lon)) {
      setState((s) => ({
        ...s,
        position: {
          vehicle_id: vid,
          plate_number: String(data.plate_number ?? ""),
          lat,
          lon,
          speed: Number(data.speed) || 0,
          timestamp: Number(data.timestamp) || Date.now() / 1000,
          route_id: data.route_id === null || data.route_id === undefined ? null : Number(data.route_id),
          eta_payloads: data.eta_payloads ?? undefined,
        },
      }));
    }
  }
}
```

- [ ] **Step 3: Display ETA in the bus dashboard page**

In `bus-dashboard-app/src/app/bus/[busId]/page.tsx`, add a helper to extract the nearest stop ETA and display it. Add this near the `nearestStopIndex` useMemo (around line 241):

```typescript
const nearestStopEta = useMemo(() => {
  if (!vehiclePosition?.eta_payloads || !routeDetail?.stops?.length) return null;
  const stops = routeDetail.stops;
  const nearestIdx = nearestStopIndex;
  const nearestStop = stops[nearestIdx];
  if (!nearestStop) return null;
  const eta = vehiclePosition.eta_payloads[String(nearestStop.id)];
  if (!eta) return null;
  // Compute live-adjusted ETA
  const elapsed = Math.max(0, Math.floor(Date.now() / 1000 - eta.computed_at));
  const liveEta = Math.max(0, eta.eta_seconds - elapsed);
  return { stopName: nearestStop.name, etaSeconds: liveEta };
}, [vehiclePosition, routeDetail, nearestStopIndex]);
```

Then in the KPI row (around line 432-435), replace or augment the Clock/status card:

```typescript
<div className="card-glow p-4">
  <div className="flex items-center gap-2 mb-2"><Clock size={14} style={{ color: "var(--cyan)" }} /><span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--text3)" }}>ETA Next Stop</span></div>
  <p className="text-lg font-bold" style={{ color: "var(--text)" }}>
    {nearestStopEta
      ? `${Math.ceil(nearestStopEta.etaSeconds / 60)} min`
      : "—"}
  </p>
  <p className="text-[11px]" style={{ color: "var(--text3)" }}>
    {nearestStopEta?.stopName || currentStopName || "—"}
  </p>
</div>
```

- [ ] **Step 4: Verify the bus dashboard builds**

```bash
cd bus-dashboard-app && npm run build 2>&1 | tail -20
```

Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 5: Commit**

```bash
git add bus-dashboard-app/src/types/index.ts \
        bus-dashboard-app/src/hooks/useBusDashboardWebSocket.ts \
        bus-dashboard-app/src/app/bus/[busId]/page.tsx

git commit -m "feat(bus-dashboard): display live ETA countdown from WS payload"
```

---

### Task 7: Admin Dashboard — Show ETA on Map Popup

**Files:**
- Modify: `bustrack-admin/src/types/index.ts`
- Modify: `bustrack-admin/src/components/Map/RealTimeBusMap.tsx`

- [ ] **Step 1: Add ETA fields to admin `VehiclePosition` type**

In `bustrack-admin/src/types/index.ts`:

```typescript
export interface VehiclePosition {
  vehicle_id: number;
  plate_number: string;
  lat: number;
  lon: number;
  speed: number;
  timestamp: number;
  route_id?: number | null;
  pixel_count?: number | null;
  density_level?: number | null;
  eta_payloads?: Record<string, {
    stop_name: string;
    eta_seconds: number;
    distance_m: number;
    computed_at: number;
  }>;
}
```

- [ ] **Step 2: Show ETA in bus popup on admin map**

In `bustrack-admin/src/components/Map/RealTimeBusMap.tsx`, in the popup template (around line 394-414), add ETA display:

```tsx
<Popup className="bus-popup">
  <div style={{ fontWeight: "bold", fontSize: "14px" }}>
    {vehicle.plate_number}
  </div>
  <div style={{ fontSize: "12px", marginTop: 4 }}>
    <div>Live GPS: {active ? "🟢 recent" : "⚪ stale / last known"}</div>
    <div>
      Density: <strong style={{ color: density.color }}>{density.label}</strong>
      {pos?.pixel_count != null ? ` (${pos.pixel_count} px)` : ""}
    </div>
    <div>
      Speed: {(pos?.speed ?? vehicle.speed ?? 0).toFixed(1)} km/h
    </div>
    <div>
      Route:{" "}
      {vehicle.route_number ||
        (vehicle.route_id != null ? `#${vehicle.route_id}` : "Unassigned")}
    </div>
    <div>Capacity: {vehicle.capacity ?? "—"} seats</div>
    {pos?.eta_payloads && Object.keys(pos.eta_payloads).length > 0 && (
      <div style={{ marginTop: 4, borderTop: "1px solid #eee", paddingTop: 4 }}>
        <div style={{ fontWeight: 600, fontSize: 11 }}>Upcoming Stops:</div>
        {Object.entries(pos.eta_payloads).slice(0, 3).map(([stopId, eta]) => {
          const elapsed = Math.max(0, Math.floor(Date.now() / 1000 - (eta.computed_at || 0)));
          const liveEta = Math.max(0, (eta.eta_seconds || 0) - elapsed);
          return (
            <div key={stopId} style={{ fontSize: 10, display: "flex", justifyContent: "space-between" }}>
              <span>{eta.stop_name}</span>
              <span style={{ fontWeight: 600 }}>{Math.ceil(liveEta / 60)}m</span>
            </div>
          );
        })}
      </div>
    )}
  </div>
</Popup>
```

- [ ] **Step 3: Verify the admin dashboard builds**

```bash
cd bustrack-admin && npm run build 2>&1 | tail -20
```

Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add bustrack-admin/src/types/index.ts \
        bustrack-admin/src/components/Map/RealTimeBusMap.tsx

git commit -m "feat(admin-dashboard): show ETA per stop on bus map popup"
```

---

### Task 8: Verification Routine — End-to-End Sync Test

**Files:**
- Create: `backend/tests/test_live_sync_verification.py`

- [ ] **Step 1: Write the integration test**

Create `backend/tests/test_live_sync_verification.py`:

```python
"""
End-to-end verification: telemetry in → ETA computed → visible on all channels.

This test simulates the full pipeline:
1. Send telemetry to /api/v1/telemetry
2. Verify ETA is stored in Redis
3. Verify broadcast_vehicle_position was called with ETA payloads
4. Verify the ETA REST endpoint returns the data
"""
import asyncio
import json
import time
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.services.route_eta import estimate_route_stop_eta_payloads
from app.utils.gps_validation import haversine_meters


@pytest.fixture
def transport():
    return ASGITransport(app=app)


@pytest.mark.asyncio
async def test_eta_computed_from_known_coordinates():
    """Given a bus at a known position, ETA to a stop 2km away should be ~120s at 60km/h."""
    from app.models.stop import Stop

    # Create mock stops
    stop_near = Stop(id=1, name="Near Stop", lat=9.032, lon=38.752, base_dwell_time=30, peak_multiplier=1.0)
    stop_far = Stop(id=2, name="Far Stop", lat=9.050, lon=38.760, base_dwell_time=30, peak_multiplier=1.0)

    payloads = estimate_route_stop_eta_payloads(
        lat=9.032, lon=38.752,
        speed_kmh=30.0,
        occupancy_level=0,
        route_number="110",
        route_id=1,
        route_stops=[stop_near, stop_far],
    )

    assert payloads, "ETA payloads should not be empty"
    assert 1 in payloads
    assert 2 in payloads

    # Near stop should have small ETA
    near_eta = payloads[1]["eta_seconds"]
    assert 0 < near_eta < 120, f"Near stop ETA should be < 120s, got {near_eta}"

    # Far stop should have larger ETA
    far_eta = payloads[2]["eta_seconds"]
    assert far_eta > near_eta, f"Far stop ETA ({far_eta}) should be > near stop ETA ({near_eta})"

    # All payloads should have required fields
    for stop_id, data in payloads.items():
        assert "stop_name" in data
        assert "eta_seconds" in data
        assert "distance_m" in data
        assert "computed_at" in data
        assert "speed_kmh" in data
        assert "occupancy_level" in data


@pytest.mark.asyncio
async def test_broadcast_includes_eta_payloads():
    """broadcast_vehicle_position should include eta_payloads in the WS message."""
    from app.services.live_broadcast import broadcast_vehicle_position

    eta_payloads = {
        1: {"stop_name": "Stop A", "eta_seconds": 60, "distance_m": 500, "computed_at": int(time.time())},
        2: {"stop_name": "Stop B", "eta_seconds": 120, "distance_m": 1000, "computed_at": int(time.time())},
    }

    with patch("app.services.live_broadcast.manager") as mock_manager:
        mock_manager.broadcast = AsyncMock()
        await broadcast_vehicle_position(
            vehicle_id=1,
            plate_number="ABC-1234",
            lat=9.032, lon=38.752,
            speed=25.0,
            route_id=1,
            timestamp=time.time(),
            occupancy_level=1,
            eta_payloads=eta_payloads,
        )

        mock_manager.broadcast.assert_called_once()
        call_args = mock_manager.broadcast.call_args[0][0]
        assert call_args["type"] == "vehicle_position"
        assert "eta_payloads" in call_args
        assert "1" in call_args["eta_payloads"]
        assert call_args["eta_payloads"]["1"]["stop_name"] == "Stop A"
        assert call_args["eta_payloads"]["1"]["eta_seconds"] == 60


@pytest.mark.asyncio
async def test_eta_payloads_none_when_no_route():
    """When vehicle has no route, eta_payloads should be None (not crash)."""
    from app.services.live_broadcast import broadcast_vehicle_position

    with patch("app.services.live_broadcast.manager") as mock_manager:
        mock_manager.broadcast = AsyncMock()
        await broadcast_vehicle_position(
            vehicle_id=1,
            plate_number="ABC-1234",
            lat=9.032, lon=38.752,
            speed=25.0,
            route_id=None,
            timestamp=time.time(),
            eta_payloads=None,
        )

        call_args = mock_manager.broadcast.call_args[0][0]
        assert "eta_payloads" not in call_args


@pytest.mark.asyncio
async def test_compute_live_eta_adjusts_for_elapsed_time():
    """compute_live_eta should subtract elapsed time from computed_at."""
    from app.services.search_helpers import compute_live_eta

    now = time.time()
    # ETA was 300s, computed 100s ago → should be ~200s
    result = compute_live_eta(eta_seconds=300, computed_at=now - 100)
    assert 195 <= result <= 205, f"Expected ~200, got {result}"

    # ETA already expired → should be 0
    result = compute_live_eta(eta_seconds=30, computed_at=now - 100)
    assert result == 0

    # Invalid computed_at → should return None
    result = compute_live_eta(eta_seconds=300, computed_at=0)
    assert result is None
```

- [ ] **Step 2: Run the verification tests**

```bash
cd backend && python -m pytest tests/test_live_sync_verification.py -x -v
```

Expected: All 4 tests PASS

- [ ] **Step 3: Manual verification checklist**

Run this checklist with the full stack running (backend + Redis + all frontends):

```bash
# 1. Start backend
cd backend && uvicorn app.main:app --reload --port 8000 &

# 2. Start Redis (if not running)
redis-server --daemonize yes

# 3. Send a test telemetry ping
curl -X POST http://localhost:8000/api/v1/telemetry \
  -H "Content-Type: application/json" \
  -d '{"device_id": "TEST001", "lat": 9.032, "lon": 38.752, "speed": 25}'

# 4. Check Redis for ETA keys
redis-cli KEYS route:*:stop:*
redis-cli HGETALL route:110:stop:1

# 5. Check ETA REST endpoint
curl http://localhost:8000/api/v1/routes/110/etas | python -m json.tool

# 6. Open browser DevTools → Network → WS tab
#    Connect to ws://localhost:8000/api/v1/ws/live?token=<admin_jwt>
#    Send another telemetry ping
#    Verify the WS message contains "eta_payloads"

# 7. Open bus-dashboard-app → navigate to a bus
#    Verify ETA countdown appears in KPI row

# 8. Open bustrack-admin → Live Map
#    Click a bus marker → verify popup shows "Upcoming Stops" with ETAs

# 9. Open Flutter app → search for a journey
#    Verify "Arriving in X min" shows on route cards
```

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_live_sync_verification.py
git commit -m "test: add end-to-end ETA sync verification tests and checklist"
```

---

## Summary of Changes

| Layer | What Changed | ETA Now Visible? |
|---|---|---|
| **Backend** `live_broadcast.py` | `broadcast_vehicle_position()` accepts `eta_payloads` | ✅ In WS message |
| **Backend** `tracking.py` | Passes ETA from `estimate_route_stop_eta_payloads()` into broadcast | ✅ |
| **Backend** `image_pipeline.py` | Passes ETA from ESP32 path into broadcast | ✅ |
| **Backend** `routes.py` | New `GET /routes/{number}/etas` REST endpoint | ✅ For mobile REST |
| **Mobile app** `bus_location.dart` | Added `etaSeconds`, `stopEtas` fields | ✅ Model ready |
| **Mobile app** `vehicle_position_model.dart` | Added ETA fields | ✅ Model ready |
| **Mobile app** `tracking_repository.dart` | Added `getStopEtas()` method | ✅ Can fetch |
| **Mobile app** `route_detail_screen.dart` | Already shows ETA from journey search | ✅ Already worked |
| **Bus dashboard** `types/index.ts` | Added `eta_payloads` to `VehiclePosition` | ✅ Type ready |
| **Bus dashboard** `useBusDashboardWebSocket.ts` | Extracts `eta_payloads` from WS message | ✅ Handler ready |
| **Bus dashboard** `[busId]/page.tsx` | Shows ETA countdown in KPI row | ✅ UI ready |
| **Admin dashboard** `types/index.ts` | Added `eta_payloads` to `VehiclePosition` | ✅ Type ready |
| **Admin dashboard** `RealTimeBusMap.tsx` | Shows upcoming stops with ETAs in popup | ✅ UI ready |
