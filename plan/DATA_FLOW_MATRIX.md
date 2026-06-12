# Complete Data Flow Matrix — Backend ↔ Mobile App
**Date:** 2026-05-26
**Purpose:** Single reference for every API call: what backend sends vs what mobile expects.

---

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Exact match — field name, type, and nullability align |
| ⚠️ | Partial match — works but with defaults/caveats |
| ❌ | Mismatch — missing field, wrong type, or broken feature |
| ➡️ | Extra field sent by backend, not expected by mobile (harmless) |
| ⬅️ | Field expected by mobile, not sent by backend |

---

## 1. Authentication

### `POST /auth/login`

| Field | Direction | Backend | Mobile | Status |
|-------|-----------|---------|--------|--------|
| `access_token` | ← | `str` | `String` | ✅ |
| `token_type` | ← | `str` = "bearer" | Not read | ➡️ Harmless |

### `POST /auth/register`

| Field | Direction | Backend | Mobile | Status |
|-------|-----------|---------|--------|--------|
| `id` | ← | `int` | `int` | ✅ |
| `username` | ← | `str` | `String` | ✅ |
| `email` | ← | `EmailStr` | `String` | ✅ |
| `role` | ← | `str` = "passenger" | `String` | ✅ |
| `is_verified` | ← | **Not in UserResponse** | `bool` (default `false`) | ⬅️ Backend should add |
| `google_id` | ← | **Not in UserResponse** | `String?` (null) | ⬅️ Backend should add |
| `created_at` | ← | `datetime` (ISO 8601) | `DateTime?` | ✅ |

### `POST /auth/google`

| Field | Direction | Backend | Mobile | Status |
|-------|-----------|---------|--------|--------|
| `access_token` | ← | `str` | `String` | ✅ |
| `token_type` | ← | `str` = "bearer" | Not read | ➡️ Harmless |

### `GET /auth/me`

| Field | Direction | Backend | Mobile | Status |
|-------|-----------|---------|--------|--------|
| `id` | ← | `int` | `int` | ✅ |
| `username` | ← | `str` | `String` | ✅ |
| `email` | ← | `str` | `String` | ✅ |
| `role` | ← | `str` | `String` | ✅ |
| `is_verified` | ← | **Not in UserResponse** | `bool` (default) | ⬅️ Backend should add |
| `google_id` | ← | **Not in UserResponse** | `String?` | ⬅️ Backend should add |
| `created_at` | ← | `datetime` | `DateTime?` | ✅ |

### `POST /auth/refresh`

| Field | Direction | Backend | Mobile | Status |
|-------|-----------|---------|--------|--------|
| `access_token` | ← | `str` | `String` | ✅ |
| `token_type` | ← | `str` | Not read | ➡️ Harmless |

---

## 2. Vehicle Positions

### `GET /vehicles/positions` (Envelope)

| Field | Direction | Backend | Mobile | Status |
|-------|-----------|---------|--------|--------|
| `positions` | ← | `dict[str, VehiclePosition]` | `Map<String, VehiclePositionModel>` | ✅ |
| `timestamp` | ← | `float` (Unix) | `double` | ✅ |

### `GET /vehicles/positions` (Each position)

| Field | Direction | Backend | Mobile | Status |
|-------|-----------|---------|--------|--------|
| Key in positions map | ← | `vehicle_id` as string (e.g., `"5"`) | Plate number used by mobile | ⚠️ Different keys, works |
| `vehicle_id` | ← | `int` | `int` | ✅ |
| `plate_number` | ← | `str` | `String` | ✅ |
| `lat` | ← | `float` | `double` | ✅ |
| `lon` | ← | `float` | `double` | ✅ |
| `speed` | ← | `float` | `double` | ✅ |
| `timestamp` | ← | `float` (Unix) | `double` | ✅ |
| `route_id` | ← | `int?` | `int?` | ✅ |
| `assignment_id` | ← | `int?` | `int?` | ✅ |
| `occupancy_level` | ← | `int` | `int` | ✅ |
| `density_level` | ← | `int` | **Not expected** | ➡️ Redundant |
| `bus_type` | ← | **Not sent** | **Not expected** | ✅ |
| `last_updated` | ← | **Not sent** | `DateTime?` | ⬅️ Always null |

