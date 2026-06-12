# Mobile App Gap Analysis Plan
**Date:** 2026-05-26
**Purpose:** What the mobile app expects vs what backend sends, and what features are missing/incomplete.

---

## 1. Backend → Mobile Data Flow: Complete Comparison

### 1.1 Authentication (`/auth/*`)

| Endpoint | Backend Sends | Mobile Expects | Match? |
|----------|--------------|----------------|--------|
| `POST /auth/login` | `{access_token, token_type}` | `access_token` string | ✅ Yes |
| `POST /auth/register` | `UserResponse {id, username, email, role, created_at}` | `UserModel {id, username, email, role, is_verified, google_id, created_at}` | ⚠️ Partial — backend sends `is_verified: false` but mobile handles missing fields with defaults |
| `POST /auth/google` | `{access_token, token_type}` | `access_token` string | ✅ Yes |
| `GET /auth/me` | `UserResponse {id, username, email, role, created_at}` | `UserModel` | ⚠️ Backend doesn't send `is_verified`, `google_id` — mobile defaults handle this |
| `POST /auth/refresh` | `{access_token, token_type}` | `access_token` string | ✅ Yes |

**ISSUE:** Backend `UserResponse` schema doesn't include `is_verified` or `google_id`. Mobile app has these fields with defaults (`isVerified: false`, `googleId: null`). **Works but incomplete.**

### 1.2 Vehicle Positions (`/vehicles/positions`)

| Field | Backend Sends | Mobile Expects | Match? |
|-------|--------------|----------------|--------|
| Envelope key | `vehicle_id` (string) | Plate number used internally | ✅ Mobile re-keys |
| `vehicle_id` | `int` | `int` | ✅ |
| `plate_number` | `string` | `string` | ✅ |
| `lat` | `float` | `double` | ✅ |
| `lon` | `float` | `double` | ✅ |
| `speed` | `float` | `double` | ✅ |
| `timestamp` | `float` (Unix) | `double` | ✅ |
| `route_id` | `int?` | `int?` | ✅ |
| `assignment_id` | `int?` | `int?` | ✅ |
| `occupancy_level` | `int` | `int` (default 0) | ✅ |
| `density_level` | `int` | **Not expected by mobile** | ⚠️ Extra field — harmless |
| `last_updated` | **Not sent** | `DateTime?` (expects `last_updated`) | ❌ Never populated from API |
| `bus_type` | **Not sent** | **Not expected** | ✅ |

**ISSUE:** Mobile expects `last_updated` (DateTime) but backend sends `timestamp` (Unix float). The mobile's `VehiclePositionModel.lastUpdated` is always null from the API response. Then `websocket_service.dart` overwrites it with `DateTime.now()`. **The `last_updated` field in the mobile model is misleading — it's actually "time we received the data."**

### 1.3 Point-to-Point Search (`POST /search/point-to-point`)

| Field | Backend Sends (in `etas` map) | Mobile Expects | Match? |
|-------|-------------------------------|----------------|--------|
| `route_number` | `string` | `string` | ✅ |
| `eta_seconds` | `number` (live-adjusted) | Falls back to `eta_seconds/60` | ✅ Works |
| `eta_minutes` | **Not sent** | Checked first | ⚠️ Always null — uses fallback |
| `eta_heuristic_seconds` | `number` | **Not expected** | Extra — harmless |
| `eta_ml_seconds` | `number?` | **Not expected** | Extra — harmless |
| `eta_mode` | `string` | **Not expected** | Extra — harmless |
| `distance_m` | `number` | **Not expected** | Extra — harmless |
| `speed_kmh` | `number` | **Not expected** | Extra — harmless |
| `occupancy_level` | `number` | `int?` | ✅ |
| `computed_at` | `number` | **Not expected** | Extra — harmless |
| `stop_name` | `string` | **Not expected** | Extra — harmless |
| `bus_plate` | **Not sent** | `String?` — always null | ❌ **BUG** |

**CRITICAL ISSUE:** `bus_plate` is never included in the ETA response. Mobile shows "No active bus" even when buses are active. This is a known TODO in the mobile code.

### 1.4 Route List (`GET /routes`)

| Field | Backend Sends | Mobile Expects | Match? |
|-------|--------------|----------------|--------|
| `id` | `int` | `int` | ✅ |
| `route_number` | `string` | `string` | ✅ |
| `name` | `string?` (nullable) | `String?` | ⚠️ Backend `name` is `String(200)` required in model but `nullable=True` in schema — potential null |
| `origin` | `string?` | `String?` | ✅ |
| `destination` | `string?` | `String?` | ✅ |
| `stops` | **Not included** | `List<StopModel>` (default `[]`) | ✅ Mobile fetches separately |
| `direction` | `string` | **Not expected** | Extra — harmless |

