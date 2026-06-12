---
title: "BusTrack Admin Dashboard — Complete Implementation Plan"
author: "Yohannes"
date: "June 9, 2026"
---

# BusTrack Admin Dashboard — Complete Implementation Plan

### Full Next.js Dashboard Built on the Existing FastAPI Backend

**Author:** Yohannes
**Date:** June 9, 2026
**Document Version:** 1.0
**Purpose:** Complete architecture, page-by-page specification, API integration map, and implementation plan for a new admin dashboard built from scratch against the existing FastAPI backend

---

# Table of Contents

1. [Introduction](#1-introduction)
2. [Backend API Surface — Complete Reference](#2-backend-api-surface--complete-reference)
3. [Dashboard Architecture](#3-dashboard-architecture)
4. [Page-by-Page Specification](#4-page-by-page-specification)
5. [API Integration Map](#5-api-integration-map)
6. [WebSocket Real-Time Layer](#6-websocket-real-time-layer)
7. [Component Library](#7-component-library)
8. [Auth & Security](#8-auth--security)
9. [Data Models & Types](#9-data-models--types)
10. [Implementation Phases](#10-implementation-phases)
11. [File Structure](#11-file-structure)
12. [Appendix — Full Endpoint Catalog](#12-appendix--full-endpoint-catalog)

---

# 1. Introduction

## 1.1 Purpose

This document is a **complete implementation blueprint** for a new BusTrack admin dashboard built with Next.js 14 (App Router), TypeScript, Tailwind CSS, and shadcn/ui. It is designed against the **existing FastAPI backend** at `/api/v1/` — no backend changes are needed.

The dashboard gives a system administrator full control over:

- Fleet: vehicles, routes, stops
- People: drivers, admins, passengers
- Operations: live assignments, ride lifecycle, real-time fleet map
- Intelligence: ML model management, ETA accuracy, analytics
- Hardware: device pairing, crowd density, telemetry

## 1.2 Backend Summary

| Aspect | Detail |
|--------|--------|
| Framework | FastAPI (async Python) |
| Database | PostgreSQL + SQLAlchemy async |
| Cache | Redis (live state + Pub/Sub) |
| Auth | JWT (HS256, 24h expiry) |
| Total HTTP endpoints | 67 |
| WebSocket endpoints | 2 (`/ws/live`, `/ws/mobile`) |
| Roles | `admin`, `driver`, `passenger` |
| API prefix | `/api/v1` |

## 1.3 Design Principles

1. **Backend-first** — every feature maps to an existing API endpoint; no backend modifications
2. **No invented data** — every field displayed comes from a real schema
3. **Progressive disclosure** — summary cards → detail tables → drill-down pages
4. **Real-time where it matters** — live map, live positions, CV results via WebSocket
5. **Mobile-responsive** — sidebar collapses, tables scroll, maps resize

---

# 2. Backend API Surface — Complete Reference

## 2.1 Auth Endpoints

### POST /api/v1/auth/login
- **Auth:** None
- **Body:** `{ username: string, password: string }`
- **Response:** `{ access_token: string, token_type: "bearer" }`
- **Purpose:** Admin login — returns JWT stored as `auth_token` cookie

### POST /api/v1/auth/register
- **Auth:** None
- **Body:** `{ username: string, email: string, password: string }`
- **Response:** `{ id, username, email, role="passenger", is_verified, google_id, created_at }`
- **Purpose:** Self-registration (passenger role)

### POST /api/v1/auth/google
- **Auth:** None
- **Body:** `{ id_token: string }` (Google OAuth)
- **Response:** `{ access_token, token_type }`
- **Purpose:** Google sign-in

### GET /api/v1/auth/me
- **Auth:** JWT
- **Response:** `{ id, username, email, role, is_verified, google_id, created_at }`
- **Purpose:** Current user profile — used to determine role in dashboard

### PATCH /api/v1/auth/me
- **Auth:** JWT
- **Body:** `{ username?: string, email?: string }`
- **Response:** `UserResponse`
- **Purpose:** Update own profile

### POST /api/v1/auth/change-password
- **Auth:** JWT
- **Body:** `{ current_password: string, new_password: string }`
- **Response:** `{ status: "password_changed" }`
- **Purpose:** Change own password

### POST /api/v1/auth/refresh
- **Auth:** JWT
- **Response:** `{ access_token, token_type }`
- **Purpose:** Extend session

### POST /api/v1/auth/driver-login
- **Auth:** None
- **Body:** `{ username, password, device_id, bus_token }`
- **Response:** `{ access_token, token_type, session_id, driver_id, vehicle_id, device_id }`
- **Purpose:** Driver login tied to a physical bus

### POST /api/v1/auth/driver-logout
- **Auth:** JWT
- **Body:** `{ session_id: int }`
- **Response:** `{ status: "logged_out", session_id }`
- **Purpose:** End driver session

### POST /api/v1/auth/bus-dashboard/login
- **Auth:** None
- **Body:** `{ vehicle_id: int, device_id: string, password: string }`
- **Response:** `{ access_token, token_type, vehicle_id, device_id }`
- **Purpose:** Physical bus device auth

### POST /api/v1/auth/verify-email
- **Auth:** None
- **Body:** `{ token: string }`
- **Response:** `{ status: "verified" | "already_verified" }`

### POST /api/v1/auth/resend-verification
- **Auth:** None
- **Body:** `{ email: string }`
- **Response:** `{ status: "sent" }`

### POST /api/v1/auth/forgot-password
- **Auth:** None
- **Body:** `{ email: string }`
- **Response:** `{ status: "sent" }`

### POST /api/v1/auth/reset-password
- **Auth:** None
- **Body:** `{ token: string, new_password: string }`
- **Response:** `{ status: "reset" }`

---

## 2.2 Admin Dashboard Analytics Endpoints

### GET /api/v1/admin/dashboard/summary
- **Auth:** RequireAdmin
- **Response:** `{ active_assignments: int, vehicles: int, routes: int, users: int, telemetry_last_24h: int }`
- **Purpose:** KPI cards on main dashboard

### GET /api/v1/admin/dashboard/assignments-over-time
- **Auth:** RequireAdmin
- **Query:** `days: int = 7` (1–90)
- **Response:** `{ labels: string[], data: int[] }`
- **Purpose:** Line/bar chart of assignments per day

### GET /api/v1/admin/dashboard/occupancy-distribution
- **Auth:** RequireAdmin
- **Response:** `{ labels: string[], data: int[] }`
- **Purpose:** Pie/donut chart of crowd levels

### GET /api/v1/admin/dashboard/eta-accuracy
- **Auth:** RequireAdmin
- **Response:** `{ heuristic_mae: float, ml_mae: float }`
- **Purpose:** ETA accuracy comparison card

### GET /api/v1/admin/dashboard/route-usage
- **Auth:** RequireAdmin
- **Query:** `days: int = 30` (1–90)
- **Response:** `{ labels: string[], data: int[] }`
- **Purpose:** Bar chart of trips per route

### GET /api/v1/admin/dashboard/telemetry-volume
- **Auth:** RequireAdmin
- **Response:** `{ labels: string[], data: int[] }`
- **Purpose:** Hourly telemetry count (last 24h)

### GET /api/v1/admin/ml/status
- **Auth:** RequireAdmin
- **Response:** `{ model_loaded: bool, model_version: string }`
- **Purpose:** ML model status indicator

### POST /api/v1/admin/cleanup
- **Auth:** RequireAdmin
- **Response:** `{ deleted_raw: int, deleted_trips: int, ... }`
- **Purpose:** Trigger data retention cleanup

### POST /api/v1/admin/ml/train
- **Auth:** RequireAdmin
- **Response:** `{ success: bool, message: string }`
- **Purpose:** Retrain ML model from trip_history

### POST /api/v1/admin/eta/preview
- **Auth:** RequireAdmin
- **Body:** `{ lat1, lon1, lat2, lon2, num_stops=0, base_dwell_time=30, stop_id?, occupancy_level=0 }`
- **Response:** `{ eta_seconds, heuristic_eta_seconds, mode: "ml"|"heuristic" }`
- **Purpose:** ETA simulator

### GET /api/v1/admin/settings
- **Auth:** RequireAdmin
- **Response:** `{ use_ml_for_prod: bool }`

### PUT /api/v1/admin/settings
- **Auth:** RequireAdmin
- **Body:** `{ use_ml_for_prod: bool }`
- **Response:** `{ use_ml_for_prod: bool }`
- **Purpose:** Toggle ML vs heuristic ETA

---

## 2.3 Admin User Management Endpoints

### POST /api/v1/admin/users/create
- **Auth:** RequireAdmin
- **Body:** `{ username, email, password, role: "driver"|"admin" }`
- **Response:** `UserResponse`
- **Purpose:** Create driver or admin account

### GET /api/v1/admin/users/list
- **Auth:** RequireAdmin
- **Query:** `skip=0, limit=100` (max 500)
- **Response:** `UserResponse[]`

### DELETE /api/v1/admin/users/delete/{user_id}
- **Auth:** RequireAdmin
- **Response:** `{ detail: "User deleted" }`

### PUT /api/v1/admin/users/update/{user_id}
- **Auth:** RequireAdmin
- **Body:** `{ username?, email?, password?, role? }` (all optional)
- **Response:** `UserResponse`

### GET /api/v1/admin/users/me
- **Auth:** RequireAdmin
- **Response:** `UserResponse`

### GET /api/v1/admin/users/search
- **Auth:** RequireAdmin
- **Query:** `query: string, limit=50` (max 200)
- **Response:** `UserResponse[]`

### GET /api/v1/admin/users/drivers
- **Auth:** RequireAdmin
- **Response:** `UserResponse[]` (role=driver)

### GET /api/v1/admin/users/admins
- **Auth:** RequireAdmin
- **Response:** `UserResponse[]` (role=admin)

---

## 2.4 Routes & Stops Endpoints

### POST /api/v1/stops
- **Auth:** RequireAdmin
- **Body:** `{ name, lat, lon, base_dwell_time=30, is_terminal=false, peak_multiplier=1.5 }`
- **Response:** `{ id, name, lat, lon, base_dwell_time, is_terminal, peak_multiplier }`

### GET /api/v1/stops
- **Auth:** None (public)
- **Query:** `skip=0, limit=100` (max 500)
- **Response:** `StopResponse[]`

### GET /api/v1/stops/{stop_id}
- **Auth:** None
- **Response:** `StopResponse`

### POST /api/v1/routes
- **Auth:** RequireAdmin
- **Body:** `{ route_number, direction="forward", name?, origin?, destination?, stops: [{stop_id, sequence_order}] }`
- **Response:** `RouteResponse`
- **Note:** `direction` must be "forward" or "reverse"; unique on (route_number, direction)

### GET /api/v1/routes
- **Auth:** None
- **Query:** `skip=0, limit=100`
- **Response:** `RouteResponse[]`

### GET /api/v1/routes/{route_id}
- **Auth:** None
- **Response:** `RouteWithStops` (includes ordered stops array)

### GET /api/v1/routes/{route_number}/etas
- **Auth:** None
- **Response:** `{ route_number, etas: { stop_id: { stop_name, eta_seconds, distance_m, occupancy_level } } }`
- **Purpose:** Pre-computed ETAs from Redis

---

## 2.5 Vehicle Endpoints

### POST /api/v1/vehicles
- **Auth:** RequireAdmin
- **Body:** `{ plate_number, device_id, bus_type?, capacity?, is_active=true }`
- **Response:** `VehicleResponse`

### GET /api/v1/vehicles
- **Auth:** None
- **Query:** `skip=0, limit=100`
- **Response:** `VehicleResponse[]`

### GET /api/v1/vehicles/{vehicle_id}
- **Auth:** None
- **Response:** `VehicleResponse`

### PUT /api/v1/vehicles/{vehicle_id}
- **Auth:** RequireAdmin
- **Body:** `{ route_id?: int }`
- **Response:** `VehicleResponse`
- **Purpose:** Assign vehicle to route

### GET /api/v1/vehicles/positions
- **Auth:** None
- **Response:** `{ positions: { [vehicle_id]: VehiclePosition }, timestamp: float }`
- **Purpose:** All live positions snapshot

### GET /api/v1/vehicles/positions/{vehicle_id}
- **Auth:** None
- **Response:** `VehiclePosition`

### POST /api/v1/vehicles/telemetry
- **Auth:** None (device)
- **Body:** `{ device_id, lat, lon, speed?, pixel_count?, raw_payload? }`
- **Response:** Telemetry pipeline result
- **Note:** Auto-provisions unknown devices

---

## 2.6 Assignment (Ride Lifecycle) Endpoints

### GET /api/v1/assignments/active
- **Auth:** RequireAdmin
- **Response:** `AssignmentOut[]`
- **Fields:** `{ id, driver_id, vehicle_id, route_id, start_time, end_time, status, driver_username, vehicle_plate, route_number }`

### POST /api/v1/assignments/start
- **Auth:** RequireAdmin
- **Body:** `{ driver_id: int, vehicle_id: int, route_id: int }`
- **Response:** `AssignmentOut`
- **Purpose:** Start a new driver+vehicle+route assignment

### POST /api/v1/assignments/end
- **Auth:** RequireAdmin
- **Body:** `{ assignment_id: int }`
- **Response:** `{ status: "ended", assignment_id }`
- **Purpose:** End an active assignment

---

## 2.7 Crowd / CV Endpoints

### GET /api/v1/admin/crowd/{plate_number}
- **Auth:** RequireAdmin
- **Response:** `{ plate_number, cv: { occupancy_level, people_count, face_count, head_blob_count, crowd_density, confidence, method, updated_at, image_path }, image_path }`
- **Purpose:** Latest CV crowd density for a vehicle

---

## 2.8 Favorites & Ratings Endpoints

### POST /api/v1/favorites
- **Auth:** JWT
- **Body:** `{ user_id, route_id, nickname? }`
- **Response:** `{ id, user_id, route_id, nickname }`

### GET /api/v1/favorites/{user_id}
- **Auth:** JWT
- **Response:** `Favorite[]`

### DELETE /api/v1/favorites/{favorite_id}
- **Auth:** JWT
- **Response:** `{ status: "deleted", id }`

### POST /api/v1/ratings
- **Auth:** JWT
- **Body:** `{ user_id, assignment_id, score: 1-5, comment? }`
- **Response:** `{ id, score }`

### GET /api/v1/ratings/{assignment_id}
- **Auth:** JWT
- **Response:** `Rating[]`

---

## 2.9 Notification Endpoints

### POST /api/v1/notifications/settings
- **Auth:** JWT
- **Body:** `{ user_id, route_id, stop_id?, lead_time_minutes=10 }`
- **Response:** `{ id, lead_time_minutes }`

### GET /api/v1/notifications/settings/{user_id}
- **Auth:** JWT
- **Response:** `NotificationSetting[]`

### POST /api/v1/notifications/register-token
- **Auth:** JWT
- **Body:** `{ user_id, token }`
- **Response:** `{ status: "registered" }`

---

## 2.10 Pairing Endpoints

### POST /api/v1/admin/vehicles/{vehicle_id}/generate-pairing-code
- **Auth:** RequireAdmin
- **Response:** `{ code: "BUS-XXXX-XXXX", vehicle_id, plate_number, device_id, expires_in_seconds=300, message }`
- **Purpose:** Generate 5-minute pairing code for bus dashboard

### POST /api/v1/pair/verify
- **Auth:** None
- **Body:** `{ code, password }`
- **Response:** `{ status: "paired", vehicle_id, plate_number, device_id, message }`

### POST /api/v1/admin/vehicles/{vehicle_id}/unpair
- **Auth:** RequireAdmin
- **Response:** `{ status: "unpaired", vehicle_id }`

---

## 2.11 Telemetry Endpoints

### POST /api/v1/telemetry
- **Auth:** None (device)
- **Body:** `{ device_id, lat, lon, speed?, pixel_count?, raw_payload? }`
- **Response:** Pipeline result
- **Note:** Requires pre-registered device

### POST /api/v1/gateway/esp32/telemetry
- **Auth:** None (device)
- **Body (multipart):** `device_id, plate_number?, bus_type?, lat, lon, speed, bus_capacity, occupancy_level?, image: UploadFile`
- **Response:** Full pipeline result (CV + ETA + broadcast)

---

## 2.12 Search Endpoints

### POST /api/v1/search/point-to-point
- **Auth:** None
- **Body:** `{ start_stop_id, end_stop_id, max_routes=5, max_buses=10 }`
- **Response:** `{ routes: [...], start_stop, end_stop }`

### POST /api/v1/search/journey
- **Auth:** None
- **Body:** `{ start_query?, end_query?, start_lat?, start_lon?, end_lat?, end_lon?, max_routes=5, max_buses=10 }`
- **Response:** `{ start: { stop info }, end: { stop info }, routes: [...] }`

---

## 2.13 WebSocket Endpoints

### WS /api/v1/ws/live
- **Auth:** JWT via `?token=` query param
- **Role required:** admin
- **Server messages:** `vehicle_position` broadcasts
- **Client messages:** `{ type: "ping" }` → `{ type: "pong" }`
- **Heartbeat:** server sends `{ type: "heartbeat" }` after 90s inactivity
- **First message:** `{ type: "connected", detail: "fleet_stream" }`

### WS /api/v1/ws/mobile
- **Auth:** JWT via `?token=` query param
- **Client messages:** `{ type: "subscribe", route_id: N }`, `{ type: "unsubscribe" }`, `{ type: "ping" }`
- **Server messages:** `vehicle_position` (filtered by subscribed route), `cv_result`
- **Heartbeat:** 120s

---

## 2.14 Health

### GET /health
- **Auth:** None
- **Response:** `{ status: "healthy"|"degraded", version: "1.0.0", database: "connected"|"error", redis: "connected"|"error" }`
- **Status:** 200 or 503

---

# 3. Dashboard Architecture

## 3.1 Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | Next.js 14 (App Router) |
| Language | TypeScript (strict) |
| Styling | Tailwind CSS + CSS variables for theming |
| UI Components | shadcn/ui (Radix primitives) |
| Maps | Leaflet + react-leaflet |
| Charts | Recharts |
| Tables | TanStack Table v8 |
| State | React Context + Zustand (lightweight) |
| Data Fetching | TanStack Query v5 (React Query) |
| WebSocket | Native WebSocket API (custom hook) |
| Forms | React Hook Form + Zod validation |
| Icons | Lucide React |
| Notifications | Sonner (toast) |

## 3.2 Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  Top Header: Logo | Search | Notifications | User Avatar/Menu  │
├──────────┬──────────────────────────────────────────────────────┤
│          │                                                      │
│  Sidebar │              Page Content                            │
│          │                                                      │
│  - Dash  │  ┌──────────────────────────────────────────────┐   │
│  - Map   │  │                                              │   │
│  - Fleet │  │  Page-specific content                       │   │
│  - Routes│  │                                              │   │
│  - Users │  │  Cards / Tables / Forms / Maps / Charts      │   │
│  - Trips │  │                                              │   │
│  - Crowd │  └──────────────────────────────────────────────┘   │
│  - ML    │                                                      │
│  - Settings│                                                    │
│          │                                                      │
└──────────┴──────────────────────────────────────────────────────┘
```

- **Sidebar:** Collapsible icon-only mode on mobile; full labels on desktop
- **Header:** Sticky, contains global search, notification bell, user dropdown
- **Content:** Max-width container, responsive padding

## 3.3 Navigation Structure

```
ADMIN
├── Dashboard (overview + KPI cards + charts)
├── Live Map (full-screen fleet map)
├── Fleet
│   ├── Vehicles (CRUD table)
│   └── Vehicle Detail (single vehicle view)
├── Routes & Stops
│   ├── Routes (CRUD table)
│   ├── Route Detail (stops sequence)
│   └── Stops (CRUD table)
├── Operations
│   ├── Active Trips (assignments)
│   └── Trip History
├── Users
│   ├── All Users
│   ├── Drivers
│   └── Admins
├── Intelligence
│   ├── Analytics (charts)
│   ├── Crowd Density
│   └── ML Model
└── Settings
    ├── General
    ├── Account
    └── API Docs
```

---

# 4. Page-by-Page Specification

## 4.1 Login Page — `/login`

### Purpose
Authenticate admin user against `POST /api/v1/auth/login`.

### Layout
Centered card on full-screen background.

### Elements
- Logo + "BusTrack Admin" title
- Username input (text, required)
- Password input (password, required)
- "Sign In" button (full width, loading spinner while pending)
- Error toast on invalid credentials

### Behavior
1. On submit → `POST /api/v1/auth/login` with `{ username, password }`
2. On success → store `access_token` in `auth_token` cookie (httpOnly would be ideal but we use js-cookie for API access) + store user object in auth context
3. Redirect to `/dashboard`
4. On failure → show error toast: "Invalid username or password"

### Auth Guard
If user already has valid JWT (check `/api/v1/auth/me`), redirect to `/dashboard`.

---

## 4.2 Dashboard (Overview) — `/dashboard`

### Purpose
At-a-glance system health + key metrics.

### Data Sources
| Card | Endpoint | Fields Used |
|------|----------|-------------|
| Active Trips | `GET /api/v1/admin/dashboard/summary` | `active_assignments` |
| Total Vehicles | same | `vehicles` |
| Active Routes | same | `routes` |
| Registered Users | same | `users` |
| Telemetry (24h) | same | `telemetry_last_24h` |
| ML Model Status | `GET /api/v1/admin/ml/status` | `model_loaded`, `model_version` |
| ETA Accuracy | `GET /api/v1/admin/dashboard/eta-accuracy` | `heuristic_mae`, `ml_mae` |

### Layout
- Row 1: 4 KPI stat cards (Active Trips, Vehicles, Routes, Users)
- Row 2: 2 cards (ML Status, ETA Accuracy)
- Row 3: 2 charts side-by-side
  - Left: Assignments over time (line chart, `GET .../assignments-over-time?days=7`)
  - Right: Route usage (bar chart, `GET .../route-usage?days=30`)
- Row 4: 2 charts side-by-side
  - Left: Occupancy distribution (donut chart, `GET .../occupancy-distribution`)
  - Right: Telemetry volume (area chart, `GET .../telemetry-volume`)
- Row 5: Live fleet map (embedded, 400px height, shows all active vehicles)

### Real-Time
The embedded map connects to `WS /api/v1/ws/live` and updates vehicle positions in real-time.

---

## 4.3 Live Map — `/map`

### Purpose
Full-screen real-time fleet monitoring.

### Map
- Leaflet with dark CartoDB tiles
- Each active vehicle = animated marker with plate number tooltip
- Click marker → popup with: plate, speed, route, occupancy, last update
- Auto-refreshes via WebSocket (no polling needed)

### Filters (top bar)
| Filter | Type | Source |
|--------|------|--------|
| Route | Dropdown | `GET /api/v1/routes` |
| Vehicle | Search input | free text |
| Status | Toggle | Active / All |
| Density | Dropdown | Low / Medium / High |

### Sidebar (collapsible)
- List of all active vehicles
- Click → pan map to that vehicle
- Shows: plate, route, speed, occupancy bar, ETA to next stop

### WebSocket
Connects to `WS /api/v1/ws/live`. Receives `vehicle_position` messages → updates markers.

---

## 4.4 Vehicles List — `/vehicles`

### Purpose
Full CRUD for vehicle management.

### Table Columns
| Column | Source Field | Type |
|--------|-------------|------|
| Plate Number | `plate_number` | string |
| Device ID | `device_id` | string |
| Type | `bus_type` | string |
| Capacity | `capacity` | int |
| Route | `route_number` (from relation) | string |
| Status | `is_active` | badge (Active/Inactive) |
| Last Position | `last_lat`, `last_lon` | "Lat, Lon" or "—" |
| Last Update | `position_updated_at` | relative time |
| Actions | — | Edit, View, More |

### Data Source
`GET /api/v1/vehicles?skip=0&limit=100` (paginated)

### Filters
- Search by plate number or device ID
- Filter by status (All / Active / Inactive)
- Filter by route

### Actions
| Action | Endpoint | Method |
|--------|----------|--------|
| View | navigates to `/vehicles/{id}` | — |
| Edit | modal with form | `PUT /api/v1/vehicles/{id}` |
| Assign Route | modal with route dropdown | `PUT /api/v1/vehicles/{id}` body: `{ route_id }` |
| Pairing | modal → generate code | `POST /api/v1/admin/vehicles/{id}/generate-pairing-code` |
| Unpair | confirm dialog | `POST /api/v1/admin/vehicles/{id}/unpair` |
| Register New | modal with form | `POST /api/v1/vehicles` |

### Register New Vehicle Form
| Field | Type | Required | Validation |
|-------|------|----------|------------|
| Plate Number | text | Yes | unique |
| Device ID | text | Yes | unique |
| Bus Type | text | No | — |
| Capacity | number | No | min 1 |
| Active | toggle | No | default true |

---

## 4.5 Vehicle Detail — `/vehicles/{vehicle_id}`

### Purpose
Drill-down view for a single vehicle.

### Sections
1. **Header:** Plate number + status badge + action buttons (Edit, Assign Route, Pairing)
2. **Info Card:** All vehicle fields (plate, device_id, type, capacity, route, last position, last update)
3. **Live Position Map:** Leaflet map centered on vehicle's last position
4. **Crowd Density:** Latest CV data from `GET /api/v1/admin/crowd/{plate_number}` — people count, density level, confidence, method
5. **Active Assignment:** If vehicle has active assignment, show driver + route + start time
6. **Telemetry History:** Recent positions (from `GET /api/v1/vehicles/positions/{vehicle_id}`)

---

## 4.6 Routes List — `/routes`

### Purpose
Full CRUD for route management.

### Table Columns
| Column | Source Field |
|--------|-------------|
| Route Number | `route_number` |
| Direction | `direction` |
| Name | `name` |
| Origin | `origin` |
| Destination | `destination` |
| Stops | count of stops |
| Status | `active` (badge) |
| Actions | Edit, View Stops |

### Data Source
`GET /api/v1/routes`

### Create/Edit Route Form
| Field | Type | Required |
|-------|------|----------|
| Route Number | text | Yes |
| Direction | select (forward/reverse) | Yes |
| Name | text | No |
| Origin | text | No |
| Destination | text | No |
| Stops | multi-select with order | No |

### Stop Sequence Editor
Drag-and-drop list of stops with `sequence_order`. Each stop: name + sequence number.

---

## 4.7 Route Detail — `/routes/{route_id}`

### Purpose
View a single route with its full stop sequence.

### Sections
1. **Header:** Route number + direction badge + origin → destination
2. **Stops Timeline:** Vertical timeline showing stops in order
   - Each stop: name, lat/lon, dwell time, terminal flag
   - Visual: connected dots with stop names
3. **Route Map:** Leaflet map with:
   - Stop markers (numbered by sequence)
   - Polyline connecting stops in order
4. **Live Buses on This Route:** List of active assignments for this route
5. **ETAs:** From `GET /api/v1/routes/{route_number}/etas` — per-stop ETA countdown

---

## 4.8 Stops List — `/stops`

### Purpose
Full CRUD for bus stop management.

### Table Columns
| Column | Source Field |
|--------|-------------|
| Name | `name` |
| Coordinates | `lat`, `lon` |
| Dwell Time | `base_dwell_time` |
| Terminal | `is_terminal` (badge) |
| Peak Multiplier | `peak_multiplier` |
| Actions | Edit, View on Map |

### Data Source
`GET /api/v1/stops`

### Create/Edit Stop Form
| Field | Type | Required |
|-------|------|----------|
| Name | text | Yes |
| Latitude | number | Yes |
| Longitude | number | Yes |
| Dwell Time (sec) | number | No (default 30) |
| Is Terminal | toggle | No |
| Peak Multiplier | number | No (default 1.5) |

---

## 4.9 Active Trips (Assignments) — `/assignments`

### Purpose
View and manage active driver+vehicle+route assignments.

### Table Columns
| Column | Source Field |
|--------|-------------|
| Assignment ID | `id` |
| Driver | `driver_username` |
| Vehicle | `vehicle_plate` |
| Route | `route_number` |
| Start Time | `start_time` |
| Duration | computed (now - start_time) |
| Status | `status` (badge) |
| Actions | End Trip, View Details |

### Data Source
`GET /api/v1/assignments/active`

### Start New Trip Form (NEW — this is the missing feature)
| Field | Type | Source |
|-------|------|--------|
| Driver | dropdown (searchable) | `GET /api/v1/admin/users/drivers` |
| Vehicle | dropdown (searchable) | `GET /api/v1/vehicles` (active only) |
| Route | dropdown (searchable) | `GET /api/v1/routes` |

On submit → `POST /api/v1/assignments/start` body: `{ driver_id, vehicle_id, route_id }`

### End Trip Action
Confirm dialog → `POST /api/v1/assignments/end` body: `{ assignment_id }`

### Auto-Refresh
Poll every 10 seconds OR use WebSocket to detect new assignments.

---

## 4.10 Users List — `/users`

### Purpose
Full user management.

### Sub-Tabs
| Tab | Endpoint | Filter |
|-----|----------|--------|
| All Users | `GET /api/v1/admin/users/list` | — |
| Drivers | `GET /api/v1/admin/users/drivers` | role=driver |
| Admins | `GET /api/v1/admin/users/admins` | role=admin |

### Table Columns
| Column | Source Field |
|--------|-------------|
| Username | `username` |
| Email | `email` |
| Role | `role` (badge: driver/admin/passenger) |
| Verified | `is_verified` (badge) |
| Created | `created_at` |
| Actions | Edit, Delete, Reset Password |

### Create/Edit User Form
| Field | Type | Required |
|-------|------|----------|
| Username | text | Yes (3-100 chars) |
| Email | email | Yes |
| Password | password | Yes on create, optional on edit |
| Role | select (driver/admin) | Yes |

### Actions
| Action | Endpoint |
|--------|----------|
| Create | `POST /api/v1/admin/users/create` |
| Update | `PUT /api/v1/admin/users/update/{id}` |
| Delete | `DELETE /api/v1/admin/users/delete/{id}` |
| Search | `GET /api/v1/admin/users/search?q={query}` |

---

## 4.11 Analytics — `/analytics`

### Purpose
Extended data visualization beyond the dashboard overview.

### Charts
| Chart | Endpoint | Type | Period |
|-------|----------|------|--------|
| Assignments Over Time | `GET .../assignments-over-time` | Line | 7/14/30 days |
| Occupancy Distribution | `GET .../occupancy-distribution` | Donut | all time |
| Route Usage | `GET .../route-usage` | Bar | 7/14/30 days |
| Telemetry Volume | `GET .../telemetry-volume` | Area | 24h |
| ETA Accuracy | `GET .../eta-accuracy` | Comparison bar | all time |

### Period Selector
Each chart has a 7 / 14 / 30 day toggle.

### Operational Insights (computed from summary)
- Most used route
- Most active vehicle
- Peak hour
- Average trip duration

---

## 4.12 Crowd Density — `/crowd`

### Purpose
View computer vision crowd analysis per vehicle.

### Layout
1. **Vehicle Selector:** Dropdown of all vehicles (`GET /api/v1/vehicles`)
2. **CV Data Card:** For selected vehicle via `GET /api/v1/admin/crowd/{plate_number}`
   - People Count
   - Face Count
   - Head/Blob Count
   - Crowd Density Level (0/1/2 with color: green/yellow/red)
   - Confidence %
   - Method (YOLOv8)
   - Last Updated
3. **Image Preview:** If `image_path` exists, show the ESP32-CAM capture
4. **History:** Recent CV readings (if available from trip_history)

---

## 4.13 ML Model — `/settings/ml`

### Purpose
ML model management and ETA configuration.

### Sections
1. **Model Status Card**
   - Loaded: Yes/No (from `GET /api/v1/admin/ml/status`)
   - Version string
   - Last trained: (from trip_history timestamps)

2. **Train Model Button**
   - `POST /api/v1/admin/ml/train`
   - Shows loading state, success/error toast
   - Warning: "This may take several minutes"

3. **ETA Mode Toggle**
   - Current mode: `GET /api/v1/admin/settings`
   - Toggle: `PUT /api/v1/admin/settings` body: `{ use_ml_for_prod: boolean }`
   - Visual: switch component with "Heuristic" / "ML-Enhanced" labels

4. **ETA Preview Simulator**
   - Form: lat1, lon1, lat2, lon2, num_stops, dwell_time, occupancy_level
   - Submit → `POST /api/v1/admin/eta/preview`
   - Shows: heuristic ETA, ML-adjusted ETA, mode used

5. **Data Cleanup**
   - Button → `POST /api/v1/admin/cleanup`
   - Confirms: "Delete old telemetry and trip history?"
   - Shows result counts

---

## 4.14 Settings — `/settings`

### Purpose
Admin account and system settings.

### Sections
1. **Account Settings**
   - Update profile: `PATCH /api/v1/auth/me`
   - Change password: `POST /api/v1/auth/change-password`

2. **System Info**
   - API version: 1.0.0
   - Backend status: `GET /health`
   - Database status: from health
   - Redis status: from health

3. **API Documentation Link**
   - Link to `/docs` (FastAPI Swagger UI)

---

# 5. API Integration Map

## 5.1 By Page → Endpoints

| Page | Endpoints Used |
|------|---------------|
| Login | `POST /auth/login`, `GET /auth/me` |
| Dashboard | `GET /admin/dashboard/summary`, `GET /admin/dashboard/assignments-over-time`, `GET /admin/dashboard/occupancy-distribution`, `GET /admin/dashboard/eta-accuracy`, `GET /admin/dashboard/route-usage`, `GET /admin/dashboard/telemetry-volume`, `GET /admin/ml/status` |
| Live Map | `WS /ws/live`, `GET /vehicles/positions`, `GET /routes` |
| Vehicles List | `GET /vehicles`, `POST /vehicles`, `PUT /vehicles/{id}`, `POST /admin/vehicles/{id}/generate-pairing-code`, `POST /admin/vehicles/{id}/unpair` |
| Vehicle Detail | `GET /vehicles/{id}`, `GET /vehicles/positions/{id}`, `GET /admin/crowd/{plate}`, `GET /assignments/active` |
| Routes List | `GET /routes`, `POST /routes` |
| Route Detail | `GET /routes/{id}`, `GET /routes/{route_number}/etas` |
| Stops List | `GET /stops`, `POST /stops` |
| Active Trips | `GET /assignments/active`, `POST /assignments/start`, `POST /assignments/end` |
| Users | `GET /admin/users/list`, `POST /admin/users/create`, `PUT /admin/users/update/{id}`, `DELETE /admin/users/delete/{id}`, `GET /admin/users/drivers`, `GET /admin/users/admins` |
| Analytics | Same as Dashboard but with period controls |
| Crowd | `GET /admin/crowd/{plate}`, `GET /vehicles` |
| ML Settings | `GET /admin/ml/status`, `POST /admin/ml/train`, `GET /admin/settings`, `PUT /admin/settings`, `POST /admin/eta/preview`, `POST /admin/cleanup` |
| Settings | `PATCH /auth/me`, `POST /auth/change-password`, `GET /health` |

## 5.2 By Entity → Endpoints

| Entity | List | Create | Read | Update | Delete |
|--------|------|--------|------|--------|--------|
| Vehicle | `GET /vehicles` | `POST /vehicles` | `GET /vehicles/{id}` | `PUT /vehicles/{id}` | — |
| Route | `GET /routes` | `POST /routes` | `GET /routes/{id}` | — | — |
| Stop | `GET /stops` | `POST /stops` | `GET /stops/{id}` | — | — |
| Assignment | `GET /assignments/active` | `POST /assignments/start` | — | `POST /assignments/end` | — |
| User | `GET /admin/users/list` | `POST /admin/users/create` | `GET /admin/users/{id}` | `PUT /admin/users/update/{id}` | `DELETE /admin/users/delete/{id}` |
| Driver | `GET /admin/users/drivers` | `POST /admin/users/create` (role=driver) | — | — | — |

---

# 6. WebSocket Real-Time Layer

## 6.1 Connection Strategy

```
┌─────────────────────────────────────────────────────────────┐
│                     Admin Dashboard                          │
│                                                             │
│  ┌─────────────────┐    ┌──────────────────────────────┐   │
│  │  useWebSocket   │    │  useLiveVehiclePositions     │   │
│  │  (raw WS)       │    │  (derived state hook)        │   │
│  └────────┬────────┘    └──────────────┬───────────────┘   │
│           │                            │                    │
│           ▼                            ▼                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Vehicle Position Store                  │   │
│  │  Map<vehicle_id, VehiclePosition>                    │   │
│  │  Updated on every WS message                         │   │
│  └─────────────────────────────────────────────────────┘   │
│           │                                                │
│           ▼                                                │
│  ┌─────────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  Live Map       │  │  Vehicle     │  │  Dashboard   │  │
│  │  (markers)      │  │  List        │  │  KPI Cards   │  │
│  └─────────────────┘  └──────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## 6.2 WebSocket Hook

```typescript
// hooks/useAdminWebSocket.ts
// Connects to ws://localhost:8000/api/v1/ws/live?token={jwt}
// Handles: connect, message, disconnect, reconnect, heartbeat
// Returns: connection status, last message, vehicle positions map
```

### Message Types
| Type | Fields | Purpose |
|------|--------|---------|
| `connected` | `{ detail: "fleet_stream" }` | Initial handshake |
| `vehicle_position` | `{ type, vehicle_id, plate_number, lat, lon, speed, route_id, timestamp, occupancy_level, eta_payloads }` | Position update |
| `cv_result` | `{ type, vehicle_id, plate_number, cv: { people_count, crowd_density, ... } }` | CV analysis |
| `heartbeat` | `{ type: "heartbeat" }` | Keep-alive |
| `pong` | `{ type: "pong" }` | Response to client ping |

## 6.3 Pages Using WebSocket

| Page | Usage |
|------|-------|
| Dashboard | Embedded map + live counters |
| Live Map | Full-screen map with markers |
| Vehicle Detail | Position update + CV data |
| Active Trips | Real-time status changes |

---

# 7. Component Library

## 7.1 Core Components (shadcn/ui)

| Component | Usage |
|-----------|-------|
| `Button` | All actions |
| `Input` | Text fields |
| `Select` | Dropdowns |
| `Table` | Data tables |
| `Dialog/Modal` | Create/edit forms |
| `Toast` | Success/error notifications |
| `Badge` | Status indicators |
| `Card` | Content containers |
| `Tabs` | Sub-page navigation |
| `Switch` | Toggle (ML mode) |
| `Skeleton` | Loading states |
| `DropdownMenu` | Action menus |
| `Pagination` | Table pagination |
| `Tooltip` | Info tooltips |
| `AlertDialog` | Confirm destructive actions |

## 7.2 Custom Components

| Component | Purpose |
|-----------|---------|
| `StatCard` | KPI dashboard card with icon + value + trend |
| `LiveMap` | Leaflet map with vehicle markers |
| `VehicleMarker` | Animated bus icon on map |
| `StopMarker` | Numbered circle on map |
| `RoutePolyline` | Dashed line connecting stops |
| `CrowdDensityBar` | Color-coded bar (green/yellow/red) |
| `ETACountdown` | Live countdown timer |
| `OccupancyBadge` | Level 0/1/2 with color |
| `ConnectionStatus` | WebSocket connected/disconnected indicator |
| `VehicleSelector` | Dropdown with search |
| `RouteSelector` | Dropdown with search |
| `DriverSelector` | Dropdown with search |
| `AssignmentForm` | Start trip form (driver + vehicle + route) |
| `PairingCodeDisplay` | Shows generated code with countdown |
| `ChartCard` | Recharts wrapper with period selector |
| `PageHeader` | Title + description + action buttons |
| `EmptyState` | "No data" placeholder |
| `ErrorState` | Error with retry button |
| `SearchInput` | Debounced search |

---

# 8. Auth & Security

## 8.1 Auth Flow

```
User → POST /auth/login → { access_token }
     → Store in cookie "auth_token"
     → Store user object in AuthContext
     → Redirect to /dashboard

Every API call → Include header: Authorization: Bearer {token}
                (or cookie: auth_token={token})

On 401 → Redirect to /login
On 403 → Show "Access Denied" toast
```

## 8.2 Middleware (Next.js `middleware.ts`)

```typescript
// middleware.ts
// Public routes: /login
// Protected routes: everything else
// Admin routes: /dashboard, /map, /vehicles, /routes, /users, /assignments, /analytics, /crowd, /settings
//   → require role "admin" (from user object decoded from JWT)
```

## 8.3 Role Guard

```typescript
// lib/auth.ts
// decode JWT → extract role
// if role !== "admin" for admin routes → redirect to /login
```

---

# 9. Data Models & Types

## 9.1 TypeScript Interfaces (derived from backend schemas)

```typescript
// User
interface User {
  id: number;
  username: string;
  email: string;
  role: "passenger" | "driver" | "admin";
  is_verified: boolean;
  google_id?: string;
  created_at: string;
}

// Vehicle
interface Vehicle {
  id: number;
  plate_number: string;
  device_id: string;
  bus_type?: string;
  capacity?: number;
  is_active: boolean;
  route_id?: number;
  route_number?: string;
  last_lat?: number;
  last_lon?: number;
  speed?: number;
  position_updated_at?: string;
}

// VehiclePosition
interface VehiclePosition {
  vehicle_id: number;
  plate_number: string;
  lat: number;
  lon: number;
  speed: number;
  timestamp: number;
  route_id?: number;
  assignment_id?: number;
  occupancy_level: number;
  last_updated?: string;
}

// Route
interface Route {
  id: number;
  route_number: string;
  direction: "forward" | "reverse";
  name?: string;
  origin?: string;
  destination?: string;
  active: boolean;
}

// RouteWithStops
interface RouteWithStops extends Route {
  stops: Stop[];
}

// Stop
interface Stop {
  id: number;
  name: string;
  lat: number;
  lon: number;
  base_dwell_time: number;
  is_terminal: boolean;
  peak_multiplier: number;
}

// Assignment
interface Assignment {
  id: number;
  driver_id: number;
  vehicle_id: number;
  route_id: number;
  start_time: string;
  end_time?: string;
  status: "active" | "completed";
  driver_username?: string;
  vehicle_plate?: string;
  route_number?: string;
}

// CrowdData
interface CrowdData {
  plate_number: string;
  cv: {
    occupancy_level: number;
    people_count: number;
    face_count: number;
    head_blob_count: number;
    crowd_density: number;
    confidence: number;
    method: string;
    updated_at: number;
    image_path: string;
  };
  image_path?: string;
}

// DashboardSummary
interface DashboardSummary {
  active_assignments: number;
  vehicles: number;
  routes: number;
  users: number;
  telemetry_last_24h: number;
}

// ChartData
interface ChartData {
  labels: string[];
  data: number[];
}

// MLStatus
interface MLStatus {
  model_loaded: boolean;
  model_version: string;
}

// ETAAccuracy
interface ETAAccuracy {
  heuristic_mae: number;
  ml_mae: number;
}

// SystemSettings
interface SystemSettings {
  use_ml_for_prod: boolean;
}

// Health
interface HealthResponse {
  status: "healthy" | "degraded";
  version: string;
  database: string;
  redis: string;
}

// WebSocket Messages
type WSMessage =
  | { type: "connected"; detail: string }
  | { type: "vehicle_position"; vehicle_id: number; plate_number: string; lat: number; lon: number; speed: number; route_id?: number; timestamp: number; occupancy_level: number; eta_payloads?: Record<number, ETAStopPayload> }
  | { type: "cv_result"; vehicle_id: number; plate_number: string; timestamp: number; cv: CVResult }
  | { type: "heartbeat" }
  | { type: "pong" };

interface ETAStopPayload {
  stop_name: string;
  eta_seconds: number;
  distance_m: number;
  computed_at: number;
}

interface CVResult {
  people_count: number;
  face_count: number;
  head_blob_count: number;
  crowd_density: number;
  is_crowded: boolean;
  method: string;
  confidence: number;
  foreground_ratio: number;
  inference_ms: number;
}
```

---

# 10. Implementation Phases

## Phase 1: Foundation (Week 1)

| Task | Details |
|------|---------|
| Initialize Next.js 14 project | `npx create-next-app@latest` with TypeScript + Tailwind + App Router |
| Install dependencies | shadcn/ui, Leaflet, Recharts, TanStack Query, React Hook Form, Zod, Zustand, Sonner, Lucide |
| Configure Tailwind | Custom theme with CSS variables for colors |
| Set up `middleware.ts` | Auth guard: public `/login`, protected everything else |
| Create `AuthContext` | Store user + token, provide login/logout functions |
| Create `api.ts` | Axios instance with base URL `http://localhost:8000/api/v1`, auto-attach Bearer token from cookie |
| Create `layout.tsx` | Root layout with AuthProvider + QueryProvider + Toaster |
| Build Login Page | Form → `POST /auth/login` → store token → redirect |
| Build Shell Layout | Sidebar + Header + Content area |

## Phase 2: Dashboard + Live Map (Week 2)

| Task | Details |
|------|---------|
| Build Dashboard page | 6 KPI cards + 4 charts + embedded map |
| Create `useAdminWebSocket` hook | Connect to `/ws/live`, handle messages, reconnect |
| Create `useLiveVehiclePositions` hook | Derive vehicle position map from WS messages |
| Build `LiveMap` component | Leaflet + dark tiles + vehicle markers + popups |
| Build `StatCard` component | Icon + value + label + optional trend |
| Build `ChartCard` component | Recharts wrapper with period selector |
| Wire Dashboard to endpoints | 7 endpoints for summary + charts |

## Phase 3: Fleet Management (Week 3)

| Task | Details |
|------|---------|
| Build Vehicles List page | Table with search, filter, pagination |
| Build Vehicle Create form | Modal with all fields |
| Build Vehicle Edit form | Pre-filled modal |
| Build Vehicle Detail page | Info card + mini map + crowd data + assignment |
| Build Pairing flow | Generate code → display with countdown → unpair |
| Build Stops List page | Table + create/edit forms |
| Build Stops Create form | Name + lat/lon + dwell + terminal + multiplier |

## Phase 4: Routes & Operations (Week 4)

| Task | Details |
|------|---------|
| Build Routes List page | Table + create form |
| Build Route Detail page | Stops timeline + map polyline + live buses + ETAs |
| Build Stop Sequence Editor | Drag-and-drop ordering |
| Build Active Trips page | Table + **Start Trip form** (driver + vehicle + route) + End Trip button |
| Build Start Trip form | 3 dropdowns → `POST /assignments/start` |
| Build End Trip flow | Confirm dialog → `POST /assignments/end` |

## Phase 5: Users & Intelligence (Week 5)

| Task | Details |
|------|---------|
| Build Users List page | 3 sub-tabs (All, Drivers, Admins) + search |
| Build User Create/Edit forms | Role dropdown, password handling |
| Build User Delete flow | Confirm dialog |
| Build Analytics page | 5 chart cards with period controls |
| Build Crowd Density page | Vehicle selector + CV data display + image preview |
| Build ML Settings page | Status + train button + ETA toggle + preview simulator + cleanup |

## Phase 6: Settings + Polish (Week 6)

| Task | Details |
|------|---------|
| Build Settings page | Account info + change password + system info |
| Add loading skeletons | Every data-fetching page |
| Add error states | Error boundary + retry button |
| Add empty states | "No vehicles found" etc. |
| Mobile responsive | Collapsible sidebar, responsive tables |
| Final testing | All CRUD flows, WS connection, auth guard |

---

# 11. File Structure

```
src/
├── app/
│   ├── layout.tsx                    # Root layout (providers)
│   ├── page.tsx                      # Redirect to /dashboard
│   ├── login/
│   │   └── page.tsx                  # Login page
│   ├── dashboard/
│   │   └── page.tsx                  # Overview + KPI + charts
│   ├── map/
│   │   └── page.tsx                  # Full-screen live map
│   ├── vehicles/
│   │   ├── page.tsx                  # Vehicles list
│   │   └── [vehicleId]/
│   │       └── page.tsx              # Vehicle detail
│   ├── routes/
│   │   ├── page.tsx                  # Routes list
│   │   └── [routeId]/
│   │       └── page.tsx              # Route detail
│   ├── stops/
│   │   └── page.tsx                  # Stops list
│   ├── assignments/
│   │   └── page.tsx                  # Active trips + start form
│   ├── users/
│   │   └── page.tsx                  # Users management
│   ├── analytics/
│   │   └── page.tsx                  # Charts
│   ├── crowd/
│   │   └── page.tsx                  # Crowd density
│   └── settings/
│       ├── page.tsx                  # Account settings
│       └── ml/
│           └── page.tsx              # ML model management
├── components/
│   ├── layout/
│   │   ├── sidebar.tsx               # App sidebar
│   │   ├── header.tsx                # Top header
│   │   └── app-shell.tsx             # Sidebar + header + content
│   ├── ui/                           # shadcn/ui components
│   │   ├── button.tsx
│   │   ├── input.tsx
│   │   ├── table.tsx
│   │   ├── dialog.tsx
│   │   ├── badge.tsx
│   │   ├── card.tsx
│   │   ├── tabs.tsx
│   │   ├── switch.tsx
│   │   ├── skeleton.tsx
│   │   ├── toast.tsx
│   │   ├── dropdown-menu.tsx
│   │   ├── alert-dialog.tsx
│   │   └── ...
│   ├── dashboard/
│   │   ├── stat-card.tsx             # KPI card
│   │   ├── chart-card.tsx            # Recharts wrapper
│   │   └── mini-map.tsx              # Embedded map
│   ├── map/
│   │   ├── live-map.tsx              # Full Leaflet map
│   │   ├── vehicle-marker.tsx        # Bus icon marker
│   │   ├── stop-marker.tsx           # Numbered stop marker
│   │   └── route-polyline.tsx        # Route path line
│   ├── vehicles/
│   │   ├── vehicle-table.tsx         # Data table
│   │   ├── vehicle-form.tsx          # Create/edit form
│   │   ├── vehicle-info-card.tsx     # Detail info
│   │   └── pairing-flow.tsx          # Generate code + unpair
│   ├── routes/
│   │   ├── route-table.tsx           # Data table
│   │   ├── route-form.tsx            # Create/edit form
│   │   ├── stops-timeline.tsx        # Stop sequence visual
│   │   └── route-map.tsx             # Map with stops + polyline
│   ├── assignments/
│   │   ├── assignment-table.tsx       # Active trips table
│   │   └── start-trip-form.tsx       # Driver + vehicle + route
│   ├── users/
│   │   ├── user-table.tsx            # Data table
│   │   └── user-form.tsx             # Create/edit form
│   ├── crowd/
│   │   ├── crowd-data-card.tsx       # CV results display
│   │   └── vehicle-selector.tsx      # Dropdown
│   └── shared/
│       ├── page-header.tsx           # Title + description + actions
│       ├── empty-state.tsx           # "No data" placeholder
│       ├── error-state.tsx           # Error with retry
│       ├── search-input.tsx          # Debounced search
│       ├── connection-status.tsx     # WS indicator
│       └── occupancy-badge.tsx       # Level badge
├── hooks/
│   ├── use-auth.tsx                  # Auth context
│   ├── use-admin-websocket.ts        # WS connection
│   ├── use-live-vehicle-positions.ts # Derived positions
│   └── use-debounce.ts               # Debounce utility
├── lib/
│   ├── api.ts                        # Axios instance + all API functions
│   ├── auth.ts                       # JWT decode, role check
│   ├── ws-url.ts                     # WS URL builder
│   └── utils.ts                      # cn() for classnames
├── types/
│   └── index.ts                      # All TypeScript interfaces
├── providers/
│   ├── auth-provider.tsx             # AuthContext
│   ├── query-provider.tsx             # QueryClient
│   └── theme-provider.tsx            # NextThemes
├── middleware.ts                     # Auth guard
├── .env.local                        # NEXT_PUBLIC_API_URL=http://localhost:8000
├── tailwind.config.ts
├── tsconfig.json
└── package.json
```

---

# 12. Appendix — Full Endpoint Catalog

## A.1 Auth (14 endpoints)

| # | Method | Path | Auth | Purpose |
|---|--------|------|------|---------|
| 1 | POST | `/auth/register` | None | Create passenger account |
| 2 | POST | `/auth/login` | None | Login → JWT |
| 3 | POST | `/auth/google` | None | Google OAuth |
| 4 | GET | `/auth/me` | JWT | Current user |
| 5 | PATCH | `/auth/me` | JWT | Update profile |
| 6 | POST | `/auth/change-password` | JWT | Change password |
| 7 | POST | `/auth/refresh` | JWT | Refresh token |
| 8 | POST | `/auth/driver-login` | None | Driver + device login |
| 9 | POST | `/auth/driver-logout` | JWT | End driver session |
| 10 | POST | `/auth/bus-dashboard/login` | None | Device auth |
| 11 | POST | `/auth/verify-email` | None | Email verification |
| 12 | POST | `/auth/resend-verification` | None | Resend verify email |
| 13 | POST | `/auth/forgot-password` | None | Password reset email |
| 14 | POST | `/auth/reset-password` | None | Reset password |

## A.2 Admin Dashboard (11 endpoints)

| # | Method | Path | Auth | Purpose |
|---|--------|------|------|---------|
| 1 | GET | `/admin/dashboard/summary` | Admin | KPI counts |
| 2 | GET | `/admin/dashboard/assignments-over-time` | Admin | Daily assignments chart |
| 3 | GET | `/admin/dashboard/occupancy-distribution` | Admin | Occupancy pie chart |
| 4 | GET | `/admin/dashboard/eta-accuracy` | Admin | MAE comparison |
| 5 | GET | `/admin/dashboard/route-usage` | Admin | Trips per route |
| 6 | GET | `/admin/dashboard/telemetry-volume` | Admin | Hourly telemetry |
| 7 | GET | `/admin/ml/status` | Admin | ML model status |
| 8 | POST | `/admin/cleanup` | Admin | Data retention |
| 9 | POST | `/admin/ml/train` | Admin | Retrain ML |
| 10 | POST | `/admin/eta/preview` | Admin | ETA simulator |
| 11 | GET/PUT | `/admin/settings` | Admin | Read/write ML toggle |

## A.3 Admin Users (8 endpoints)

| # | Method | Path | Auth | Purpose |
|---|--------|------|------|---------|
| 1 | POST | `/admin/users/create` | Admin | Create driver/admin |
| 2 | GET | `/admin/users/list` | Admin | List all users |
| 3 | DELETE | `/admin/users/delete/{id}` | Admin | Delete user |
| 4 | PUT | `/admin/users/update/{id}` | Admin | Update user |
| 5 | GET | `/admin/users/me` | Admin | Current admin |
| 6 | GET | `/admin/users/search` | Admin | Search users |
| 7 | GET | `/admin/users/drivers` | Admin | List drivers |
| 8 | GET | `/admin/users/admins` | Admin | List admins |

## A.4 Routes & Stops (7 endpoints)

| # | Method | Path | Auth | Purpose |
|---|--------|------|------|---------|
| 1 | POST | `/stops` | Admin | Create stop |
| 2 | GET | `/stops` | None | List stops |
| 3 | GET | `/stops/{id}` | None | Get stop |
| 4 | POST | `/routes` | Admin | Create route |
| 5 | GET | `/routes` | None | List routes |
| 6 | GET | `/routes/{id}` | None | Get route + stops |
| 7 | GET | `/routes/{number}/etas` | None | Route ETAs |

## A.5 Vehicles (7 endpoints)

| # | Method | Path | Auth | Purpose |
|---|--------|------|------|---------|
| 1 | POST | `/vehicles` | Admin | Register vehicle |
| 2 | GET | `/vehicles` | None | List vehicles |
| 3 | GET | `/vehicles/{id}` | None | Get vehicle |
| 4 | PUT | `/vehicles/{id}` | Admin | Assign route |
| 5 | GET | `/vehicles/positions` | None | All live positions |
| 6 | GET | `/vehicles/positions/{id}` | None | Single position |
| 7 | POST | `/vehicles/telemetry` | None | Device telemetry |

## A.6 Assignments (3 endpoints)

| # | Method | Path | Auth | Purpose |
|---|--------|------|------|---------|
| 1 | GET | `/assignments/active` | Admin | List active |
| 2 | POST | `/assignments/start` | Admin | Start trip |
| 3 | POST | `/assignments/end` | Admin | End trip |

## A.7 Crowd (1 endpoint)

| # | Method | Path | Auth | Purpose |
|---|--------|------|------|---------|
| 1 | GET | `/admin/crowd/{plate}` | Admin | CV crowd data |

## A.8 Favorites & Ratings (5 endpoints)

| # | Method | Path | Auth | Purpose |
|---|--------|------|------|---------|
| 1 | POST | `/favorites` | JWT | Add favorite |
| 2 | GET | `/favorites/{user_id}` | JWT | List favorites |
| 3 | DELETE | `/favorites/{id}` | JWT | Remove favorite |
| 4 | POST | `/ratings` | JWT | Add rating |
| 5 | GET | `/ratings/{assignment_id}` | JWT | List ratings |

## A.9 Notifications (3 endpoints)

| # | Method | Path | Auth | Purpose |
|---|--------|------|------|---------|
| 1 | POST | `/notifications/settings` | JWT | Create alert |
| 2 | GET | `/notifications/settings/{user_id}` | JWT | List alerts |
| 3 | POST | `/notifications/register-token` | JWT | Register FCM |

## A.10 Pairing (3 endpoints)

| # | Method | Path | Auth | Purpose |
|---|--------|------|------|---------|
| 1 | POST | `/admin/vehicles/{id}/generate-pairing-code` | Admin | Generate code |
| 2 | POST | `/pair/verify` | None | Verify + set password |
| 3 | POST | `/admin/vehicles/{id}/unpair` | Admin | Remove pairing |

## A.11 Telemetry (2 endpoints)

| # | Method | Path | Auth | Purpose |
|---|--------|------|------|---------|
| 1 | POST | `/telemetry` | None | SIM7600 telemetry |
| 2 | POST | `/gateway/esp32/telemetry` | None | ESP32-CAM telemetry |

## A.12 Search (2 endpoints)

| # | Method | Path | Auth | Purpose |
|---|--------|------|------|---------|
| 1 | POST | `/search/point-to-point` | None | Stop-based search |
| 2 | POST | `/search/journey` | None | Geo-based search |

## A.13 WebSocket (2 endpoints)

| # | Type | Path | Auth | Purpose |
|---|------|------|------|---------|
| 1 | WS | `/ws/live` | JWT (admin) | Admin fleet stream |
| 2 | WS | `/ws/mobile` | JWT | Passenger route stream |

## A.14 Health (1 endpoint)

| # | Method | Path | Auth | Purpose |
|---|--------|------|------|---------|
| 1 | GET | `/health` | None | System health |

---

**Total: 67 HTTP endpoints + 2 WebSocket = 69 handlers**

---

*Document generated: June 9, 2026*
*No backend code was modified. This plan is based entirely on the existing API surface.*