### `GET /vehicles/positions/{vehicle_id}`

Same fields as individual position above.

---

## 3. Search

### `POST /search/point-to-point` — Request

| Field | Direction | Mobile sends | Backend expects | Status |
|-------|-----------|-------------|----------------|--------|
| `start_stop_id` | → | `int` | `int` | ✅ |
| `end_stop_id` | → | `int` | `int` | ✅ |

### `POST /search/point-to-point` — Response (Top level)

| Field | Direction | Backend | Mobile | Status |
|-------|-----------|---------|--------|--------|
| `routes` | ← | `list[object]` | `List<JourneyResultModel>` | ✅ |
| `start_stop` | ← | `str` (stop name) | Not captured | ➡️ Available but unused |
| `end_stop` | ← | `str` (stop name) | Not captured | ➡️ Available but unused |

### `POST /search/point-to-point` — Response (Per route, in `etas` map)

| Field | Direction | Backend | Mobile | Status |
|-------|-----------|---------|--------|--------|
| `route_number` | ← | `str` | `String` | ✅ |
| `etas` | ← | `dict` | `Map<String, dynamic>` | ✅ |
| `etas.eta_seconds` | ← | `float` (live-adj) | `etaMinutes` = `/60` | ✅ Fallback works |
| `etas.eta_minutes` | ← | **Not sent** | Checked first | ❌ Dead code |
| `etas.bus_plate` | ← | **Not sent** | `String?` (always null) | ❌ **BUG** |
| `etas.occupancy_level` | ← | `int` | `int?` | ✅ |
| `etas.stop_name` | ← | `str` | Not read | ➡️ Available |
| `etas.distance_m` | ← | `float` | Not read | ➡️ Available |
| `etas.speed_kmh` | ← | `float` | Not read | ➡️ Available |
| `etas.eta_heuristic_seconds` | ← | `float` | Not read | ➡️ Available |
| `etas.eta_ml_seconds` | ← | `float?` | Not read | ➡️ Available |
| `etas.eta_mode` | ← | `str` | Not read | ➡️ Available |
| `etas.computed_at` | ← | `float` | Not read | ➡️ Available |

---

## 4. Routes & Stops

### `GET /routes/{id}` — Route Detail

| Field | Direction | Backend | Mobile | Status |
|-------|-----------|---------|--------|--------|
| `id` | ← | `int` | `int` | ✅ |
| `route_number` | ← | `str` | `String` | ✅ |
| `direction` | ← | `str` | Not in model | ➡️ Silently dropped |
| `name` | ← | `str` (nullable) | `String?` | ✅ |
| `origin` | ← | `str?` | `String?` | ✅ |
| `destination` | ← | `str?` | `String?` | ✅ |
| `stops[]` | ← | Array | `List<StopModel>` | ✅ |
| `stops[].id` | ← | `int` | `int` | ✅ |
| `stops[].name` | ← | `str` | `String` | ✅ |
| `stops[].lat` | ← | `float` | `double` | ✅ |
| `stops[].lon` | ← | `float` | `double` | ✅ |
| `stops[].base_dwell_time` | ← | `int` | `int` | ✅ |
| `stops[].is_terminal` | ← | `bool` | `bool` | ✅ (never displayed) |
| `stops[].peak_multiplier` | ← | `float` | `double` | ✅ (never displayed) |

### `GET /routes` — Route List

| Field | Direction | Backend | Mobile | Status |
|-------|-----------|---------|--------|--------|
| `id` | ← | `int` | `int` | ✅ |
| `route_number` | ← | `str` | `String` | ✅ |
| `direction` | ← | `str` | Not in model | ➡️ Silently dropped |
| `name` | ← | `str` | `String?` | ✅ |
| `origin` | ← | `str?` | `String?` | ✅ |
| `destination` | ← | `str?` | `String?` | ✅ |

### `GET /stops` — Stop List