**ISSUE:** The `name` field on the backend `routes` table is `nullable=False` with no default. If a route is created without a name, the DB will reject it. But the mobile expects it nullable. **No actual bug since backend requires it, but mobile is defensively correct.**

### 1.5 Route Detail (`GET /routes/{id}`)

| Field | Backend Sends | Mobile Expects | Match? |
|-------|--------------|----------------|--------|
| `id` | `int` | `int` | ✅ |
| `route_number` | `string` | `string` | ✅ |
| `direction` | `string` | **Not expected** | Extra — harmless |
| `name` | `string` | `String?` | ✅ |
| `origin` | `string?` | `String?` | ✅ |
| `destination` | `string?` | `String?` | ✅ |
| `stops[]` | Array of stops | `List<StopModel>` | ✅ |
| `stops[].base_dwell_time` | `int` | `int` | ✅ |
| `stops[].is_terminal` | `bool` | `bool` | ✅ |
| `stops[].peak_multiplier` | `float` | `double` | ✅ |

**✅ PERFECT MATCH.**

### 1.6 Stops List (`GET /stops`)

**✅ PERFECT MATCH.** All fields align exactly.

### 1.7 Favorites

| Operation | Backend Expects | Mobile Sends | Match? |
|-----------|----------------|-------------|--------|
| `POST /favorites` | `{user_id, route_id, nickname}` | `{user_id, route_id, nickname}` | ✅ |
| `GET /favorites/{user_id}` | — | Returns array of Favorite objects | ✅ |
| `DELETE /favorites/{id}` | — | Favorite ID | ❌ **Not implemented on backend** |

**ISSUE:** Delete favorite endpoint doesn't exist on backend. Mobile catches the error and does local-only deletion. Favorite reappears on next data refresh.

### 1.8 Ratings

| Operation | Backend Expects | Mobile Sends | Match? |
|-----------|----------------|-------------|--------|
| `POST /ratings` | `{user_id, assignment_id, score, comment?}` | `{user_id, assignment_id, score, comment?}` | ✅ |
| `GET /ratings/{assignment_id}` | — | Returns `[{score, comment?}]` | ✅ |

**✅ PERFECT MATCH.**

### 1.9 Notifications

| Operation | Backend Expects | Mobile Sends | Match? |
|-----------|----------------|-------------|--------|
| `POST /notifications/settings` | `{user_id, route_id, lead_time_minutes}` | `{user_id, route_id, lead_time_minutes}` | ✅ |
| `GET /notifications/settings/{user_id}` | — | Returns array | ✅ |
| `POST /notifications/register-token` | `{user_id, token}` | `{user_id, token}` | ❌ **Not implemented on backend** |
| `POST /auth/me/fcm-token` (fallback) | `{fcm_token}` | `{fcm_token}` | ❌ **Not implemented on backend** |

**ISSUE:** FCM token registration falls through both endpoints and returns `false`.

---

## 2. What Mobile App is MISSING (Not Implemented)

### 2.1 Features Present in Backend But Not Used by Mobile

| Backend Feature | Mobile Status | Impact |
|----------------|---------------|--------|
| `POST /search/journey` (geo-based search) | ❌ Not used | Mobile only uses point-to-point; geo search with coordinates/queries available but unused |
| `GET /routes/{number}/etas` (all stop ETAs) | ❌ Not used | Mobile computes its own ETA from journey results |
| `GET /admin/use-ml` (ML status) | ❌ Not used | Passenger doesn't know if ML ETA is active |
| WebSocket real-time updates | ❌ Not used | Mobile polls every 15s instead of using live WebSocket |
| `bus_type` field in VehiclePosition | ❌ Not displayed | Mobile doesn't show bus type (Anbessa/Sheger/Minibus) |
| `speed` in journey search bus entry | ❌ Not displayed | Mobile doesn't show bus speed in journey results |
| `eta_ml_seconds` / `eta_heuristic_seconds` | ❌ Not displayed | Mobile only shows `etaMinutes`, doesn't compare ML vs heuristic |
| `crowd_density` (`is_crowded`, `people_count`, `face_count`, `head_blob_count`) | ❌ Not displayed | WebSocket CV data never reaches mobile |
| `direction` field in RouteModel | ❌ Not displayed | Mobile doesn't show forward/reverse direction |
| Email verification flow | ❌ Not wired up | Mobile registers but doesn't handle email verification |
| Password reset flow | ❌ Not implemented | No forgot/reset password screens |
| `GET /vehicles/positions/{vehicleId}` (single vehicle) | ❌ Not used | Mobile fetches all positions |

### 2.2 Mobile UI Features That Are Incomplete

