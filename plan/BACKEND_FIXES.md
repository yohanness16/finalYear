# Backend — Complete Fix Plan
**Date:** 2026-05-26
**Scope:** Every bug, missing endpoint, data mismatch, and cleanup item found during the full system audit.

---

## How This Document Is Organized

Every fix is a self-contained unit. For each one I list:
- **What's wrong** — the exact problem
- **Where** — file path and line numbers
- **Fix** — the exact code change needed
- **Priority** — 🔴 Critical / 🟡 Medium / 🟢 Low

---

## SECTION 1: Missing Endpoints (Mobile App Cannot Work Without These)

---

### FIX 1.1 — `PATCH /auth_me` — Update Passenger Profile

**Priority:** 🔴 CRITICAL

**What's wrong:**
The mobile app's `api_adapter.dart` tries `PATCH /auth/me`, then `PUT /auth/me`, then `PATCH /users/{id}`. All three return 404. The endpoint simply doesn't exist. Users cannot update their username or email.

**Where:** `app/api/v1/auth.py` — no PATCH route for `/auth/me`

**What the mobile sends:**
```json
{"username": "new_name", "email": "new@email.com"}
```

**Fix — Add to `app/api/v1/auth.py`:**

```python
from app.schemas.auth import UserUpdateRequest  # ← add this schema (see below)

@router.patch("/auth/me", response_model=UserResponse)
@limiter.limit("10/minute")
async def update_profile(
    request: Request,
    body: UserUpdateRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Update the authenticated passenger's profile."""
    if body.username is not None:
        existing = await crud_user.get_user_by_username(db, body.username)
        if existing and existing.id != current_user.id:
            raise HTTPException(400, "Username already taken")
        current_user.username = body.username
    if body.email is not None:
        existing = await crud_user.get_user_by_email(db, body.email)
        if existing and existing.id != current_user.id:
            raise HTTPException(400, "Email already taken")
        current_user.email = body.email
    await db.flush()
    await db.refresh(current_user)
    return current_user
```

**Fix — Add schema to `app/schemas/auth.py`:**

```python
class UserUpdateRequest(BaseModel):
    username: str | None = None
    email: EmailStr | None = None
```

**Also add to `app/schemas/auth.py` imports:**
```python
from pydantic import BaseModel, EmailStr, Field
```
(EmailStr is already imported, no change needed.)

---

### FIX 1.2 — `POST /auth/change-password` — Change Password

**Priority:** 🔴 CRITICAL

**What's wrong:**
The mobile app tries `POST /auth/change-password`, then `/auth/password/change`, then `PUT /auth/password`. All 404. Users cannot change their password.

**Where:** `app/api/v1/auth.py` — no change-password route

**What the mobile sends:**
```json
{"current_password": "old_pass", "new_password": "new_pass"}
```

**Fix — Add to `app/api/v1/auth.py`:**

```python
from app.schemas.auth import ChangePasswordRequest  # ← add this schema

@router.post("/auth/change-password")
@limiter.limit("10/minute")
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Change the authenticated user's password."""
    if not current_user.password_hash:
        raise HTTPException(400, "This account uses Google sign-in")
    if not pwd_context.verify(body.current_password, current_user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    current_user.password_hash = pwd_context.hash(body.new_password)
    await db.flush()
    return {"status": "password_changed"}
```

**Fix — Add schema to `app/schemas/auth.py`:**

```python
class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=100)
```

---

### FIX 1.3 — `DELETE /favorites/{favorite_id}` — Remove Favorite

**Priority:** 🔴 CRITICAL

**What's wrong:**
The endpoint doesn't exist. The mobile app calls it, catches the error silently, and does local-only deletion. The favorite reappears on next sync.

**Where:** `app/api/v1/favorites.py` — no DELETE route

**Fix — Add to `app/api/v1/favorites.py`:**

```python
from app.core.security import get_current_user
from app.models.user import User

@router.delete("/favorites/{favorite_id}")
async def delete_favorite(
    favorite_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a favorite route."""
    fav = await db.get(Favorite, favorite_id)
    if not fav:
        raise HTTPException(404, "Favorite not found")
    if fav.user_id != current_user.id:
        raise HTTPException(403, "Not your favorite")
    await db.delete(fav)
    await db.flush()
    return {"status": "deleted", "id": favorite_id}
```