| Field | Direction | Backend | Mobile | Status |
|-------|-----------|---------|--------|--------|
| `id` | ← | `int` | `int` | ✅ |
| `name` | ← | `str` | `String` | ✅ |
| `lat` | ← | `float` | `double` | ✅ |
| `lon` | ← | `float` | `double` | ✅ |
| `base_dwell_time` | ← | `int` | `int` | ✅ |
| `is_terminal` | ← | `bool` | `bool` | ✅ (never displayed) |
| `peak_multiplier` | ← | `float` | `double` | ✅ (never displayed) |

---

## 5. Favorites

### `POST /favorites` — Request

| Field | Direction | Mobile sends | Backend expects | Status |
|-------|-----------|-------------|----------------|--------|
| `user_id` | → | `int` | `int` | ✅ |
| `route_id` | → | `int` | `int` | ✅ |
| `nickname` | → | `String?` even if null | `str?` | ⚠️ Sends null explicitly |

### `GET /favorites/{user_id}` — Response

| Field | Direction | Backend | Mobile | Status |
|-------|-----------|---------|--------|--------|
| `id` | ← | `int` | `int` | ✅ |
| `user_id` | ← | `int` | `int` | ✅ |
| `route_id` | ← | `int` | `int` | ✅ |
| `nickname` | ← | `str?` | `String?` | ✅ |

### `DELETE /favorites/{favorite_id}`

| Aspect | Backend | Mobile | Status |
|--------|---------|--------|--------|
| Endpoint exists | ❌ No | Calls it, catches error | ❌ **Missing** |

---

## 6. Ratings

### `POST /ratings` — Request

| Field | Direction | Mobile sends | Backend expects | Status |
|-------|-----------|-------------|----------------|--------|
| `user_id` | → | `int` | `int` | ✅ |
| `assignment_id` | → | `int` | `int` | ✅ |
| `score` | → | `int` | `int` (1-5) | ✅ |
| `comment` | → | `String?` (omitted if empty) | `str?` | ✅ |

### `GET /ratings/{assignment_id}` — Response

| Field | Direction | Backend | Mobile | Status |
|-------|-----------|---------|--------|--------|
| `score` | ← | `int` | `num` (summed for avg) | ✅ |
| `comment` | ← | `str?` | Not used | ➡️ Available |
| `id` | ← | `int` (via ORM) | Not read | ➡️ Available |

---

## 7. Notifications

### `POST /notifications/settings` — Request

| Field | Direction | Mobile sends | Backend expects | Status |
|-------|-----------|-------------|----------------|--------|
| `user_id` | → | `int` | `int` | ✅ |
| `route_id` | → | `int` | `int` | ✅ |
| `lead_time_minutes` | → | `int` | `int` | ✅ |

### `GET /notifications/settings/{user_id}` — Response

| Field | Direction | Backend | Mobile | Status |
|-------|-----------|---------|--------|--------|
| `id` | ← | `int` | `int` | ✅ |
| `user_id` | ← | `int` | `int` | ✅ |
| `route_id` | ← | `int` | `int` | ✅ |
| `lead_time_minutes` | ← | `int` | `int` | ✅ |

### `POST /notifications/register-token`

| Aspect | Backend | Mobile | Status |
|--------|---------|--------|--------|
| Endpoint exists | ❌ No | Tries first | ❌ **Missing** |

---

## Summary of All Issues (52 fields checked)

| Category | Count |
|----------|-------|
| ✅ Exact match | 38 |
| ⚠️ Partial match (works with defaults) | 4 |
| ❌ Mismatch / missing | 5 |
| ➡️ Extra backend field (harmless) | 9 |
| ⬅️ Expected by mobile, not sent by backend | 3 |

### The 5 Critical Mismatches

| # | Issue | Backend Fix | Mobile Fix |
|---|-------|------------|-----------|
| 1 | `bus_plate` missing from point-to-point ETA | Add to Redis ETA hash | Remove dead `busPlate` accessor or use it when available |
| 2 | `PATCH /auth/me` missing | Add endpoint | Remove fallback chain |
| 3 | `POST /auth/change-password` missing | Add endpoint | Remove fallback chain |
| 4 | `DELETE /favorites/{id}` missing | Add endpoint | Enable remove button |
| 5 | `POST /notifications/register-token` missing | Add endpoint | Remove fallback chain |
