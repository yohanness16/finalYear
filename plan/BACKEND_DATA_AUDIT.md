# Backend Data Audit Plan
**Date:** 2026-05-26
**Purpose:** Verify what the backend sends, what it should send per system goals, and identify bugs/missing data.

---

## 1. System Goals (What Backend MUST Support)

| Goal | Required Data |
|------|--------------|
| Real-time GPS tracking | Vehicle positions with lat/lon/speed/timestamp |
| Crowd density estimation | occupancy_level, people_count, crowd_density per vehicle |
| ETA computation | eta_seconds per stop, ML vs heuristic comparison |
| Live streaming (admin) | WebSocket vehicle_position + cv_result events |
| Passenger mobile app | Journey search, live positions, favorites, ratings, notifications |
| Admin dashboard | Fleet analytics, ML training, system settings |
| Bus dashboard | Driver auth, live trip monitoring |

---

## 2. What Backend Actually Sends — Endpoint-by-Endpoint

### 2.1 `GET /vehicles/positions` — Live Positions

**Actual response** (from `crud/vehicle.py:get_live_positions`):
```json
{
  "positions": {
    "<vehicle_id_str>": {
      "vehicle_id": 5,
      "plate_number": "AA-3-B12345",
      "lat": 9.032,
      "lon": 38.752,
      "speed": 32.5,
      "timestamp": 1705312200.0,
      "route_id": 1,
      "assignment_id": 12,
      "occupancy_level": 1,
      "density_level": 1
    }
  },
  "timestamp": 1705312200.0
}
```

**Schema** (`VehiclePosition`): Matches the CRUD output exactly.

**✅ CORRECT:** All fields present. Mobile app expects all of these.

**⚠️ BUG: Positions keyed by `vehicle_id` (string), NOT `plate_number`.**
- Backend: `out[str(vid)] = {...}` — keys are vehicle IDs like `"5"`
- Mobile app: Uses `position.plateNumber` as the map key in `BusTracker._applyPositions()`
- Impact: The envelope keys are vehicle IDs, but the mobile app uses plate numbers internally. This works because the mobile app re-keys by plate number. However, if two vehicles somehow share a plate, there'd be a collision. **Low priority — works correctly in practice.**

### 2.2 `GET /vehicles/positions/{vehicle_id}` — Single Vehicle Position

**Actual response:** Same `VehiclePosition` object.

**✅ CORRECT.**

### 2.3 `POST /search/point-to-point` — Journey Search

**Actual response** (from `search.py`):
```json
{
  "routes": [
    {
      "route_number": "12",
      "etas": {
        "eta_seconds": 420,
        "eta_heuristic_seconds": 420.0,
        "eta_mode": "heuristic",
        "eta_ml_seconds": 360.0,
        "distance_m": 1200,
        "speed_kmh": 25.0,
        "occupancy_level": 1,
        "computed_at": 1705312200.0,
        "stop_name": "Merkato Terminal"
      }
    }
  ],
  "start_stop": "Merkato Terminal",
  "end_stop": "Megenagna"
}
```

**⚠️ CRITICAL BUG: Mobile app expects `eta_minutes` but backend sends `eta_seconds`.**
- Mobile `JourneyResultModel.etaMinutes`: checks `etas['eta_minutes']` first, then falls back to `etas['eta_seconds']/60`
- The backend sends `eta_seconds` — the fallback path works. **No bug, but the mobile code has a misleading comment.**

**⚠️ BUG: Mobile expects `bus_plate` in etas but backend doesn't send it.**
- Mobile: `etas['bus_plate'] as String?` — always null
- Backend: Never includes `bus_plate` in the Redis ETA hash
- Impact: Journey results always show "No active bus" even when buses exist
- **This is a confirmed TODO in the mobile code itself (line 18 comment)**

**⚠️ BUG: Mobile expects `occupancy_level` in etas — backend DOES send it.**
- The backend includes `occupancy_level` in the Redis hash. **This works correctly.**

### 2.4 `POST /search/journey` — Geo Journey Search