---

### FIX 1.4 — `POST /notifications/register-token` — Register FCM Token

**Priority:** 🔴 CRITICAL

**What's wrong:**
The endpoint doesn't exist. The mobile app tries this, then falls back to `POST /auth/me/fcm-token` (also doesn't exist). Push notification registration always fails silently.

**Where:** `app/api/v1/notifications.py` — no register-token route

**What the mobile sends:**
```json
{"user_id": 42, "token": "fcm_device_token_here"}
```

**Fix — Add to `app/api/v1/notifications.py`:**

```python
from pydantic import BaseModel

class FcmTokenRequest(BaseModel):
    user_id: int
    token: str

@router.post("/notifications/register-token")
async def register_fcm_token(body: FcmTokenRequest):
    """Register an FCM device token for push notifications."""
    redis = await get_redis()
    await redis.set(f"fcm:{body.user_id}", body.token, ex=2592000)  # 30 days
    return {"status": "registered"}
```

---

## SECTION 2: Data Mismatches (Mobile Gets Wrong/Empty Data)

---

### FIX 2.1 — `bus_plate` Missing from Point-to-Point ETA Response

**Priority:** 🔴 CRITICAL

**What's wrong:**
`POST /search/point-to-point` reads ETA data from Redis `route:{number}:stop:{stop_id}`. The Redis hash contains `eta_seconds`, `occupancy_level`, etc. but **no bus_plate or vehicle_id**. The mobile app's `JourneyResultModel.busPlate` always returns null. Journey results always show "No active bus" even when buses are running on that route.

**Root cause:** `estimate_route_stop_eta_payloads()` in `route_eta.py` doesn't know which vehicle it's computing for — it only receives lat/lon/speed/occupancy. The plate/vehicle_id is never written to the Redis ETA hash.

**Where:**
- `app/services/route_eta.py:115` — the payload dict that gets stored in Redis
- `app/api/v1/search.py:66-84` — the point-to-point endpoint that reads it back

**Fix — Step 1: Pass plate/vehicle_id into `estimate_route_stop_eta_payloads()`**

Change the function signature in `app/services/route_eta.py`:

```python
def estimate_route_stop_eta_payloads(
    lat: float,
    lon: float,
    speed_kmh: float,
    occupancy_level: int,
    route_number: str,
    route_id: int | None,
    route_stops: list[Stop],
    plate_number: str = "",       # ← NEW
    vehicle_id: int | None = None, # ← NEW
) -> dict[int, dict[str, Any]]:
```

And add them to the payload at line 115:

```python
payloads[stop.id] = {
    "route_number": route_number,
    "stop_id": stop.id,
    "stop_name": stop.name,
    "eta_seconds": eta_seconds,
    "eta_heuristic_seconds": heuristic_eta,
    "eta_mode": eta_mode,
    "eta_ml_seconds": eta_ml_seconds,
    "distance_m": int(distance_m + 0.5),
    "speed_kmh": round(speed_kmh, 2),
    "occupancy_level": occupancy_level,
    "computed_at": computed_at,
    "bus_plate": plate_number,          # ← NEW
    "vehicle_id": str(vehicle_id or ""), # ← NEW
}
```

**Fix — Step 2: Pass plate/vehicle_id when calling the function**

In `app/services/image_pipeline.py` (line ~331), the call already has access to `vehicle`:

```python
eta_payloads = estimate_route_stop_eta_payloads(
    validated_lat,
    validated_lon,
    speed,
    occupancy_level,
    vehicle.route.route_number,
    vehicle.route_id,
    route_stops,
    plate_number=vehicle.plate_number,  # ← NEW
    vehicle_id=vehicle.id,              # ← NEW
)
```

In `app/api/v1/search.py` journey_search (line ~179-190), the call already has `bus` data:

```python
eta_payloads = estimate_route_stop_eta_payloads(
    float(lat),
    float(lon),
    float(bus.get("speed") or 0.0),
    int(occupancy_level),
    route.route_number,
    route.id,
    eta_stops,
    plate_number=plate_number,  # ← NEW (plate_number is already extracted at line 152)
    vehicle_id=bus.get("vehicle_id"),  # ← NEW
)
```

**Fix — Step 3: Include bus data in point-to-point response**