| Feature | Screen | Issue |
|---------|--------|-------|
| "No active bus" in journey results | `journey_results_screen.dart` | Always shows because `bus_plate` never sent by backend |
| Remove favorite | `journey_results_screen.dart` | Shows snackbar "Remove favorite is pending backend delete support" |
| Bus type display | `home_screen.dart` | `bus_type` from backend not shown in bus bottom sheet |
| ML ETA indicators | `journey_results_screen.dart` | No indication of whether ETA is ML-powered or heuristic |
| Crowd density detail | `home_screen.dart` | Only shows occupancy level (0/1/2), not people count or CV method |
| Walking time to stop | `route_detail_screen.dart` | ✅ Implemented via OSRM |
| Email verification | `register_screen.dart` | No prompt to verify email after registration |
| Password reset | Settings screen | No forgot password flow |

---

## 3. Mobile App Bugs

### BUG 1: WebSocket imported but never used
- **File:** `pubspec.yaml` — `web_socket_channel: ^3.0.3`
- **File:** `websocket_service.dart` — uses HTTP polling, not WebSocket
- **Impact:** Unnecessary dependency; real-time updates limited to 15s polling interval
- **Fix:** Either implement WebSocket or remove the unused import

### BUG 2: `eta_minutes` field never found in point-to-point response
- **File:** `journey_result_model.dart:20-21`
- **Code:** Checks `etas['eta_minutes']` first, but backend sends `eta_seconds`
- **Impact:** Always falls through to `eta_seconds/60` calculation. Not a bug per se, but the `eta_minutes` check is dead code.

### BUG 3: `assignmentId` default `0` causes false matches in route detail
- **File:** `websocket_service.dart:107`
- **Code:** `assignmentId: position.assignmentId ?? 0`
- **Impact:** Buses without active assignments get `assignmentId = 0`. In `route_detail_screen.dart:381`, `bus.assignmentId.toString()` → `"0"`. If the ETA map doesn't have key `"0"`, the bus is hidden. **Correct behavior for filtering, but the default `0` is semantically misleading.**

### BUG 4: `isTerminal` and `peakMultiplier` in StopModel never used
- **File:** `stop_model.dart` — fields exist
- **Impact:** Displayed nowhere in the UI. Dead data.

### BUG 5: `googleId` and `isVerified` in UserModel never populated
- **File:** `user_model.dart` — fields exist with defaults
- **Impact:** Backend `UserResponse` doesn't send these fields. The frontend can never show verification status.

### BUG 6: Rating duplicate submission not properly prevented
- **File:** `home_screen.dart` — checks `hasSubmittedRating` locally
- **Impact:** Local-only check. If user reinstalls app or clears data, they can rate again. Backend doesn't prevent duplicate ratings from same user on same assignment.

### BUG 7: Route detail screen hides buses with null assignmentId
- **File:** `route_detail_screen.dart:381`
- **Code:** `targetJourney!.etas.containsKey(bus.assignmentId.toString())`
- **Impact:** When `assignmentId` is null, `toString()` returns `"null"`. The ETA map likely uses integer stop IDs as keys. Buses without assignments are always hidden. **This is correct for assigned-bus-only display.**

---

## 4. What Mobile App SENDS But Backend Doesn't Need/Use

| Field | Sent By | Backend Action | Issue |
|-------|---------|---------------|-------|
| `nickname` in POST `/favorites` | Mobile sends even if null | Backend stores null | Minor — backend should ignore null nickname |

---

## 5. Summary of Mobile Issues

| # | Severity | Issue | Fix Needed |
|---|----------|-------|-----------|
| 1 | 🔴 HIGH | `bus_plate` never shown in journey results | Backend must include it OR mobile must get it from vehicle positions |
| 2 | 🔴 HIGH | FCM token registration fails silently | Implement `POST /notifications/register-token` on backend |
| 3 | 🔴 HIGH | Remove favorite shows "pending backend support" | Implement `DELETE /favorites/{id}` on backend |
| 4 | 🟡 MEDIUM | Profile update uses fallback chain, may fail | Implement `PATCH /auth/me` on backend |
| 5 | 🟡 MEDIUM | Password change uses fallback chain, may fail | Implement `POST /auth/change-password` on backend |
| 6 | 🟡 MEDIUM | WebSocket imported but never used | Implement real-time updates or remove dependency |
| 7 | 🟡 MEDIUM | Crowd density CV data never reaches mobile | Add CV data to REST endpoint or implement WebSocket |
| 8 | 🟢 LOW | `eta_minutes` check is dead code in journey model | Remove dead code or have backend send it |
| 9 | 🟢 LOW | `isTerminal`, `peakMultiplier` displayed nowhere | Add to UI or remove from model |
| 10 | 🟢 LOW | `last_updated` in VehiclePositionModel always null from API | Rename to clarify it's client-side timestamp |
| 11 | 🟢 LOW | `density_level` sent by backend but not parsed by mobile | Ignore — no impact |