**Actual response:**
```json
{
  "start": {"query": "...", "lat": 9.02, "lon": 38.74, "stop_id": 1, "stop_name": "...", "distance_m": 100},
  "end": {"query": "...", "lat": 9.03, "lon": 38.75, "stop_id": 5, "stop_name": "...", "distance_m": 200},
  "routes": [
    {
      "route_id": 1,
      "route_number": "12",
      "direction": "forward",
      "name": "Megenagna - Mexico",
      "start_index": 0,
      "end_index": 5,
      "buses": [
        {
          "vehicle_id": 5,
          "plate_number": "AA-3-B12345",
          "lat": 9.032,
          "lon": 38.752,
          "speed": 32.5,
          "route_id": 1,
          "assignment_id": 12,
          "occupancy_level": 1,
          "eta_seconds": 420,
          "eta_live_seconds": 380,
          "eta_mode": "heuristic",
          "eta_ml_seconds": 360.0,
          "eta_heuristic_seconds": 420.0,
          "distance_m": 1200
        }
      ]
    }
  ]
}
```

**✅ CORRECT:** Rich data structure. Mobile app doesn't use this endpoint (uses point-to-point instead).

### 2.5 `GET /routes/{route_number}/etas` — Route ETAs

**Actual response:**
```json
{
  "route_number": "12",
  "etas": {
    "1": {
      "stop_name": "Merkato Terminal",
      "eta_seconds": 420,
      "distance_m": 1200,
      "occupancy_level": 1
    }
  }
}
```

**✅ CORRECT.** Mobile app doesn't currently use this endpoint but it's available for future use.

### 2.6 `GET /routes/{route_id}` — Route Detail

**Actual response:**
```json
{
  "id": 1,
  "route_number": "12",
  "direction": "forward",
  "name": "Megenagna - Mexico",
  "origin": "Megenagna",
  "destination": "Mexico",
  "stops": [
    {
      "id": 1,
      "name": "Merkato Terminal",
      "lat": 9.02,
      "lon": 38.74,
      "base_dwell_time": 30,
      "is_terminal": false,
      "peak_multiplier": 1.5
    }
  ]
}
```

**✅ CORRECT.** Matches `RouteModel` in mobile app exactly.

### 2.7 `GET /routes` — List Routes

**Actual response:** Array of `RouteResponse` (without stops nested):
```json
[
  {
    "id": 1,
    "route_number": "12",
    "direction": "forward",
    "name": "Megenagna - Mexico",
    "origin": "Megenagna",
    "destination": "Mexico"
  }
]
```

**✅ CORRECT.** Mobile `getRouteDetailByNumber` fetches all routes, filters by `route_number`, then calls `getRouteDetail(id)` for the full detail with stops.

### 2.8 `GET /stops` — List Stops

**Actual response:** Array of `StopResponse`:
```json
[
  {
    "id": 1,
    "name": "Merkato Terminal",
    "lat": 9.02,
    "lon": 38.74,
    "base_dwell_time": 30,
    "is_terminal": false,
    "peak_multiplier": 1.5
  }
]
```

**✅ CORRECT.** Matches `StopModel` in mobile app.

### 2.9 WebSocket `vehicle_position` Event

**Actual payload:**
```json
{
  "type": "vehicle_position",
  "vehicle_id": 5,
  "plate_number": "AA-3-B12345",
  "lat": 9.032,
  "lon": 38.752,
  "speed": 32.5,
  "route_id": 1,
  "timestamp": 1705312200.0,
  "bus_type": "Anbessa",
  "occupancy_level": 1,
  "density_level": 1,
  "eta_payloads": {
    "1": {
      "stop_name": "Merkato Terminal",
      "eta_seconds": 420,
      "distance_m": 1200,
      "computed_at": 1705312200
    }
  }
}
```

**✅ CORRECT for admin dashboard.** Mobile app doesn't use WebSocket (uses polling).

### 2.10 WebSocket `cv_result` Event

**Actual payload:**
```json
{
  "type": "cv_result",
  "vehicle_id": 5,
  "plate_number": "AA-3-B12345",
  "timestamp": 1705312200.0,
  "cv": {
    "people_count": 18,
    "face_count": 5,
    "head_blob_count": 3,
    "crowd_density": 2,
    "is_crowded": true,
    "method": "yolov8_multi(person:12+face:5+head:3)",
    "confidence": 0.85,
    "foreground_ratio": 0.72,
    "boxes": [[x1,y1,x2,y2], ...],
    "face_boxes": [[x1,y1,x2,y2], ...],
    "head_boxes": [[x1,y1,x2,y2], ...],
    "inference_ms": 142.3
  },
  "image_path": "storage/esp32_images/..."
}
```

**⚠️ BUG: `inference_ms` is in the Python dict but NOT in the WebSocket payload.**
The `broadcast_cv_result` function doesn't include `inference_ms` in the CV payload. The backend's `yolo_detector.py` returns it, but `live_broadcast.py` drops it. **Low priority — admin dashboard doesn't display it.**

