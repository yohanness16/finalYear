# Mobile App Remaining Work Plan
**Date:** 2026-05-26
**Purpose:** What the mobile app needs to implement/fix to fully support features and properly consume backend data.

---

## Priority 1: Critical — Fixes for Backend Gaps

These fixes depend on the backend implementing the missing endpoints (see BACKEND_REMAINING_WORK.md). Until then, the fallback chains in `api_adapter.dart` will continue to fail silently.

### 1.1 Remove Fallback Chains Once Backend Endpoints Exist

**Current state:** `api_adapter.dart` tries 3 different endpoints for profile update and password change. Once the correct endpoints are implemented on the backend:

- Remove fallback chain for `updateProfile()` → just use `PATCH /auth/me`
- Remove fallback chain for `changePassword()` → just use `POST /auth/change-password`
- Remove fallback chain for `registerFcmToken()` → just use `POST /notifications/register-token`

### 1.2 Wire Up Remove Favorite

**Current state:** `journey_results_screen.dart:213-219` shows "Remove favorite is pending backend delete support."

**Once backend implements `DELETE /favorites/{id}`:**
- Enable the remove favorite button in `journey_results_screen.dart`
- Call `ref.read(deleteFavoriteProvider.notifier).deleteFavorite(favoriteId)`
- Remove the "pending backend support" snackbar

---

## Priority 2: High — Data Display Fixes

### 2.1 Fix `bus_plate` in Journey Results

**Current state:** `journey_result_model.dart:18` — `busPlate` always null because backend doesn't send it.

**Option A (Backend fix):** Backend adds `bus_plate` to the point-to-point Redis ETA hash. Then it appears in the `etas` map automatically.

**Option B (Mobile workaround):** After getting journey results, cross-reference with live vehicle positions to find the plate number for each route.

**Recommended:** Option A (backend fix). Option B is fragile and adds complexity.

### 2.2 Display `last_updated` Age for Buses

**Current state:** `route_detail_screen.dart:584` shows "Live" / "Estimated" badge based on `bus.lastUpdated`. But `lastUpdated` is set to `DateTime.now()` when polling, not the actual bus data age.

**Fix:** Once backend adds `last_updated` (ISO 8601) to `VehiclePosition`, update `websocket_service.dart` to use the server-provided timestamp instead of `DateTime.now()`:

```dart
// In _applyPositions():
lastUpdated: position.lastUpdated ?? DateTime.now(),  // Already correct IF backend sends it
```

### 2.3 Show Bus Speed in Journey Results

**Current state:** Backend sends `speed` in vehicle position data, but journey results don't display it.

**Fix:** Add speed display to `journey_results_screen.dart` bus cards. The `speed` field is available in the `etas` map from Redis (`speed_kmh`).

**Code addition in `journey_result_model.dart`:**
```dart
int? get speedKmh => etas['speed_kmh'] != null 
    ? int.tryParse(etas['speed_kmh'].toString()) 
    : null;
```

---

## Priority 3: Medium — Feature Completion

### 3.1 Implement Proper Email Verification Flow

**Current state:** After registration, user is taken to login screen. No email verification prompt.

**Fix:**
1. After registration, show a screen: "Check your email for a verification link"
2. Add a "Resend verification email" button
3. Handle the `POST /auth/verify-email` endpoint
4. Handle the `POST /auth/resend-verification` endpoint

### 3.2 Implement Password Reset Flow

**Current state:** No forgot/reset password UI. Backend has `/auth/forgot-password` and `/auth/reset-password`.

**Fix:**
1. Add "Forgot password?" link on login screen
2. Add forgot password screen (email input)
3. Add reset password screen (token + new password)
4. Wire up to backend endpoints

### 3.3 Implement WebSocket for Real-Time Updates

**Current state:** `websocket_service.dart` polls every 15s. `web_socket_channel` dependency exists but is unused.

**Fix:**
1. Create a proper WebSocket service that connects to `wss://api.bustrack.dpdns.org/api/v1/ws/live`
2. Note: The current WebSocket endpoint is admin-only. Need a passenger-facing endpoint on backend, OR use the admin endpoint with a passenger JWT (security concern).
3. Alternative: Implement Server-Sent Events (SSE) for one-way real-time updates from backend to mobile.

**Recommended approach:** Add a new backend endpoint `GET /ws/live` that doesn't require admin auth — just a valid passenger JWT — and broadcasts only vehicle positions (no admin data).