In `app/api/v1/search.py:point_to_point_search()`, the endpoint currently only reads from Redis. It needs to also cross-reference with live vehicle positions. Add live position fetching and bus data to the response:

```python
@router.post("/search/point-to-point")
async def point_to_point_search(
    body: PointToPointSearch,
    db: AsyncSession = Depends(get_db),
):
    start = await crud_route.get_stop_by_id(db, body.start_stop_id)
    end = await crud_route.get_stop_by_id(db, body.end_stop_id)
    if not start or not end:
        raise HTTPException(404, "Stop not found")
    routes = await crud_route.get_routes_through_stops(
        db, body.start_stop_id, body.end_stop_id
    )

    redis = None
    try:
        redis = await get_redis()
    except Exception:
        redis = None

    # ← NEW: Fetch live positions so we can include bus data
    live_positions = {}
    try:
        live_positions = await crud_vehicle.get_live_positions(db)
    except Exception:
        live_positions = {}

    results = []
    for route in routes:
        key = f"route:{route.route_number}:stop:{body.start_stop_id}"
        data = {}
        if redis is not None:
            try:
                data = await redis.hgetall(key)
            except Exception:
                data = {}
        if data:
            live_eta = compute_live_eta(
                data.get("eta_seconds", 0), data.get("computed_at", 0)
            )
            if live_eta is not None:
                data["eta_live_seconds"] = live_eta

        # ← NEW: Find live buses on this route
        route_buses = [
            bus for bus in live_positions.values()
            if bus.get("route_id") == route.id
        ]

        if data:
            results.append({
                "route_number": route.route_number,
                "etas": data,
                "buses": route_buses,  # ← NEW
            })
        else:
            results.append({
                "route_number": route.route_number,
                "etas": {},
                "buses": route_buses,  # ← NEW
            })

    return {"routes": results, "start_stop": start.name, "end_stop": end.name}
```

---

### FIX 2.2 — `UserResponse` Missing `is_verified` and `google_id`

**Priority:** 🟡 MEDIUM

**What's wrong:**
The `UserResponse` schema only has `{id, username, email, role, created_at}`. The mobile app expects `is_verified` (bool) and `google_id` (String?). Both always come back as defaults (false / null) because the backend never sends them.

**Where:** `app/schemas/user.py:24-29`

**Fix — Replace `UserResponse` in `app/schemas/user.py`:**

```python
class UserResponse(UserBase):
    id: int
    is_verified: bool = False
    google_id: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True
```

No other changes needed — the SQLAlchemy `User` model already has `is_verified` and `google_id` columns, so `from_attributes=True` will pick them up automatically.

---

### FIX 2.3 — `VehiclePosition` Missing `last_updated` (ISO 8601)

**Priority:** 🟡 MEDIUM

**What's wrong:**
The backend sends `timestamp` (Unix float). The mobile app expects `last_updated` (ISO 8601 DateTime string). The mobile's `VehiclePositionModel.lastUpdated` is always null from the API. The `websocket_service.dart` then overwrites it with `DateTime.now()`, which means the "Live" badge on the route detail screen reflects "when we polled" not "when the bus sent data."

**Where:** `app/schemas/vehicle.py:45-55` and `app/crud/vehicle.py:106-117`

**Fix — Add `last_updated` to `VehiclePosition` in `app/schemas/vehicle.py`:**

```python
class VehiclePosition(BaseModel):
    vehicle_id: int
    plate_number: str
    lat: float
    lon: float
    speed: float = 0.0
    timestamp: float
    route_id: int | None = None
    assignment_id: int | None = None
    occupancy_level: int = 0
    density_level: int = 0
    last_updated: datetime | None = None  # ← NEW
```

**Fix — Populate it in `app/crud/vehicle.py:get_live_positions()` at line 106:**

```python
out[str(vid)] = {
    "vehicle_id": vid,
    "plate_number": plate,
    "lat": lat,
    "lon": lon,
    "speed": speed or 0.0,
    "timestamp": ts,
    "route_id": route_id,
    "assignment_id": assignment_id,
    "occupancy_level": occupancy,
    "density_level": occupancy,
    "last_updated": pos_at,  # ← NEW (pos_at is already Vehicle.position_updated_at)
}
```

And similarly in `get_position()` at line 168:

```python
return {
    "vehicle_id": vid,
    "plate_number": plate,
    "lat": lat,
    "lon": lon,
    "speed": speed or 0.0,
    "timestamp": ts,
    "route_id": route_id,
    "assignment_id": assignment_id,
    "occupancy_level": occupancy,
    "last_updated": pos_at,  # ← NEW
}
```

---

## SECTION 3: Redundant / Dead Data (Cleanup)

---

### FIX 3.1 — Remove `density_level` (Duplicate of `occupancy_level`)

**Priority:** 🟡 MEDIUM

**What's wrong:**
`VehiclePosition` includes both `occupancy_level` and `density_level` with the identical value. The mobile app doesn't parse `density_level`. It's dead data on the wire.

**Where:**
- `app/schemas/vehicle.py:55` — schema field
- `app/crud/vehicle.py:116` — set in `get_live_positions()`
- `app/crud/vehicle.py:177` — set in `get_position()`

**Fix — Remove from schema (`app/schemas/vehicle.py`):**

```python
class VehiclePosition(BaseModel):
    vehicle_id: int
    plate_number: str
    lat: float
    lon: float
    speed: float = 0.0
    timestamp: float
    route_id: int | None = None
    assignment_id: int | None = None
    occupancy_level: int = 0
    # density_level removed — was identical to occupancy_level
    last_updated: datetime | None = None
```

**Fix — Remove from CRUD (`app/crud/vehicle.py`):**

In `get_live_positions()` remove `"density_level": occupancy` from the dict.
In `get_position()` remove `"density_level": occupancy` from the dict.

---

### FIX 3.2 — Remove `human_count` from CV Pipeline (Duplicate of `people_count`)

**Priority:** 🟢 LOW

**What's wrong:**
The CV functions return both `human_count` and `people_count` with the same value. Only `people_count` is used in the WebSocket broadcast schema. `human_count` is dead data.

**Where:**
- `app/services/cv_engine.py` — returns both
- `app/services/yolo_detector.py` — returns both

**Fix:** Remove `human_count` from all return dicts in both files. Keep only `people_count`.

---

### FIX 3.3 — Add `inference_ms` to WebSocket CV Broadcast

**Priority:** 🟢 LOW

**What's wrong:**
`yolo_detector.py` returns `inference_ms` (detection time in milliseconds) but `live_broadcast.py:broadcast_cv_result()` doesn't include it in the WebSocket payload.

**Where:** `app/services/live_broadcast.py:93`

**Fix — Add to the cv dict in `broadcast_cv_result()`:**

```python
"cv": {
    "people_count": cv_result.get("people_count", 0),
    "face_count": cv_result.get("face_count", 0),
    "head_blob_count": cv_result.get("head_blob_count", 0),
    "crowd_density": cv_result.get("crowd_density", 0),
    "is_crowded": cv_result.get("is_crowded", False),
    "method": cv_result.get("method", "unknown"),
    "confidence": cv_result.get("confidence", 0.0),
    "foreground_ratio": cv_result.get("foreground_ratio", 0.0),
    "inference_ms": cv_result.get("inference_ms", 0.0),  # ← NEW
    "boxes": cv_result.get("boxes", []),
    "face_boxes": cv_result.get("face_boxes", []),
    "head_boxes": cv_result.get("head_boxes", []),
},
```

---

## SECTION 4: Summary of All Files to Change

