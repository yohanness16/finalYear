# Backend Remaining Work Plan
**Date:** 2026-05-26
**Purpose:** What the backend needs to implement/fix to fully support the system goals and mobile app.

---

## Priority 1: Critical — Missing Mobile Endpoints

These 4 endpoints are required for the mobile app to function properly. The mobile app has fallback chains that try multiple endpoints, but none exist.

### 1.1 `PATCH /auth/me` — Update Passenger Profile

**Current state:** Not implemented. Mobile tries `PATCH /auth/me`, `PUT /auth/me`, `PATCH /users/{id}` — all 404.

**What to implement:**
```python
@router.patch("/auth/me", response_model=UserResponse)
async def update_profile(
    body: UserUpdateRequest,  # {username?, email?}
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.username:
        current_user.username = body.username
    if body.email:
        current_user.email = body.email
    await db.flush()
    await db.refresh(current_user)
    return current_user
```

**Files to modify:**
- `app/api/v1/auth.py` — Add endpoint
- `app/schemas/auth.py` — Add `UserUpdateRequest` schema
- `app/core/security.py` — Add `get_current_user` dependency (extract from JWT)

### 1.2 `POST /auth/change-password` — Change Password

**Current state:** Not implemented. Mobile tries 3 fallback endpoints — all 404.

**What to implement:**
```python
@router.post("/auth/change-password")
async def change_password(
    body: ChangePasswordRequest,  # {current_password, new_password}
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    current_user.password_hash = hash_password(body.new_password)
    await db.flush()
    return {"status": "password_changed"}
```

**Files to modify:**
- `app/api/v1/auth.py` — Add endpoint
- `app/schemas/auth.py` — Add `ChangePasswordRequest` schema

### 1.3 `DELETE /favorites/{favorite_id}` — Remove Favorite

**Current state:** Not implemented. Mobile catches error and does local-only deletion.

**What to implement:**
```python
@router.delete("/favorites/{favorite_id}")
async def delete_favorite(
    favorite_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    fav = await db.get(Favorite, favorite_id)
    if not fav:
        raise HTTPException(404, "Favorite not found")
    if fav.user_id != current_user.id:
        raise HTTPException(403, "Not your favorite")
    await db.delete(fav)
    await db.flush()
    return {"status": "deleted", "id": favorite_id}
```

**Files to modify:**
- `app/api/v1/favorites.py` — Add DELETE endpoint

### 1.4 `POST /notifications/register-token` — Register FCM Token

**Current state:** Not implemented. Mobile tries this, then falls back to `POST /auth/me/fcm-token` — both 404.

**What to implement:**
```python
class FcmTokenRequest(BaseModel):
    user_id: int
    token: str

@router.post("/notifications/register-token")
async def register_fcm_token(body: FcmTokenRequest, db: AsyncSession = Depends(get_db)):
    # Store FCM token — either in a new table or in user preferences
    # For now, store in Redis with TTL
    redis = await get_redis()
    await redis.set(f"fcm:{body.user_id}", body.token, ex=2592000)  # 30 days
    return {"status": "registered"}
```

**Files to modify:**
- `app/api/v1/notifications.py` — Add endpoint
- Optionally add an `fcm_tokens` DB table for persistence

---

## Priority 2: High — Data Enrichment for Mobile

### 2.1 Add `bus_plate` to Point-to-Point ETA Response

**Current state:** The `etas` map in `POST /search/point-to-point` response doesn't include `bus_plate`. Mobile always shows "No active bus."

**Root cause:** The ETA data comes from Redis `route:{number}:stop:{stop_id}` hash, which doesn't store plate numbers.

**Fix approach:** In `search.py:point_to_point_search()`, after reading ETA from Redis, look up which bus/vehicle is associated with that ETA and include the plate number.

**Files to modify:**
- `app/api/v1/search.py` — Enrich ETA response with `bus_plate`
- `app/services/redis_cache.py` — Store plate number in ETA hash when computing ETAs

### 2.2 Add `is_verified` and `google_id` to UserResponse

**Current state:** `UserResponse` schema only has `{id, username, email, role, created_at}`. Mobile expects `is_verified` and `google_id`.

**Fix:**
```python
class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    email: EmailStr
    role: str = "passenger"
    is_verified: bool = False
    google_id: str | None = None
    created_at: datetime
```

**Files to modify:**
- `app/schemas/user.py` — Add fields to `UserResponse`