### 3.4 Show Crowd Density Detail

**Current state:** Mobile only shows occupancy level (0/1/2) as green/amber/red.

**Enhancement:** Add a crowd density detail page or expand the bus bottom sheet to show:
- People count (from CV)
- Detection method (from CV)
- Confidence score (from CV)
- This requires backend to include CV data in the REST vehicle positions endpoint

### 3.5 Add ML vs Heuristic ETA Indicator

**Current state:** Backend sends `eta_mode: "heuristic" | "ml"` and both `eta_ml_seconds` and `eta_heuristic_seconds`. Mobile ignores all of this.

**Enhancement:** Show a small indicator like "🤖 ML ETA: 6 min" or "📍 Estimated: 7 min" in journey results.

**Code addition in `journey_result_model.dart`:**
```dart
String? get etaMode => etas['eta_mode'] as String?;
double? get etaMlSeconds => etas['eta_ml_seconds'] != null 
    ? double.tryParse(etas['eta_ml_seconds'].toString()) 
    : null;
double? get etaHeuristicSeconds => etas['eta_heuristic_seconds'] != null 
    ? double.tryParse(etas['eta_heuristic_seconds'].toString()) 
    : null;
```

### 3.6 Display `isTerminal` and `peakMultiplier` in Stop Context

**Current state:** `StopModel` has `isTerminal` and `peakMultiplier` but they're never displayed.

**Enhancement:** In `route_detail_screen.dart`, show a "Terminus" badge for terminal stops. Show peak multiplier in stop tooltip if relevant.

---

## Priority 4: Low — Code Cleanup

### 4.1 Remove Dead Code from JourneyResultModel

**File:** `journey_result_model.dart:20-21`
```dart
if (etas['eta_minutes'] != null) {  // Dead code — backend never sends eta_minutes
    return int.tryParse(etas['eta_minutes'].toString());
}
```
**Fix:** Remove the `eta_minutes` check. Keep only the `eta_seconds` fallback.

### 4.2 Rename `lastUpdated` to `receivedAt` in BusLocation

**File:** `bus_location.dart`
**Fix:** Rename to clarify this is client-side "when we received it," not "when the bus sent it." Prevents confusion once backend adds real `last_updated`.

### 4.3 Remove Unused `web_socket_channel` Import

**File:** `pubspec.yaml`
**Fix:** If WebSocket isn't implemented within the current sprint, remove the unused dependency to reduce app size.

### 4.4 Remove Unused `direction` from RouteModel

**File:** `route_model.dart` imports `direction` from JSON but it's not in the model class. The `fromJson` silently drops it. **No fix needed** — this is fine as long as `direction` stays `includeFromJson: false` or is excluded in the freezed config.

### 4.5 Add `bus_type` Display to Bus Bottom Sheet

**File:** `home_screen.dart`
**Enhancement:** Backend `VehiclePosition` doesn't include `bus_type` in the REST response (only in WebSocket). Add it to the REST schema and display it (e.g., "Anbessa Bus" / "Sheger Bus" / "Minibus").

---

## Implementation Order

| Step | Task | Dependency | Estimated Effort |
|------|------|-----------|-----------------|
| 1 | Remove fallback chains (once backend endpoints exist) | Backend P1 | 15 min |
| 2 | Wire up remove favorite | Backend P1.3 | 30 min |
| 3 | Fix `bus_plate` in journey results | Backend P2.1 | 15 min |
| 4 | Use server-provided `last_updated` | Backend P2.3 | 15 min |
| 5 | Implement email verification flow | None | 2 hours |
| 6 | Implement password reset flow | None | 2 hours |
| 7 | Show bus speed in journey results | None | 30 min |
| 8 | Remove dead `eta_minutes` code | None | 5 min |
| 9 | Rename `lastUpdated` to `receivedAt` | None | 15 min |
| 10 | Add ML/heuristic ETA indicator | None | 1 hour |
| 11 | Display bus type in bottom sheet | Backend | 30 min |
| 12 | Display terminal badge on stops | None | 30 min |
| 13 | Implement WebSocket real-time | Backend P4.1 | 4 hours |
| 14 | Show crowd density detail | Backend P4.2 | 2 hours |
| **Core fixes total** | | | **~4 hours** |
| **All enhancements total** | | | **~12 hours** |
