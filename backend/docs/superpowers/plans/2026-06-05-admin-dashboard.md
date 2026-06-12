# Admin Dashboard — Complete Backend Capability Map & Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement the plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a comprehensive blueprint of every admin-facing capability in the backend, the data each endpoint requires, and a phased plan to build a full admin dashboard frontend.

**Architecture:** FastAPI backend with async SQLAlchemy, PostgreSQL, Redis (live state + CV cache), WebSocket pub/sub. Admin routes are gated by `RequireAdmin` dependency (JWT + role=admin check). The dashboard frontend will consume these REST endpoints + the `/ws/live` WebSocket for real-time fleet updates.

**Tech Stack:** FastAPI, SQLAlchemy async, PostgreSQL, Redis, WebSocket, YOLOv8 CV, scikit-learn RandomForest, Pydantic v2

---

## 1. System Topology

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ADMIN DASHBOARD SPA                          │
│  (React / Vue / Next.js — TBD by frontend team)                    │
│                                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │ Overview │ │  Fleet   │ │  Routes  │ │   ML/AI  │ │  Users   │ │
│  │  Charts  │ │  Map     │ │  Stops   │ │  Models  │ │  Drivers │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ │
│       │             │            │             │             │       │
│  ┌────┴─────────────┴────────────┴─────────────┴─────────────┴────┐ │
│  │              REST API  (/api/v1/admin/*)                        │ │
│  │              WebSocket (/ws/live)  ← real-time positions       │ │
│  └──────────────────────────┬─────────────────────────────────────┘ │
│                             │ JWT (Bearer)                          │
└─────────────────────────────┼───────────────────────────────────────┘
                              │
┌─────────────────────────────┼───────────────────────────────────────┐
│                        FASTAPI BACKEND                              │
│                             │                                       │
│  ┌──────────────────────────┴─────────────────────────────────────┐ │
│  │  admin.py  admin_dashboard.py  admin_users.py  crowd.py        │ │
│  │  assignments.py  vehicles.py  routes.py  pairing.py           │ │
│  │  tracking.py  gateway.py  search.py  favorites.py             │ │
│  │  notifications.py  auth.py  websocket.py                     │ │
│  └──────────────────────────┬─────────────────────────────────────┘ │
│                             │                                       │
│  ┌──────────┐  ┌───────────┴───────────┐  ┌────────────────────┐  │
│  │PostgreSQL│  │  Services Layer        │  │  Redis             │  │
│  │          │  │  telemetry_ingest      │  │  bus_live:{plate}  │  │
│  │ users    │  │  ai_predictor          │  │  veh:cv:{plate}    │  │
│  │ vehicles │  │  trainer               │  │  route:{num}:stop  │  │
│  │ routes   │  │  eta_engine            │  │  fcm:{user_id}     │  │
│  │ stops    │  │  cv_engine / yolo      │  │  pairing_code:{c}  │  │
│  │assignments│ │  live_broadcast (WS)    │  │  pub/sub channel   │  │
│  │trip_hist │  │  image_pipeline        │  └────────────────────┘  │
│  │raw_tele  │  │  route_eta             │                           │
│  │model_perf│  │  geocoding             │                           │
│  │favorites │  │  email_service         │                           │
│  │ratings   │  │  token_service         │                           │
│  │notif_set │  │  search_helpers        │                           │
│  │sys_set   │  │  route_validation      │                           │
│  │driver_ses│  │  redis_cache           │                           │
│  └──────────┘  └────────────────────────┘                           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Complete Admin Capability Inventory

### 2.1 Admin User Management (`/api/v1/admin/users/*`)

| Method | Endpoint | Auth | Request Body / Params | Response | Description |
|--------|----------|------|----------------------|----------|-------------|
| POST | `/api/v1/admin/users/create` | Admin JWT | `{username, email, password, role: "driver"\|"admin"}` | `UserResponse` | Create driver or admin account |
| GET | `/api/v1/admin/users/list` | None* | `?skip=0&limit=100` | `UserResponse[]` | Paginated user list |
| GET | `/api/v1/admin/users/me` | Admin JWT | — | `UserResponse` | Current admin profile |
| GET | `/api/v1/admin/users/search` | Admin JWT | `?query=foo&limit=50` | `UserResponse[]` | Search by username/email |
| GET | `/api/v1/admin/users/drivers` | Admin JWT | — | `UserResponse[]` | All drivers |
| GET | `/api/v1/admin/users/admins` | Admin JWT | — | `UserResponse[]` | All admins |
| PUT | `/api/v1/admin/users/update/{user_id}` | Admin JWT | `{username?, email?, password?, role?}` | `UserResponse` | Partial update user |
| DELETE | `/api/v1/admin/users/delete/{user_id}` | Admin JWT | — | `{detail}` | Delete user |

**Data model:** `User {id, username, email, password_hash, role, google_id, is_verified, created_by_id, created_at}`

---

### 2.2 Dashboard Analytics (`/api/v1/admin/dashboard/*`)

| Method | Endpoint | Auth | Params | Response Fields | Description |
|--------|----------|------|--------|-----------------|-------------|
| GET | `/api/v1/admin/dashboard/summary` | Admin JWT | — | `active_assignments, vehicles, routes, users, telemetry_last_24h` | KPI cards |
| GET | `/api/v1/admin/dashboard/assignments-over-time` | Admin JWT | `?days=7` (1-90) | `{labels: date[], data: count[]}` | Bar chart |
| GET | `/api/v1/admin/dashboard/occupancy-distribution` | Admin JWT | — | `{labels: ["Level 0","Level 1","Level 2"], data: count[]}` | Pie/donut chart |
| GET | `/api/v1/admin/dashboard/eta-accuracy` | Admin JWT | — | `{heuristic_mae, ml_mae}` | Model comparison |
| GET | `/api/v1/admin/dashboard/route-usage` | Admin JWT | `?days=30` (1-90) | `{labels: route_number[], data: trip_count[]}` | Horizontal bar |
| GET | `/api/v1/admin/dashboard/telemetry-volume` | Admin JWT | — | `{labels: hour[], data: count[]}` | Time-series area chart |

---

### 2.3 ML / AI Management (`/api/v1/admin/ml/*`)

| Method | Endpoint | Auth | Body | Response | Description |
|--------|----------|------|------|----------|-------------|
| GET | `/api/v1/admin/ml/status` | Admin JWT | — | `{model_loaded: bool, model_version: str\|null}` | Model health |
| POST | `/api/v1/admin/ml/train` | Admin JWT | — | `{success, message}` | Trigger retraining from trip_history |

**Training pipeline:** `trip_history` → feature engineering (15 features) → `RandomForestRegressor` → saved to `delay_predictor.joblib` → lazy-loaded by `ai_predictor.py`

**Features used:** `route_id, stop_id, stop_sequence, remaining_stops, distance_m, base_dwell_time, peak_multiplier, hour, day_of_week, is_peak, occupancy_level, heuristic_eta, is_weekend, is_night, month`

---

### 2.4 ETA Preview & Settings (`/api/v1/admin/eta/*`, `/api/v1/admin/settings`)

| Method | Endpoint | Auth | Body/Params | Response | Description |
|--------|----------|------|-------------|----------|-------------|
| POST | `/api/v1/admin/eta/preview` | Admin JWT | `{lat1, lon1, lat2, lon2, num_stops, base_dwell_time, stop_id?, occupancy_level}` | `{eta_seconds, heuristic_eta_seconds, mode}` | Compare heuristic vs ML ETA |
| GET | `/api/v1/admin/settings` | Admin JWT | — | `{use_ml_for_prod: bool}` | Read runtime toggle |
| PUT | `/api/v1/admin/settings` | Admin JWT | `{use_ml_for_prod: bool}` | `{use_ml_for_prod: bool}` | Toggle ML vs heuristic |

---

### 2.5 Data Cleanup (`/api/v1/admin/cleanup`)

| Method | Endpoint | Auth | Response | Description |
|--------|----------|------|----------|-------------|
| POST | `/api/v1/admin/cleanup` | Admin JWT | `{raw_telemetry_deleted, trip_history_deleted}` | Run retention policy |

**Retention:** `RAW_TELEMETRY_RETENTION_DAYS` and `TRIP_HISTORY_RETENTION_DAYS` from env config.

---

### 2.6 ML Toggle (legacy endpoint)

| Method | Endpoint | Auth | Response | Description |
|--------|----------|------|----------|-------------|
| GET | `/api/v1/admin/use-ml` | None | `{use_ml_for_prod: bool}` | Read current ETA mode |

---

### 2.7 Vehicle Fleet Management (`/api/v1/vehicles/*`, `/api/v1/admin/vehicles/*`)

| Method | Endpoint | Auth | Body/Params | Response | Description |
|--------|----------|------|-------------|----------|-------------|
| POST | `/api/v1/vehicles` | Admin JWT | `{plate_number, device_id, bus_type?, capacity?, is_active}` | `VehicleResponse` | Register new vehicle |
| GET | `/api/v1/vehicles` | None | `?skip=0&limit=100` | `VehicleResponse[]` | List all vehicles |
| GET | `/api/v1/vehicles/{vehicle_id}` | None | — | `VehicleResponse` | Single vehicle detail |
| PUT | `/api/v1/vehicles/{vehicle_id}` | Admin JWT | `{route_id?}` | `VehicleResponse` | Assign route to vehicle |
| GET | `/api/v1/vehicles/positions` | None | — | `LivePositionsEnvelope {positions: {str: VehiclePosition}, timestamp}` | All live bus positions |
| GET | `/api/v1/vehicles/positions/{vehicle_id}` | None | — | `VehiclePosition` | Single bus position |
| POST | `/api/v1/vehicles/telemetry` | None (rate-limited) | `{device_id, lat, lon, speed, pixel_count?, raw_payload?}` | Telemetry result | Ingest GPS data |

**VehicleResponse fields:** `id, plate_number, device_id, bus_type, capacity, is_active, route_id, route_number, last_lat, last_lon, speed, position_updated_at`

**VehiclePosition fields:** `vehicle_id, plate_number, lat, lon, speed, timestamp, route_id, assignment_id, occupancy_level, last_updated`

---

### 2.8 Bus Dashboard Pairing (`/api/v1/admin/vehicles/{id}/*`, `/api/v1/pair/*`)

| Method | Endpoint | Auth | Body | Response | Description |
|--------|----------|------|------|----------|-------------|
| POST | `/api/v1/admin/vehicles/{vehicle_id}/generate-pairing-code` | Admin JWT | — | `{code, vehicle_id, plate_number, device_id, expires_in_seconds, message}` | Generate 5-min pairing code |
| POST | `/api/v1/pair/verify` | None | `{code, password}` | `{status, vehicle_id, plate_number, device_id, message}` | Verify code, set dashboard password |
| POST | `/api/v1/admin/vehicles/{vehicle_id}/unpair` | Admin JWT | — | `{status, vehicle_id}` | Remove dashboard pairing |

---

### 2.9 Route & Stop Management (`/api/v1/routes/*`, `/api/v1/stops/*`)

| Method | Endpoint | Auth | Body/Params | Response | Description |
|--------|----------|------|-------------|----------|-------------|
| POST | `/api/v1/routes` | Admin JWT | `{route_number, direction, name?, origin?, destination?, stops: [{stop_id, sequence_order}]}` | `RouteResponse` | Create route with stop sequence |
| GET | `/api/v1/routes` | None | `?skip=0&limit=100` | `RouteResponse[]` | List routes |
| GET | `/api/v1/routes/{route_id}` | None | — | `RouteWithStops` | Route + ordered stops |
| GET | `/api/v1/routes/{route_number}/etas` | None | — | `{route_number, etas: {stop_id: {stop_name, eta_seconds, distance_m, occupancy_level}}}` | Live ETAs per stop |
| POST | `/api/v1/stops` | Admin JWT | `{name, lat, lon, base_dwell_time?, is_terminal?, peak_multiplier?}` | `StopResponse` | Create stop |
| GET | `/api/v1/stops` | None | `?skip=0&limit=100` | `StopResponse[]` | List stops |
| GET | `/api/v1/stops/{stop_id}` | None | — | `StopResponse` | Single stop |

**RouteResponse fields:** `id, route_number, direction, name, origin, destination`
**RouteWithStops:** adds `stops: StopResponse[]`
**StopResponse fields:** `id, name, lat, lon, base_dwell_time, is_terminal, peak_multiplier`

---

### 2.10 Assignment Management (`/api/v1/assignments/*`)

| Method | Endpoint | Auth | Body | Response | Description |
|--------|----------|------|------|----------|-------------|
| GET | `/api/v1/assignments/active` | Admin JWT | — | `AssignmentOut[]` | Active driver-vehicle-route assignments |
| POST | `/api/v1/assignments/start` | Admin JWT | `{driver_id, vehicle_id, route_id}` | `AssignmentOut` | Start new assignment |
| POST | `/api/v1/assignments/end` | Admin JWT | `{assignment_id}` | `{status, assignment_id}` | End assignment |

**AssignmentOut fields:** `id, driver_id, vehicle_id, route_id, start_time, end_time, status, driver_username, vehicle_plate, route_number`

---

### 2.11 Crowd Density / CV Results (`/api/v1/admin/crowd/*`)

| Method | Endpoint | Auth | Response Fields | Description |
|--------|----------|------|-----------------|-------------|
| GET | `/api/v1/admin/crowd/{plate_number}` | Admin JWT | `{plate_number, cv: {occupancy_level, people_count, face_count, head_blob_count, crowd_density, confidence, method, updated_at, image_path}}` | Latest CV analysis for a bus |

---

### 2.12 Telemetry Ingestion (`/api/v1/telemetry`, `/api/v1/gateway/esp32/telemetry`)

| Method | Endpoint | Auth | Body | Response | Description |
|--------|----------|------|------|----------|-------------|
| POST | `/api/v1/telemetry` | None (rate 300/min) | `{device_id, lat, lon, speed?, pixel_count?, raw_payload?}` | Telemetry result | GPS-only telemetry (SIM7600) |
| POST | `/api/v1/gateway/esp32/telemetry` | None (rate 300/min) | multipart: `device_id, lat, lon, speed, image, plate_number?, bus_type?, bus_capacity?, occupancy_level?` | Telemetry result | GPS + image (ESP32-CAM) |

**Telemetry pipeline (9 steps):**
1. Vehicle resolution (auto-provision if new device_id)
2. GPS validation (outlier + on-route check)
3. Image storage + YOLOv8 CV analysis (if image provided)
4. Raw telemetry persistence (bronze layer)
5. Redis live pipeline update
6. ETA computation (heuristic + optional ML)
7. Vehicle position update in DB
8. Trip history recording (for ML training)
9. WebSocket broadcast (position + cv_result)

---

### 2.13 Search & Journey Planning (`/api/v1/search/*`)

| Method | Endpoint | Auth | Body | Response | Description |
|--------|----------|------|------|----------|-------------|
| POST | `/api/v1/search/point-to-point` | None | `{start_stop_id, end_stop_id, max_routes?, max_buses?}` | `{routes: [{route_number, etas, buses: [{vehicle_id, plate, lat, lon, speed, occupancy, eta_to_start, eta_to_end, position_age}]}], start_stop, end_stop}` | Stop-to-stop search |
| POST | `/api/v1/search/journey` | None | `{start_query?, end_query?, start_lat?, start_lon?, end_lat?, end_lon?, max_routes?, max_buses?}` | `{start: {query, lat, lon, stop_id, stop_name, distance_m}, end: {...}, routes: [...]}` | Geocoded journey search |

---

### 2.14 Favorites & Ratings (`/api/v1/favorites/*`, `/api/v1/ratings/*`)

| Method | Endpoint | Auth | Body/Params | Response | Description |
|--------|----------|------|-------------|----------|-------------|
| POST | `/api/v1/favorites` | JWT | `{user_id, route_id, nickname?}` | `{id, user_id, route_id, nickname}` | Save favorite route |
| GET | `/api/v1/favorites/{user_id}` | JWT | — | `Favorite[]` | List user favorites |
| DELETE | `/api/v1/favorites/{favorite_id}` | JWT | — | `{status, id}` | Remove favorite |
| POST | `/api/v1/ratings` | JWT | `{user_id, assignment_id, score (1-5), comment?}` | `{id, score}` | Rate a journey |
| GET | `/api/v1/ratings/{assignment_id}` | JWT | — | `Rating[]` | Ratings for assignment |

---

### 2.15 Notifications (`/api/v1/notifications/*`)

| Method | Endpoint | Auth | Body/Params | Response | Description |
|--------|----------|------|-------------|----------|-------------|
| POST | `/api/v1/notifications/settings` | JWT | `{user_id, route_id, stop_id?, lead_time_minutes}` | `{id, lead_time_minutes}` | Set proximity alert |
| GET | `/api/v1/notifications/settings/{user_id}` | JWT | — | `NotificationSetting[]` | List user notification settings |
| POST | `/api/v1/notifications/register-token` | JWT | `{user_id, token}` | `{status}` | Register FCM push token |

---

### 2.16 Authentication (`/api/v1/auth/*`)

| Method | Endpoint | Auth | Body | Response | Description |
|--------|----------|------|------|----------|-------------|
| POST | `/api/v1/auth/register` | None | `{username, email, password}` | `UserResponse` | Passenger signup |
| POST | `/api/v1/auth/login` | None | `{username, password}` | `{access_token, token_type}` | Email/password login |
| POST | `/api/v1/auth/google` | None | `{id_token}` | `{access_token, token_type}` | Google OAuth |
| GET | `/api/v1/auth/me` | JWT | — | `UserResponse` | Current user profile |
| PATCH | `/api/v1/auth/me` | JWT | `{username?, email?}` | `UserResponse` | Update profile |
| POST | `/api/v1/auth/refresh` | JWT | — | `{access_token, token_type}` | Refresh JWT |
| POST | `/api/v1/auth/change-password` | JWT | `{current_password, new_password}` | `{status}` | Change password |
| POST | `/api/v1/auth/driver-login` | None | `{username, password, device_id, bus_token}` | `{access_token, session_id, driver_id, vehicle_id, device_id}` | Driver login (bus-bound) |
| POST | `/api/v1/auth/driver-logout` | JWT | `{session_id}` | `{status, session_id}` | End driver session |
| POST | `/api/v1/auth/bus-dashboard/login` | None | `{vehicle_id, device_id, password}` | `{access_token, vehicle_id, device_id}` | Bus dashboard device login |
| POST | `/api/v1/auth/verify-email` | None | `{token}` | `{status}` | Verify email |
| POST | `/api/v1/auth/resend-verification` | None | `{email}` | `{status}` | Resend verification |
| POST | `/api/v1/auth/forgot-password` | None | `{email}` | `{status}` | Request password reset |
| POST | `/api/v1/auth/reset-password` | None | `{token, new_password}` | `{status}` | Reset password |

---

### 2.17 WebSocket Endpoints

| Protocol | Endpoint | Auth | Direction | Message Types | Description |
|----------|----------|------|-----------|---------------|-------------|
| WS | `/api/v1/ws/live` | Admin JWT (query param) | Server → Client | `vehicle_position, cv_result, heartbeat` | Real-time fleet stream (admin) |
| WS | `/api/v1/ws/mobile` | JWT (query param) | Bidirectional | Client: `subscribe{route_id}, unsubscribe, ping` → Server: `vehicle_position, cv_result, heartbeat, pong` | Mobile passenger stream |

**vehicle_position message:**
```json
{
  "type": "vehicle_position",
  "vehicle_id": 1,
  "plate_number": "ABC-123",
  "lat": 9.032,
  "lon": 38.746,
  "speed": 25.0,
  "route_id": 5,
  "timestamp": 1717185600.0,
  "bus_type": "Anbessa",
  "occupancy_level": 1,
  "eta_payloads": { "stop_id": { "stop_name": "...", "eta_seconds": 120, "distance_m": 800 } }
}
```

---

## 3. Database Schema (All Tables)

| Table | Key Columns | Relationships |
|-------|-------------|---------------|
| `users` | id, username, email, password_hash, role, google_id, is_verified, created_by_id, created_at | → assignments, favorites, ratings, notification_settings, driver_sessions |
| `vehicles` | id, plate_number, device_id, bus_type, capacity, is_active, route_id, last_lat, last_lon, speed, position_updated_at, dashboard_password_hash | → route, assignments, raw_telemetry, driver_sessions |
| `routes` | id, route_number, direction, name, origin, destination, active | → vehicles, route_stops, assignments, favorites, notification_settings |
| `stops` | id, name, lat, lon, base_dwell_time, is_terminal, peak_multiplier | → route_stops, trip_history |
| `route_stops` | route_id (FK), stop_id (FK), sequence_order | → route, stop |
| `assignments` | id, driver_id (FK), vehicle_id (FK), route_id (FK), start_time, end_time, status | → driver, vehicle, route, trip_history, ratings |
| `raw_telemetry` | id, timestamp, vehicle_id (FK), raw_lat, raw_lon, pixel_count, raw_payload (JSONB) | → vehicle |
| `trip_history` | id, assignment_id (FK), stop_id (FK), arrival_time, dwell_time, occupancy_level, heuristic_eta, ml_eta, actual_travel_time | → assignment, stop, model_performance |
| `model_performance` | id, trip_history_id (FK), heuristic_error, ml_error, timestamp | → trip_history |
| `favorites` | id, user_id (FK), route_id (FK), nickname | → user, route |
| `ratings` | id, user_id (FK), assignment_id (FK), score, comment, timestamp | → user, assignment |
| `notification_settings` | id, user_id (FK), route_id (FK), stop_id (FK), lead_time_minutes | → user, route, stop |
| `system_settings` | id, key, value | — (key-value store) |
| `driver_bus_sessions` | id, driver_id (FK), vehicle_id (FK), login_at, logout_at, status | → driver, vehicle |

---

## 4. Redis Key Patterns

| Pattern | Type | Purpose |
|---------|------|---------|
| `bus_live:{plate}` | Hash | Live bus state (lat, lon, speed, occupancy_level, assignment_id) |
| `veh:cv:{plate}` | Hash | Latest CV result (people_count, crowd_density, confidence, method, image_path, updated_at) |
| `route:{route_number}:stop:{stop_id}` | Hash | Pre-computed ETA for a stop (eta_seconds, computed_at, distance_m, occupancy_level, stop_name) |
| `fcm:{user_id}` | String | FCM push token (30-day TTL) |
| `pairing_code:{code}` | String | Bus dashboard pairing code (5-min TTL, value=vehicle_id) |
| `ws_pubsub` | Pub/Sub channel | Cross-worker WebSocket broadcast |

---

## 5. Admin Dashboard Frontend — Page Map

### 5.1 Overview / Home
- **KPI Cards:** Active assignments, total vehicles, total routes, total users, telemetry (24h)
- **Chart 1:** Assignments over time (line/bar, selectable 7/30/90 days)
- **Chart 2:** Occupancy distribution (donut: Level 0/1/2)
- **Chart 3:** ETA accuracy comparison (bar: heuristic MAE vs ML MAE)
- **Chart 4:** Route usage (horizontal bar, top routes by trip count)
- **Chart 5:** Telemetry volume (area chart, per hour last 24h)

### 5.2 Fleet Map
- **Live map** with bus markers (color-coded by occupancy: green/yellow/red)
- **Click marker** → bus detail panel (plate, route, speed, occupancy, last update)
- **Data source:** WebSocket `/ws/live` (real-time) + REST `GET /vehicles/positions` (initial load)
- **Filters:** By route, by occupancy level, active/inactive

### 5.3 Vehicles Management
- **Table:** All vehicles with columns (plate, device_id, bus_type, capacity, route, status, last position)
- **Actions:** Register new, edit (assign route), view position, generate pairing code, unpair
- **Detail page:** Vehicle info + position history + active assignment + CV results

### 5.4 Routes & Stops
- **Routes table:** route_number, direction, name, origin, destination, stop count, active
- **Actions:** Create route (with stop sequence), view route detail
- **Route detail:** Ordered stops list + map preview + live ETAs per stop
- **Stops table:** name, lat, lon, dwell time, is_terminal, peak_multiplier
- **Actions:** Create stop, view on map

### 5.5 Assignments
- **Active assignments table:** driver, vehicle, route, start time, duration
- **Actions:** Start assignment (select driver + vehicle + route), end assignment
- **Assignment history:** Filterable by driver, vehicle, route, date range

### 5.6 Users & Drivers
- **Users table:** username, email, role, verified, created_at
- **Actions:** Create user (driver/admin), edit, delete, search
- **Drivers list:** Filtered view of role=driver
- **Driver detail:** Profile + active session + assignment history

### 5.7 ML / AI Center
- **Model status card:** Loaded? Version? Last trained?
- **ETA accuracy chart:** Heuristic vs ML MAE over time
- **Training controls:** "Retrain now" button + status message
- **ETA preview tool:** Enter two coordinates → see heuristic vs ML ETA side-by-side
- **Feature importance chart:** From RandomForest model

### 5.8 Crowd Density / CV
- **Per-vehicle CV results:** Latest image, people count, crowd density, confidence
- **Occupancy trend:** Over time for a selected vehicle
- **Image gallery:** Recent captured images per vehicle

### 5.9 System Settings
- **Toggle:** Use ML for production ETA (use_ml_for_prod)
- **Cleanup:** "Run data retention cleanup" button + results
- **System health:** Database status, Redis status, model status

### 5.10 Telemetry Monitor
- **Raw telemetry stream:** Recent entries (device_id, lat, lon, timestamp)
- **Volume chart:** Telemetry per hour (reuse dashboard endpoint)
- **Ingestion health:** Messages/minute, rejection rate

---

## 6. Implementation Phases

### Phase 1: Foundation — Auth + Layout + Overview
**Goal:** Admin can log in and see the dashboard overview page.

**Files to create:**
- `admin-dashboard/src/main.tsx` — App entry with auth guard
- `admin-dashboard/src/layouts/AdminLayout.tsx` — Sidebar + header + content area
- `admin-dashboard/src/pages/Overview.tsx` — KPI cards + 5 charts
- `admin-dashboard/src/api/client.ts` — Axios/fetch client with JWT interceptor
- `admin-dashboard/src/api/admin.ts` — All admin API functions
- `admin-dashboard/src/hooks/useWebSocket.ts` — WebSocket hook for `/ws/live`

**API endpoints consumed:**
- `POST /api/v1/auth/login`
- `GET /api/v1/admin/dashboard/summary`
- `GET /api/v1/admin/dashboard/assignments-over-time`
- `GET /api/v1/admin/dashboard/occupancy-distribution`
- `GET /api/v1/admin/dashboard/eta-accuracy`
- `GET /api/v1/admin/dashboard/route-usage`
- `GET /api/v1/admin/dashboard/telemetry-volume`
- `WS /api/v1/ws/live`

### Phase 2: Fleet Map + Vehicle Management
**Goal:** Interactive map with live bus positions + vehicle CRUD.

**Files to create:**
- `admin-dashboard/src/pages/FleetMap.tsx` — Map with bus markers
- `admin-dashboard/src/pages/Vehicles.tsx` — Vehicle table + register/edit
- `admin-dashboard/src/pages/VehicleDetail.tsx` — Single vehicle view
- `admin-dashboard/src/components/BusMarker.tsx` — Map marker component
- `admin-dashboard/src/components/PairingModal.tsx` — Generate pairing code UI

**API endpoints consumed:**
- `GET /api/v1/vehicles/positions`
- `GET /api/v1/vehicles`
- `POST /api/v1/vehicles`
- `PUT /api/v1/vehicles/{id}`
- `POST /api/v1/admin/vehicles/{id}/generate-pairing-code`
- `POST /api/v1/admin/vehicles/{id}/unpair`

### Phase 3: Routes, Stops & Assignments
**Goal:** Full CRUD for routes, stops, and assignment management.

**Files to create:**
- `admin-dashboard/src/pages/Routes.tsx` — Routes table + create
- `admin-dashboard/src/pages/RouteDetail.tsx` — Route with ordered stops
- `admin-dashboard/src/pages/Stops.tsx` — Stops table + create
- `admin-dashboard/src/pages/Assignments.tsx` — Active assignments + start/end

**API endpoints consumed:**
- `GET /api/v1/routes`, `POST /api/v1/routes`, `GET /api/v1/routes/{id}`
- `GET /api/v1/stops`, `POST /api/v1/stops`, `GET /api/v1/stops/{id}`
- `GET /api/v1/assignments/active`, `POST /api/v1/assignments/start`, `POST /api/v1/assignments/end`

### Phase 4: User & Driver Management
**Goal:** Admin can create, edit, delete, and search users.

**Files to create:**
- `admin-dashboard/src/pages/Users.tsx` — Users table + create/edit
- `admin-dashboard/src/pages/Drivers.tsx` — Filtered driver list
- `admin-dashboard/src/pages/UserDetail.tsx` — User profile + history

**API endpoints consumed:**
- `GET /api/v1/admin/users/list`, `POST /api/v1/admin/users/create`
- `GET /api/v1/admin/users/search`, `GET /api/v1/admin/users/drivers`
- `PUT /api/v1/admin/users/update/{id}`, `DELETE /api/v1/admin/users/delete/{id}`

### Phase 5: ML/AI Center + ETA Preview
**Goal:** Model management, training, and ETA comparison tool.

**Files to create:**
- `admin-dashboard/src/pages/MLCenter.tsx` — Model status + training
- `admin-dashboard/src/pages/EtaPreview.tsx` — Coordinate input + ETA comparison
- `admin-dashboard/src/components/ModelStatusCard.tsx`
- `admin-dashboard/src/components/EtaComparisonChart.tsx`

**API endpoints consumed:**
- `GET /api/v1/admin/ml/status`, `POST /api/v1/admin/ml/train`
- `POST /api/v1/admin/eta/preview`
- `GET /api/v1/admin/settings`, `PUT /api/v1/admin/settings`

### Phase 6: Crowd Density + Telemetry Monitor
**Goal:** CV results viewer and telemetry health monitor.

**Files to create:**
- `admin-dashboard/src/pages/CrowdDensity.tsx` — Per-vehicle CV results
- `admin-dashboard/src/pages/TelemetryMonitor.tsx` — Telemetry stream + volume

**API endpoints consumed:**
- `GET /api/v1/admin/crowd/{plate_number}`
- `GET /api/v1/admin/dashboard/telemetry-volume`

### Phase 7: System Settings + Cleanup + Health
**Goal:** Runtime configuration and data management.

**Files to create:**
- `admin-dashboard/src/pages/Settings.tsx` — ML toggle + cleanup + health

**API endpoints consumed:**
- `GET /api/v1/admin/settings`, `PUT /api/v1/admin/settings`
- `POST /api/v1/admin/cleanup`
- `GET /health`

---

## 7. Engineering Risk Analysis

| Risk | Impact | Mitigation |
|------|--------|------------|
| WebSocket reconnection on token expiry | Fleet map freezes | Auto-refresh JWT before expiry; reconnect WS with new token |
| Large telemetry table slows dashboard queries | Slow chart loading | Add DB indexes on `timestamp`; use materialized views for aggregates |
| ML model training blocks API | Request timeout | Run training as background task (Celery/ARQ); return immediately |
| Redis failure | No live positions | Graceful fallback to REST polling; show "last known" positions |
| CV image storage grows unbounded | Disk full | Implement image retention policy; store thumbnails only |
| Admin JWT in WS query param | Token in server logs | Use short-lived WS tokens; rotate on reconnect |
| Concurrent assignment start for same vehicle | Data inconsistency | DB-level unique constraint on active assignment per vehicle |

---

## 8. Backend Gaps to Address

These are missing features the admin dashboard needs that don't exist yet in the backend:

| Gap | Suggested Endpoint | Description |
|-----|-------------------|-------------|
| No paginated assignment history | `GET /api/v1/assignments?status=&driver_id=&vehicle_id=&skip=&limit=` | Filter + paginate all assignments |
| No vehicle delete | `DELETE /api/v1/vehicles/{id}` | Remove a vehicle |
| No route update/delete | `PUT /api/v1/routes/{id}`, `DELETE /api/v1/routes/{id}` | Edit/remove routes |
| No stop update/delete | `PUT /api/v1/stops/{id}`, `DELETE /api/v1/stops/{id}` | Edit/remove stops |
| No bulk user operations | `POST /api/v1/admin/users/bulk-create` | Import drivers from CSV |
| No assignment history per driver/vehicle | `GET /api/v1/assignments/history?driver_id=&vehicle_id=` | Filtered history |
| No system audit log | `GET /api/v1/admin/audit-log` | Track admin actions |
| No notification broadcast | `POST /api/v1/admin/notifications/broadcast` | Send push to all users |
| No export endpoint | `GET /api/v1/admin/export/telemetry?format=csv&from=&to=` | Data export |
| No driver session list | `GET /api/v1/admin/driver-sessions?status=active` | View active driver sessions |

---

## 9. Summary — What an Admin Can Do Today

### User Management
- Create driver/admin accounts
- List, search, update, delete users
- Filter by role (drivers, admins)

### Fleet Management
- Register vehicles (plate, device_id, bus_type, capacity)
- Assign routes to vehicles
- View live positions (map + table)
- Generate/unpair bus dashboard pairing codes
- Ingest telemetry (GPS + optional CV image)

### Route & Stop Management
- Create routes with ordered stop sequences
- Create stops with GPS coordinates and dwell time parameters
- View live ETAs per route-stop

### Assignment Management
- Start assignments (driver + vehicle + route)
- End assignments
- View active assignments with driver/vehicle/route details

### Analytics & Monitoring
- Dashboard summary (5 KPIs)
- Assignments over time chart
- Occupancy distribution (pie chart)
- ETA accuracy comparison (heuristic vs ML)
- Route usage ranking
- Telemetry volume (per hour)
- Real-time fleet WebSocket stream

### ML/AI Management
- Check model status and version
- Trigger model retraining from trip_history
- Preview heuristic vs ML ETA for any two points
- Toggle ML vs heuristic for production

### Crowd Density
- View latest CV results per vehicle (people count, density, confidence, method)

### System
- Toggle use_ml_for_prod setting
- Run data retention cleanup
- Health check (DB + Redis status)

---

*Plan complete and saved to `docs/superpowers/plans/2026-06-05-admin-dashboard.md`.*

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