### 2.3 Add `last_updated` to VehiclePosition (or rename `timestamp`)

**Current state:** Backend sends `timestamp` (Unix float). Mobile expects `last_updated` (ISO 8601 string). Mobile's `lastUpdated` field is always null from API.

**Fix:** Either:
- (a) Add `last_updated` as ISO 8601 string alongside `timestamp` in the response
- (b) Change mobile to use `timestamp` instead

**Recommended:** Add `last_updated` to the `VehiclePosition` schema:
```python
class VehiclePosition(BaseModel):
    # ... existing fields ...
    timestamp: float
    last_updated: datetime | None = None  # ISO 8601 for mobile compatibility
```

**Files to modify:**
- `app/schemas/vehicle.py` — Add `last_updated` field
- `app/crud/vehicle.py` — Populate `last_updated` from `position_updated_at`

---

## Priority 3: Medium — Cleanup & Consistency

### 3.1 Remove `density_level` Redundancy

**Current state:** `VehiclePosition` includes both `occupancy_level` and `density_level` with the same value. Mobile doesn't use `density_level`.

**Fix:** Remove `density_level` from:
- `app/schemas/vehicle.py` — `VehiclePosition` class
- `app/crud/vehicle.py` — `get_live_positions()` and `get_position()`

### 3.2 Remove `human_count` from CV Pipeline

**Current state:** CV functions return both `human_count` and `people_count` (same value). Only `people_count` is used in WebSocket broadcast.

**Fix:** Remove `human_count` from:
- `app/services/cv_engine.py`
- `app/services/yolo_detector.py`

### 3.3 Add `inference_ms` to WebSocket CV Broadcast

**Current state:** `yolo_detector.py` returns `inference_ms` but `live_broadcast.py` drops it.

**Fix:** Add to `broadcast_cv_result` in `app/services/live_broadcast.py`:
```python
"inference_ms": cv_result.get("inference_ms", 0.0),
```

### 3.4 Add `direction` to RouteResponse

**Current state:** `RouteResponse` doesn't include `direction`. Mobile's `RouteModel` doesn't expect it either, but it's useful for display.

**Fix:** Add `direction` to `RouteResponse` in `app/schemas/route.py`.

---

## Priority 4: Low — Future Enhancements

### 4.1 Implement WebSocket Support for Mobile

**Current state:** Mobile polls every 15s. Backend has WebSocket at `/ws/live` but it's admin-only.

**Enhancement:** Create a passenger-facing WebSocket endpoint that broadcasts vehicle positions (without admin-only ETA payloads). This would reduce server load and provide real-time updates.

### 4.2 Add Crowd Density Data to Vehicle Positions REST Endpoint

**Current state:** CV results (people_count, face_count, head_blob_count) are only in WebSocket. Mobile only sees `occupancy_level` (0/1/2).

**Enhancement:** Include CV detail in `GET /vehicles/positions` response for mobile to show richer crowd info.

### 4.3 Add Rate Limiting for Mobile-Specific Endpoints

**Current state:** Only `/telemetry` and `/gateway/esp32/telemetry` have rate limits (300/min).

**Enhancement:** Add rate limiting to auth endpoints (login, register) to prevent abuse.

### 4.4 Add ETA Comparison Data to Mobile Search

**Current state:** Mobile only shows one ETA. Backend computes both ML and heuristic ETAs.

**Enhancement:** Include `eta_ml_seconds` and `eta_heuristic_seconds` in point-to-point response so mobile can show "ML: 6 min | Heuristic: 7 min" comparison.

---

## Implementation Order

| Step | Task | Estimated Effort |
|------|------|-----------------|
| 1 | Add `PATCH /auth/me` endpoint | 30 min |
| 2 | Add `POST /auth/change-password` endpoint | 30 min |
| 3 | Add `DELETE /favorites/{id}` endpoint | 20 min |
| 4 | Add `POST /notifications/register-token` endpoint | 20 min |
| 5 | Add `is_verified`, `google_id` to `UserResponse` | 10 min |
| 6 | Add `bus_plate` to point-to-point ETA response | 1 hour |
| 7 | Add `last_updated` to `VehiclePosition` | 20 min |
| 8 | Remove `density_level` redundancy | 15 min |
| 9 | Remove `human_count` from CV pipeline | 15 min |
| 10 | Add `inference_ms` to WebSocket CV broadcast | 5 min |
| **Total** | | **~4 hours** |