| # | File | Change | Priority |
|---|------|--------|----------|
| 1 | `app/api/v1/auth.py` | Add `PATCH /auth/me` endpoint | 🔴 |
| 2 | `app/api/v1/auth.py` | Add `POST /auth/change-password` endpoint | 🔴 |
| 3 | `app/schemas/auth.py` | Add `UserUpdateRequest` schema | 🔴 |
| 4 | `app/schemas/auth.py` | Add `ChangePasswordRequest` schema | 🔴 |
| 5 | `app/api/v1/favorites.py` | Add `DELETE /favorites/{id}` endpoint | 🔴 |
| 6 | `app/api/v1/notifications.py` | Add `POST /notifications/register-token` endpoint + `FcmTokenRequest` schema | 🔴 |
| 7 | `app/api/v1/search.py` | Fetch live positions in point-to-point; include `buses` array in response | 🔴 |
| 8 | `app/services/route_eta.py` | Add `plate_number` and `vehicle_id` params; include in Redis payload | 🔴 |
| 9 | `app/services/image_pipeline.py` | Pass `plate_number` and `vehicle_id` to `estimate_route_stop_eta_payloads()` | 🔴 |
| 10 | `app/schemas/user.py` | Add `is_verified` and `google_id` to `UserResponse` | 🟡 |
| 11 | `app/schemas/vehicle.py` | Add `last_updated` field; remove `density_level` | 🟡 |
| 12 | `app/crud/vehicle.py` | Populate `last_updated`; remove `density_level` | 🟡 |
| 13 | `app/services/cv_engine.py` | Remove `human_count` from return dicts | 🟢 |
| 14 | `app/services/yolo_detector.py` | Remove `human_count` from return dicts | 🟢 |
| 15 | `app/services/live_broadcast.py` | Add `inference_ms` to CV WebSocket payload | 🟢 |

---

## SECTION 5: Complete New/Modified File Contents

### `app/schemas/auth.py` — Full additions

Add these two classes to the existing file:

```python
class UserUpdateRequest(BaseModel):
    username: str | None = None
    email: EmailStr | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=100)
```

### `app/schemas/user.py` — Full replacement of `UserResponse`

```python
class UserResponse(UserBase):
    id: int
    is_verified: bool = False
    google_id: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True
```

### `app/schemas/vehicle.py` — Full replacement of `VehiclePosition`

```python
class VehiclePosition(BaseModel):
    vehicle_id: int
    plate_number: str
    lat: float
    lon: float
    speed: float = 0.0
    timestamp: float
    route_id: int | None = None
    assignment_id: int | None = None
    occupancy_level: int = 0
    last_updated: datetime | None = None
```

### `app/api/v1/favorites.py` — Full new DELETE endpoint

Add this to the existing file (add `get_current_user` to imports):

```python
from app.core.security import get_current_user
from app.models.user import User

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

### `app/api/v1/notifications.py` — Full new register-token endpoint

Add to the existing file:

```python
from pydantic import BaseModel

class FcmTokenRequest(BaseModel):
    user_id: int
    token: str

@router.post("/notifications/register-token")
async def register_fcm_token(body: FcmTokenRequest):
    redis = await get_redis()
    await redis.set(f"fcm:{body.user_id}", body.token, ex=2592000)
    return {"status": "registered"}
```

---

## SECTION 6: Implementation Order

Do them in this order to avoid breaking dependencies:

| Step | Task | Files | Time |
|------|------|-------|------|
| 1 | Add `UserUpdateRequest` + `ChangePasswordRequest` schemas | `schemas/auth.py` | 5 min |
| 2 | Add `PATCH /auth/me` endpoint | `api/v1/auth.py` | 15 min |
| 3 | Add `POST /auth/change-password` endpoint | `api/v1/auth.py` | 15 min |
| 4 | Add `DELETE /favorites/{id}` endpoint | `api/v1/favorites.py` | 15 min |
| 5 | Add `POST /notifications/register-token` endpoint | `api/v1/notifications.py` | 10 min |
| 6 | Add `is_verified`, `google_id` to `UserResponse` | `schemas/user.py` | 5 min |
| 7 | Add `last_updated`, remove `density_level` from `VehiclePosition` | `schemas/vehicle.py` | 5 min |
| 8 | Update `get_live_positions()` and `get_position()` CRUD | `crud/vehicle.py` | 10 min |
| 9 | Add `bus_plate`/`vehicle_id` to `estimate_route_stop_eta_payloads()` | `services/route_eta.py` | 15 min |
| 10 | Pass plate/vehicle_id in `image_pipeline.py` call | `services/image_pipeline.py` | 5 min |
| 11 | Pass plate/vehicle_id in `search.py` journey_search call | `api/v1/search.py` | 5 min |
| 12 | Rewrite point-to-point to include live bus data | `api/v1/search.py` | 20 min |
| 13 | Remove `human_count` from CV pipeline | `services/cv_engine.py`, `services/yolo_detector.py` | 10 min |
| 14 | Add `inference_ms` to WebSocket CV broadcast | `services/live_broadcast.py` | 5 min |
| **Total** | | | **~2.5 hours** |