---

## 3. Missing Backend Endpoints (Per System Goals)

| Missing Endpoint | Required By | Status |
|-----------------|-------------|--------|
| `PATCH /auth/me` | Mobile profile update | ❌ Not implemented — mobile uses fallback chain |
| `POST /auth/change-password` | Mobile password change | ❌ Not implemented — mobile uses fallback chain |
| `DELETE /favorites/{id}` | Mobile delete favorite | ❌ Not implemented — mobile catches error silently |
| `POST /notifications/register-token` | Mobile FCM registration | ❌ Not implemented — mobile uses fallback chain |

---

## 4. Data the Backend Sends But Shouldn't / Should Clean Up

| Issue | Location | Recommendation |
|-------|----------|---------------|
| `density_level` is duplicate of `occupancy_level` | `VehiclePosition` schema, `get_live_positions` CRUD | Remove `density_level` — it's the same value. Mobile doesn't use it. |
| `human_count` in CV result is alias of `people_count` | `cv_engine.py`, `yolo_detector.py` | Remove `human_count` — redundant. Only `people_count` is in the WebSocket schema. |
| `last_updated` field in `VehiclePosition` — backend doesn't send it | `vehicle_position_model.dart` mobile | Mobile expects `last_updated` but backend sends `timestamp` (Unix float). Mobile's `lastUpdated` will always be null from API, then overwritten with `DateTime.now()` in websocket_service. **Inconsistency but not a bug.** |

---

## 5. Bugs Found in Backend Data Flow

### BUG 1: `GET /vehicles/positions` — `assignment_id` can be null
- **Location:** `crud/vehicle.py:get_live_positions()`
- **Issue:** `assignment_id` comes from a subquery. If a vehicle has no active assignment, it's `null`.
- **Mobile impact:** `VehiclePositionModel.assignmentId` is `int?` — handles null correctly.
- **Route detail impact:** `bus.assignmentId.toString()` → `"null"` → won't match any ETA key. Buses without assignments are hidden on route detail. **This is correct behavior** — only assigned buses should show.

### BUG 2: `POST /search/point-to-point` — ETA data from Redis may be stale
- **Location:** `search.py:point_to_point_search()`
- **Issue:** Reads from `route:{route_number}:stop:{start_stop_id}` in Redis. If no bus has recently traversed this route-stop, the hash may be empty or stale.
- **Impact:** Returns `"etas": {}` for routes with no recent bus activity. Mobile shows "No active bus."
- **This is correct behavior** — no data means no active bus.

### BUG 3: `POST /telemetry` — `occupancy_level` in response is from `resolve_occupancy_level`, not from CV
- **Location:** `vehicles.py:receive_telemetry()`
- **Issue:** The `POST /telemetry` endpoint (JSON, no image) computes occupancy from `pixel_count` or `raw_payload` heuristic. The `POST /gateway/esp32/telemetry` endpoint (multipart, with image) runs full CV analysis.
- **Impact:** If a bus only sends JSON telemetry (no camera), occupancy is a rough heuristic. **This is by design.**

### BUG 4: `GET /routes/{route_number}/etas` — No authentication
- **Location:** `routes.py:get_route_etas()`
- **Issue:** Public endpoint with no auth. Any client can query any route's ETA data.
- **Impact:** Low security risk for a public transport app. **Acceptable for this use case.**

---

## 6. Summary of Backend Issues

| # | Severity | Issue | Fix Needed |
|---|----------|-------|-----------|
| 1 | 🔴 HIGH | `bus_plate` missing from point-to-point ETA response | Add `bus_plate` to Redis ETA hash in `route_eta.py` or `search.py` |
| 2 | 🟡 MEDIUM | 4 missing endpoints for mobile (profile update, change password, delete favorite, FCM token) | Implement the 4 endpoints |
| 3 | 🟡 MEDIUM | `density_level` is redundant with `occupancy_level` | Remove `density_level` from schema and CRUD |
| 4 | 🟢 LOW | `inference_ms` dropped from WebSocket CV broadcast | Add to `broadcast_cv_result` payload |
| 5 | 🟢 LOW | `human_count` redundant with `people_count` in CV | Remove `human_count` |
| 6 | 🟢 LOW | Positions envelope keyed by vehicle_id not plate_number | Works as-is; change only for consistency |
