# 🚌 BusTrack — Mobile App Developer Guide

> **Complete API Reference & UI Integration Blueprint**
> Version 1.0.0 | Smart Transport — Real-time Public Transport Tracking for Addis Ababa

---

## 📖 Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture Summary](#2-architecture-summary)
3. [Base URL & Environment](#3-base-url--environment)
4. [Authentication & OAuth](#4-authentication--oauth)
5. [All API Endpoints (Detailed)](#5-all-api-endpoints-detailed)
6. [WebSocket Real-Time Stream](#6-websocket-real-time-stream)
7. [Data Models & Response Shapes](#7-data-models--response-shapes)
8. [Error Handling](#8-error-handling)
9. [Rate Limiting](#9-rate-limiting)
10. [UI/UX Design Specification](#10-uiux-design-specification)
11. [Feature-by-Feature UI Implementation Guide](#11-feature-by-feature-ui-implementation-guide)
12. [State Management & Async Patterns](#12-state-management--async-patterns)
13. [Push Notifications (FCM)](#13-push-notifications-fcm)
14. [Testing the API](#14-testing-the-api)

---

## 1. Project Overview

BusTrack is a **real-time public transport tracking and crowd density prediction** system for Addis Ababa, Ethiopia. The backend:

- Ingests **GPS telemetry** from IoT devices (SIM7600/ESP32-CAM) mounted on buses
- Estimates **passenger crowd density** via OpenCV computer vision
- Computes **ETA** using heuristic + ML models
- Streams **live positions** to admin dashboards via WebSocket
- Provides a **REST API** for the mobile app to search, track, favorite, and rate bus journeys

### User Roles

| Role | Description | Created By |
|------|-------------|------------|
| **Passenger** | Searches routes, tracks buses, saves favorites, rates journeys, sets notifications | Self-registration |
| **Driver** | Logs into bus dashboard device | Admin |
| **Admin** | Full system access, user management, ML training, live dashboard | Admin |

---

## 2. Architecture Summary

```
┌─────────────┐     HTTPS      ┌──────────────────┐     SQL      ┌────────────┐
│  Mobile App  │ ◄──────────► │   FastAPI Backend  │ ◄────────► │ PostgreSQL │
│  (You Build) │     WSS       │   (This System)   │            │  + PostGIS │
└─────────────┘ ◄──────────► │                  │     Cache    └────────────┘
                               │                  │ ◄────────► ┌────────────┐
                               │                  │            │   Redis    │
                               └──────────────────┘            │  (Upstash) │
                                        │                      └────────────┘
                                        │ Telemetry
                                        ▼
                               ┌──────────────────┐
                               │  IoT Devices     │
                               │  (SIM7600/ESP32) │
                               └──────────────────┘
```

**Tech Stack (Backend):** Python 3.11, FastAPI, SQLAlchemy (async), PostgreSQL + PostGIS, Redis, OpenCV, scikit-learn, Alembic, Docker

---

## 3. Base URL & Environment

```
Production:  https://bustrack.dpdns.org/api/v1
Local Dev:   http://localhost:8000/api/v1
Health:      GET /health
```

All endpoints are prefixed with `/api/v1`.

### Content-Type

- JSON endpoints: `application/json`
- Multipart (image upload): `multipart/form-data`

---

## 4. Authentication & OAuth

The app uses **JWT Bearer tokens** for authentication. Tokens expire after **24 hours** and can be refreshed.

### Auth Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        PASSENGER AUTH FLOW                          │
│                                                                     │
│  ┌──────────┐    ┌───────────┐    ┌──────────┐    ┌─────────────┐  │
│  │ Register  │───►│  Verify   │───►│  Login   │───►│  Use JWT    │  │
│  │ (email+   │    │  Email    │    │  (get    │    │  Bearer     │  │
│  │  password)│    │  (token)  │    │   JWT)   │    │  Token      │  │
│  └──────────┘    └───────────┘    └──────────┘    └─────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    GOOGLE OAUTH FLOW                         │   │
│  │                                                              │   │
│  │  Google Sign-In ──► Get id_token ──► POST /auth/google       │   │
│  │                                    ──► Get JWT               │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Token Usage

Every authenticated request must include the JWT in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

### Token Refresh Strategy

- Tokens last **24 hours**
- Call `POST /auth/refresh` with the current valid token to get a new one
- **UI Suggestion:** Auto-refresh silently when the user opens the app if the token is older than 12 hours

---

### 4.1 Auth Endpoints (Detailed)

#### `POST /auth/register` — Passenger Signup

**Rate Limit:** 10/minute

**Request:**
```json
{
  "username": "johndoe",
  "email": "john@example.com",
  "password": "securePass123"
}
```

**Validation Rules:**
- `username`: 3–100 characters
- `email`: Valid email format
- `password`: 8–100 characters

**Response (201):**
```json
{
  "id": 1,
  "username": "johndoe",
  "email": "john@example.com",
  "role": "passenger",
  "created_at": "2025-01-15T10:30:00"
}
```

**Errors:**
| Status | Detail |
|--------|--------|
| 400 | `"Username already registered"` |
| 400 | `"Email already registered"` |

**UI Flow:**
```
[Register Screen] → POST /auth/register → [Check Email Screen] → (user taps link in email) → [Email Verified Screen] → [Login Screen]
```

---

#### `POST /auth/login` — Email/Password Login

**Rate Limit:** 20/minute

**Request:**
```json
{
  "username": "johndoe",
  "password": "securePass123"
}
```

**Response (200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

**Errors:**
| Status | Detail |
|--------|--------|
| 401 | `"Invalid credentials"` |
| 401 | `"Use Google sign-in for this account"` (user registered via Google) |

**UI Flow:**
```
[Login Screen] → POST /auth/login → Store JWT securely → [Home/Map Screen]
```

---

#### `POST /auth/google` — Google OAuth

**Rate Limit:** 20/minute

**Request:**
```json
{
  "id_token": "eyJhbGciOiJSUzI1NiIs..."
}
```

**Response (200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

**Errors:**
| Status | Detail |
|--------|--------|
| 401 | `"Invalid Google token"` |
| 401 | `"Token audience mismatch"` |
| 400 | `"Email already registered. Use password login."` |
| 503 | `"Google OAuth not configured"` |

**UI Flow:**
```
[Login Screen] → Tap "Sign in with Google" → Google Sign-In SDK → Get id_token → POST /auth/google → Store JWT → [Home/Map Screen]
```

---

#### `GET /auth/me` — Current User Profile

**Rate Limit:** 30/minute
**Auth:** Required (Bearer JWT)

**Response (200):**
```json
{
  "id": 1,
  "username": "johndoe",
  "email": "john@example.com",
  "role": "passenger",
  "created_at": "2025-01-15T10:30:00"
}
```

**UI Usage:** Display in profile screen, settings screen header, drawer/sidebar.

---

#### `POST /auth/refresh` — Refresh JWT

**Auth:** Required (Bearer JWT)

**Response (200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

---

#### `POST /auth/verify-email` — Verify Email

**Rate Limit:** 10/minute

**Request:**
```json
{
  "token": "abc123def456"
}
```

**Response (200):**
```json
{
  "status": "verified"
}
```

**Errors:**
| Status | Detail |
|--------|--------|
| 400 | `"Invalid or expired verification token"` |
| 404 | `"User not found"` |

**UI Flow:** Deep link from email → extract token → POST /auth/verify-email → [Success Screen]

---

#### `POST /auth/resend-verification` — Resend Verification Email

**Rate Limit:** 5/minute

**Request:**
```json
{
  "email": "john@example.com"
}
```

**Response (200):**
```json
{
  "status": "sent"
}
```

> **Note:** Always returns `"sent"` even if email doesn't exist (prevents email enumeration).

---

#### `POST /auth/forgot-password` — Request Password Reset

**Rate Limit:** 5/minute

**Request:**
```json
{
  "email": "john@example.com"
}
```

**Response (200):**
```json
{
  "status": "sent"
}
```

> **Note:** Always returns `"sent"` to prevent email enumeration.

---

#### `POST /auth/reset-password` — Reset Password with Token

**Rate Limit:** 5/minute

**Request:**
```json
{
  "token": "reset_token_here",
  "new_password": "newSecurePass456"
}
```

**Response (200):**
```json
{
  "status": "reset"
}
```

**Errors:**
| Status | Detail |
|--------|--------|
| 400 | `"Invalid or expired reset token"` |
| 404 | `"User not found"` |

---

## 5. All API Endpoints (Detailed)

### 5.1 Search & Journey Planning

#### `POST /search/journey` — Search Routes & Live Buses

**Auth:** Public
**Description:** The **core endpoint** for the user's primary use case. Search for buses between two locations using either GPS coordinates or text queries (e.g., "Merkato" to "Bole").

**Request (using coordinates):**
```json
{
  "start_lat": 9.0222,
  "start_lon": 38.7468,
  "end_lat": 9.0194,
  "end_lon": 38.7579,
  "max_routes": 5,
  "max_buses": 10
}
```

**Request (using text queries):**
```json
{
  "start_query": "Merkato",
  "end_query": "Bole",
  "max_routes": 5,
  "max_buses": 10
}
```

**Response (200):**
```json
{
  "start": {
    "query": "Merkato",
    "lat": 9.0222,
    "lon": 38.7468,
    "stop_id": 1,
    "stop_name": "Merkato Terminal",
    "distance_m": 45
  },
  "end": {
    "query": "Bole",
    "lat": 9.0194,
    "lon": 38.7579,
    "stop_id": 15,
    "stop_name": "Bole Terminal",
    "distance_m": 120
  },
  "routes": [
    {
      "route_id": 1,
      "route_number": "101",
      "direction": "forward",
      "name": "Merkato - Bole",
      "start_index": 0,
      "end_index": 14,
      "buses": [
        {
          "vehicle_id": 5,
          "plate_number": "ET-1234-AB",
          "lat": 9.0210,
          "lon": 38.7450,
          "speed": 32.5,
          "route_id": 1,
          "assignment_id": 12,
          "occupancy_level": 1,
          "eta_seconds": 420,
          "eta_live_seconds": 380,
          "eta_mode": "heuristic",
          "eta_ml_seconds": 360,
          "eta_heuristic_seconds": 420,
          "distance_m": 1200
        }
      ]
    }
  ]
}
```

**Field Explanations:**

| Field | Type | Description |
|-------|------|-------------|
| `occupancy_level` | int | **0** = Empty/Low, **1** = Medium, **2** = Crowded/Full |
| `eta_seconds` | int | ETA in seconds (from selected mode) |
| `eta_live_seconds` | int/null | Real-time adjusted ETA (null if stale) |
| `eta_mode` | string | `"heuristic"` or `"ml"` |
| `eta_ml_seconds` | float/null | ML model ETA (if available) |
| `eta_heuristic_seconds` | float | Heuristic ETA |
| `distance_m` | float | Distance from bus to destination in meters |

**Errors:**
| Status | Detail |
|--------|--------|
| 400 | `"start location could not be resolved"` |
| 400 | `"end location could not be resolved"` |
| 404 | `"No stops found near the provided locations"` |

**UI Flow:**
```
[Home Screen] → User enters "From" and "To" → POST /search/journey → [Results Screen with map + list]
```

---

#### `POST /search/point-to-point` — Search Between Known Stops

**Auth:** Public
**Description:** Find routes and ETAs between two specific stop IDs (when user has already selected stops from a list).

**Request:**
```json
{
  "start_stop_id": 1,
  "end_stop_id": 15
}
```

**Response (200):**
```json
{
  "routes": [
    {
      "route_number": "101",
      "etas": {
        "eta_seconds": 420,
        "computed_at": 1705312200,
        "eta_live_seconds": 380
      }
    }
  ],
  "start_stop": "Merkato Terminal",
  "end_stop": "Bole Terminal"
}
```

---

### 5.2 Vehicles & Live Positions

#### `GET /vehicles/positions` — All Live Vehicle Positions

**Auth:** Public
**Description:** Get all currently active vehicle positions. Use this to plot buses on the map.

**Response (200):**
```json
{
  "positions": {
    "ET-1234-AB": {
      "vehicle_id": 5,
      "plate_number": "ET-1234-AB",
      "lat": 9.0210,
      "lon": 38.7450,
      "speed": 32.5,
      "timestamp": 1705312200.0,
      "route_id": 1,
      "assignment_id": 12
    },
    "ET-5678-CD": {
      "vehicle_id": 8,
      "plate_number": "ET-5678-CD",
      "lat": 9.0150,
      "lon": 38.7600,
      "speed": 18.0,
      "timestamp": 1705312180.0,
      "route_id": 2,
      "assignment_id": 15
    }
  },
  "timestamp": 1705312200.0
}
```

> **Note:** Positions older than 180 seconds (3 minutes) are considered stale and excluded.

**UI Usage:** Poll every 5–10 seconds to update bus markers on the map. Show a "last updated" indicator.

---

#### `GET /vehicles/positions/{vehicle_id}` — Single Vehicle Position

**Auth:** Public

**Response (200):**
```json
{
  "vehicle_id": 5,
  "plate_number": "ET-1234-AB",
  "lat": 9.0210,
  "lon": 38.7450,
  "speed": 32.5,
  "timestamp": 1705312200.0,
  "route_id": 1,
  "assignment_id": 12
}
```

**Errors:**
| Status | Detail |
|--------|--------|
| 404 | `"Position not found"` |

---

#### `GET /vehicles` — List All Vehicles

**Auth:** Public

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `skip` | int | 0 | Pagination offset |
| `limit` | int | 100 | Max results per page |

**Response (200):**
```json
[
  {
    "id": 5,
    "plate_number": "ET-1234-AB",
    "device_id": "ESP32-001",
    "bus_type": "minibus",
    "capacity": 25,
    "is_active": true,
    "route_id": 1,
    "route_number": "101",
    "last_lat": 9.0210,
    "last_lon": 38.7450,
    "speed": 32.5,
    "position_updated_at": "2025-01-15T10:30:00"
  }
]
```

---

#### `GET /vehicles/{vehicle_id}` — Vehicle Details

**Auth:** Public

**Response (200):** Same as single item from `GET /vehicles`

**Errors:**
| Status | Detail |
|--------|--------|
| 404 | `"Vehicle not found"` |

---

### 5.3 Routes & Stops

#### `GET /routes` — List All Routes

**Auth:** Public

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `skip` | int | 0 | Pagination offset |
| `limit` | int | 100 | Max results per page |

**Response (200):**
```json
[
  {
    "id": 1,
    "route_number": "101",
    "direction": "forward",
    "name": "Merkato - Bole",
    "origin": "Merkato",
    "destination": "Bole"
  }
]
```

---

#### `GET /routes/{route_id}` — Route with Ordered Stops

**Auth:** Public

**Response (200):**
```json
{
  "id": 1,
  "route_number": "101",
  "direction": "forward",
  "name": "Merkato - Bole",
  "origin": "Merkato",
  "destination": "Bole",
  "stops": [
    {
      "id": 1,
      "name": "Merkato Terminal",
      "lat": 9.0222,
      "lon": 38.7468,
      "base_dwell_time": 30,
      "is_terminal": true,
      "peak_multiplier": 1.5
    },
    {
      "id": 2,
      "name": "Merkato Market",
      "lat": 9.0215,
      "lon": 38.7460,
      "base_dwell_time": 30,
      "is_terminal": false,
      "peak_multiplier": 1.5
    }
  ]
}
```

**UI Usage:** Display route line on map, show stop markers, draw polyline connecting stops.

---

#### `GET /stops` — List All Stops

**Auth:** Public

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `skip` | int | 0 | Pagination offset |
| `limit` | int | 100 | Max results per page |

**Response (200):**
```json
[
  {
    "id": 1,
    "name": "Merkato Terminal",
    "lat": 9.0222,
    "lon": 38.7468,
    "base_dwell_time": 30,
    "is_terminal": true,
    "peak_multiplier": 1.5
  }
]
```

---

#### `GET /stops/{stop_id}` — Single Stop Details

**Auth:** Public

**Response (200):** Same as single item from `GET /stops`

**Errors:**
| Status | Detail |
|--------|--------|
| 404 | `"Stop not found"` |

---

### 5.4 Favorites & Ratings

#### `POST /favorites` — Save a Favorite Route

**Auth:** Public (requires `user_id` — in production, derive from JWT)

**Request:**
```json
{
  "user_id": 1,
  "route_id": 1,
  "nickname": "Home to Work"
}
```

**Response (200):**
```json
{
  "id": 1,
  "user_id": 1,
  "route_id": 1,
  "nickname": "Home to Work"
}
```

**UI Flow:**
```
[Route Detail Screen] → Tap "♡ Favorite" → POST /favorites → Show "♥ Saved" → Appears in [Favorites Screen]
```

---

#### `GET /favorites/{user_id}` — List User Favorites

**Auth:** Public

**Response (200):**
```json
[
  {
    "id": 1,
    "user_id": 1,
    "route_id": 1,
    "nickname": "Home to Work"
  }
]
```

---

#### `POST /ratings` — Rate a Journey

**Auth:** Public

**Request:**
```json
{
  "user_id": 1,
  "assignment_id": 12,
  "score": 4,
  "comment": "Bus was on time but crowded"
}
```

**Validation:** `score` must be 1–5

**Response (200):**
```json
{
  "id": 1,
  "score": 4
}
```

**Errors:**
| Status | Detail |
|--------|--------|
| 400 | `"Score must be 1-5"` |

**UI Flow:**
```
[After journey ends] → [Rate Journey Screen] → Star rating (1-5) + optional comment → POST /ratings → [Thank You Screen]
```

---

#### `GET /ratings/{assignment_id}` — List Ratings for Assignment

**Auth:** Public

**Response (200):**
```json
[
  {
    "id": 1,
    "user_id": 1,
    "assignment_id": 12,
    "score": 4,
    "comment": "Bus was on time but crowded",
    "timestamp": "2025-01-15T11:00:00"
  }
]
```

---

### 5.5 Notifications (Proximity Alerts)

#### `POST /notifications/settings` — Set Proximity Alert

**Auth:** Public

**Request:**
```json
{
  "user_id": 1,
  "route_id": 1,
  "lead_time_minutes": 10
}
```

**Response (200):**
```json
{
  "id": 1,
  "lead_time_minutes": 10
}
```

**UI Flow:**
```
[Route Detail Screen] → Tap "🔔 Notify me" → [Notification Settings Sheet] → Set lead time (5/10/15/20 min) → POST /notifications/settings
```

---

#### `GET /notifications/settings/{user_id}` — Get Notification Settings

**Auth:** Public

**Response (200):**
```json
[
  {
    "id": 1,
    "user_id": 1,
    "route_id": 1,
    "lead_time_minutes": 10
  }
]
```

---

### 5.6 Health Check

#### `GET /health` — System Health

**Auth:** Public

**Response (200 — Healthy):**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "database": "connected",
  "redis": "connected"
}
```

**Response (503 — Degraded):**
```json
{
  "status": "degraded",
  "version": "1.0.0",
  "database": "error: ConnectionRefusedError",
  "redis": "connected"
}
```

**UI Usage:** Show a banner or snackbar when the API is degraded.

---

## 6. WebSocket Real-Time Stream

### Overview

The WebSocket endpoint is primarily designed for the **admin dashboard**, but the mobile app can optionally use it for real-time bus position updates instead of polling.

### Connection

```
WSS://bustrack.dpdns.org/api/v1/ws/live?token=<JWT>
```

> **Important:** The JWT must be an **admin** token. For passenger apps, use polling (`GET /vehicles/positions`) instead.

### Protocol

**Connection Lifecycle:**
```
Client                                    Server
  │                                         │
  │───── WSS /ws/live?token=<jwt> ────────►│
  │                                         │ (validates JWT + admin role)
  │◄──── {"type": "connected",             │
  │       "detail": "fleet_stream"}        │
  │                                         │
  │◄──── {"type": "vehicle_position",      │ (broadcast from IoT devices)
  │       "vehicle_id": 5,                 │
  │       "plate_number": "ET-1234-AB",    │
  │       "lat": 9.021,                    │
  │       "lon": 38.745,                   │
  │       "speed": 32.5,                   │
  │       "route_id": 1,                   │
  │       "timestamp": 1705312200.0,       │
  │       "occupancy_level": 1}            │
  │                                         │
  │◄──── {"type": "heartbeat"}             │ (every 90s of inactivity)
  │                                         │
  │───── {"type": "ping"} ────────────────►│
  │◄──── {"type": "pong"}                  │
  │                                         │
  │───── (disconnect) ────────────────────►│
  │                                         │ (server cleans up)
```

### Message Types

#### `vehicle_position` — Live Bus Position Update

```json
{
  "type": "vehicle_position",
  "vehicle_id": 5,
  "plate_number": "ET-1234-AB",
  "lat": 9.021,
  "lon": 38.745,
  "speed": 32.5,
  "route_id": 1,
  "timestamp": 1705312200.0,
  "occupancy_level": 1
}
```

#### `cv_result` — Crowd Density Analysis Result

```json
{
  "type": "cv_result",
  "vehicle_id": 5,
  "plate_number": "ET-1234-AB",
  "timestamp": 1705312200.0,
  "cv": {
    "people_count": 18,
    "crowd_density": 2,
    "is_crowded": true,
    "method": "hog",
    "confidence": 0.85,
    "foreground_ratio": 0.72
  }
}
```

#### `connected` — Connection Established

```json
{
  "type": "connected",
  "detail": "fleet_stream"
}
```

#### `heartbeat` — Server Keep-Alive

Sent every 90 seconds if no messages were sent.

```json
{
  "type": "heartbeat"
}
```

#### `pong` — Ping Response

```json
{
  "type": "pong"
}
```

#### `error` — Connection Error

```json
{
  "type": "error",
  "detail": "missing_token" | "invalid_token" | "admin_only"
}
```

### WebSocket Implementation (Mobile)

**For Passenger App — Use Polling Instead:**
```
Poll GET /vehicles/positions every 5-10 seconds
```

**For Admin App — Use WebSocket:**

```javascript
// React Native example
const ws = new WebSocket('wss://bustrack.dpdns.org/api/v1/ws/live?token=' + adminJwt);

ws.onopen = () => console.log('Connected to live stream');
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  switch (data.type) {
    case 'connected':
      // Show "Live" indicator
      break;
    case 'vehicle_position':
      // Update bus marker on map
      updateBusMarker(data);
      break;
    case 'cv_result':
      // Update crowd density panel
      updateCrowdPanel(data.cv);
      break;
    case 'heartbeat':
      // Connection is alive
      break;
  }
};
ws.onerror = (error) => console.error('WebSocket error', error);
ws.onclose = () => {
  // Auto-reconnect with exponential backoff
  setTimeout(connectWebSocket, reconnectDelay);
};
```

### Reconnection Strategy

```
Disconnect → Wait 1s → Reconnect
If failed → Wait 2s → Reconnect
If failed → Wait 4s → Reconnect
If failed → Wait 8s → Reconnect
...max 60s between retries
```

---

## 7. Data Models & Response Shapes

### Occupancy Level Enum

| Value | Meaning | Color | Icon |
|-------|---------|-------|------|
| `0` | Empty / Low | 🟢 Green | Sparse dots |
| `1` | Medium | 🟡 Yellow | Medium dots |
| `2` | Crowded / Full | 🔴 Red | Dense dots |

### User Object

```json
{
  "id": 1,
  "username": "johndoe",
  "email": "john@example.com",
  "role": "passenger",
  "created_at": "2025-01-15T10:30:00"
}
```

### Vehicle Object

```json
{
  "id": 5,
  "plate_number": "ET-1234-AB",
  "device_id": "ESP32-001",
  "bus_type": "minibus",
  "capacity": 25,
  "is_active": true,
  "route_id": 1,
  "route_number": "101",
  "last_lat": 9.0210,
  "last_lon": 38.7450,
  "speed": 32.5,
  "position_updated_at": "2025-01-15T10:30:00"
}
```

### Route Object

```json
{
  "id": 1,
  "route_number": "101",
  "direction": "forward",
  "name": "Merkato - Bole",
  "origin": "Merkato",
  "destination": "Bole"
}
```

### Stop Object

```json
{
  "id": 1,
  "name": "Merkato Terminal",
  "lat": 9.0222,
  "lon": 38.7468,
  "base_dwell_time": 30,
  "is_terminal": true,
  "peak_multiplier": 1.5
}
```

---

## 8. Error Handling

All errors follow a consistent format:

```json
{
  "detail": "Error message here"
}
```

### Common HTTP Status Codes

| Code | Meaning | Action |
|------|---------|--------|
| 200 | Success | Process response |
| 400 | Bad Request | Show validation error to user |
| 401 | Unauthorized | Redirect to login |
| 403 | Forbidden | Show "not allowed" message |
| 404 | Not Found | Show "not found" state |
| 409 | Conflict | Show conflict message (e.g., "already exists") |
| 429 | Rate Limited | Back off, retry after delay |
| 503 | Service Unavailable | Show "try again later" |

### Error Handling Pattern

```javascript
try {
  const response = await fetch(url, options);
  if (!response.ok) {
    const error = await response.json();
    switch (response.status) {
      case 401:
        // Token expired → refresh or redirect to login
        await refreshToken();
        break;
      case 429:
        // Rate limited → exponential backoff
        await delay(retryAfter * 1000);
        break;
      default:
        showError(error.detail);
    }
  }
  return await response.json();
} catch (networkError) {
  showError('Network error. Check your connection.');
}
```

---

## 9. Rate Limiting

| Endpoint | Limit |
|----------|-------|
| `/auth/register` | 10/minute |
| `/auth/login` | 20/minute |
| `/auth/google` | 20/minute |
| `/auth/me` | 30/minute |
| `/auth/verify-email` | 10/minute |
| `/auth/resend-verification` | 5/minute |
| `/auth/forgot-password` | 5/minute |
| `/auth/reset-password` | 5/minute |
| `/telemetry` | 300/minute |
| Most other endpoints | 60/minute (default) |

**UI Suggestion:** When receiving 429, show a toast: "Too many requests. Please wait a moment."

---

## 10. UI/UX Design Specification

### 10.1 Design System: "TransitFlow"

A futuristic, clean, and highly functional design system optimized for transit apps used in bright sunlight (Addis Ababa context).

### 10.2 Color Palette

#### Primary Colors

| Name | Hex | Usage |
|------|-----|-------|
| **Deep Space** | `#0A0E27` | Primary dark background, nav bar |
| **Electric Blue** | `#2563EB` | Primary buttons, active states, links |
| **Neon Cyan** | `#06B6D4` | Accents, highlights, live indicators |
| **Pure White** | `#FFFFFF` | Text on dark backgrounds, cards |

#### Secondary Colors

| Name | Hex | Usage |
|------|-----|-------|
| **Slate Dark** | `#1E293B` | Card backgrounds, input fields |
| **Slate Mid** | `#334155` | Borders, dividers |
| **Slate Light** | `#94A3B8` | Secondary text, placeholders |
| **Soft Gray** | `#E2E8F0` | Disabled states, backgrounds |

#### Semantic Colors

| Name | Hex | Usage |
|------|-----|-------|
| **Success Green** | `#10B981` | Empty bus, on-time, success states |
| **Warning Amber** | `#F59E0B` | Medium crowd, delayed |
| **Danger Red** | `#EF4444` | Crowded bus, errors, alerts |
| **Info Blue** | `#3B82F6` | Information, neutral states |

#### Occupancy Colors

| Level | Color | Hex | Gradient |
|-------|-------|-----|----------|
| Empty (0) | Green | `#10B981` | `#059669` → `#10B981` |
| Medium (1) | Amber | `#F59E0B` | `#D97706` → `#F59E0B` |
| Crowded (2) | Red | `#EF4444` | `#DC2626` → `#EF4444` |

#### Map Colors

| Element | Color | Hex |
|---------|-------|-----|
| Route line (active) | Electric Blue | `#2563EB` |
| Route line (inactive) | Slate Mid | `#475569` |
| Stop marker (normal) | Neon Cyan | `#06B6D4` |
| Stop marker (terminal) | Electric Blue | `#2563EB` |
| Bus marker (empty) | Green | `#10B981` |
| Bus marker (medium) | Amber | `#F59E0B` |
| Bus marker (crowded) | Red | `#EF4444` |
| User location | Blue pulse | `#3B82F6` |

### 10.3 Typography

| Style | Size | Weight | Usage |
|-------|------|--------|-------|
| **Display** | 32px | Bold (700) | Splash screen title |
| **H1** | 24px | Bold (700) | Screen titles |
| **H2** | 20px | SemiBold (600) | Section headers |
| **H3** | 17px | SemiBold (600) | Card titles |
| **Body** | 15px | Regular (400) | Main text |
| **Body Small** | 13px | Regular (400) | Secondary text |
| **Caption** | 11px | Medium (500) | Labels, timestamps |
| **Button** | 16px | SemiBold (600) | Button text |
| **ETA Large** | 28px | Bold (700) | ETA countdown display |

**Font Family:** System default (SF Pro on iOS, Roboto on Android) or `Inter` for cross-platform consistency.

### 10.4 Spacing & Layout

| Token | Value | Usage |
|-------|-------|-------|
| `xs` | 4px | Tight spacing |
| `sm` | 8px | Icon-to-label |
| `md` | 16px | Standard padding |
| `lg` | 24px | Section spacing |
| `xl` | 32px | Screen edge padding |
| `xxl` | 48px | Major section breaks |

### 10.5 Component Sizes

#### Buttons

| Type | Height | Min Width | Border Radius | Padding |
|------|--------|-----------|---------------|---------|
| **Primary** | 52px | 200px | 16px (fully rounded) | 16px 24px |
| **Secondary** | 48px | 160px | 12px | 12px 20px |
| **Small** | 36px | 100px | 10px | 8px 16px |
| **Icon Button** | 44px | 44px | 12px | 10px |
| **FAB** | 56px | 56px | 16px (circular) | — |

#### Input Fields

| Property | Value |
|----------|-------|
| Height | 52px |
| Border Radius | 12px |
| Border Width | 1.5px |
| Focus Border Color | `#2563EB` |
| Error Border Color | `#EF4444` |
| Background | `#1E293B` |
| Text Color | `#FFFFFF` |
| Placeholder Color | `#94A3B8` |

#### Cards

| Property | Value |
|----------|-------|
| Border Radius | 16px |
| Background | `#1E293B` |
| Padding | 16px |
| Shadow | `0 4px 12px rgba(0,0,0,0.3)` |
| Border | `1px solid #334155` |

#### Map Markers

| Type | Size |
|------|------|
| Bus marker | 40×40px |
| Stop marker | 24×24px |
| Terminal marker | 32×32px |
| User location | 20×20px + 40×40px pulse |

### 10.6 Iconography

Use **rounded/outlined** icon style for consistency:

| Icon | Usage |
|------|-------|
| 🚌 | Bus / Vehicle |
| 📍 | Stop / Location |
| 🔍 | Search |
| ❤️ / ♡ | Favorite (filled / outline) |
| 🔔 | Notification |
| ⭐ | Rating |
| 🧭 | Directions |
| 👤 | Profile |
| ⚙️ | Settings |
| 🔄 | Refresh |
| 📡 | Live / Signal |
| ⏱️ | ETA / Time |

### 10.7 Animations & Micro-interactions

| Animation | Duration | Easing | Usage |
|-----------|----------|--------|-------|
| Screen transition | 300ms | ease-in-out | Navigation |
| Button press | 100ms | ease-out | Scale to 0.96 |
| Card appear | 250ms | ease-out | Fade up |
| Map marker update | 500ms | linear | Smooth position change |
| Pull to refresh | 200ms | spring | Refresh indicator |
| Skeleton loading | 1500ms | linear | Shimmer effect |
| Occupancy change | 300ms | ease | Color transition |
| ETA countdown | 1000ms | linear | Number tick |
| Toast | 250ms | ease | Slide up + fade |

### 10.8 Dark Theme (Default)

The app should use a **dark theme by default** (better for battery, readability in varying light):

```
Background:        #0A0E27 (Deep Space)
Surface:           #1E293B (Slate Dark)
Surface Variant:   #334155 (Slate Mid)
Primary:           #2563EB (Electric Blue)
Secondary:         #06B6D4 (Neon Cyan)
Text Primary:      #FFFFFF (Pure White)
Text Secondary:    #94A3B8 (Slate Light)
Error:             #EF4444 (Danger Red)
```

### 10.9 Light Theme (Optional)

```
Background:        #F8FAFC (Slate 50)
Surface:           #FFFFFF (White)
Surface Variant:   #F1F5F9 (Slate 100)
Primary:           #2563EB (Electric Blue)
Secondary:         #0891B2 (Cyan 600)
Text Primary:      #0F172A (Slate 900)
Text Secondary:    #64748B (Slate 500)
Error:             #DC2626 (Red 600)
```

---

## 11. Feature-by-Feature UI Implementation Guide

### 11.1 Splash Screen

```
┌─────────────────────────────────────┐
│                                     │
│                                     │
│            🚌                       │
│         BusTrack                    │
│    Smart Transport System           │
│                                     │
│         [Loading Spinner]           │
│                                     │
│                                     │
└─────────────────────────────────────┘
```

**Behavior:**
- Display for 2–3 seconds
- Check if stored JWT exists and is valid
- If valid → navigate to Home
- If invalid/expired → navigate to Login
- Call `GET /health` to check API status

**Implementation:**
```
On mount:
  1. Start 2s timer
  2. Check AsyncStorage for 'auth_token'
  3. If token exists → POST /auth/refresh
  4. If refresh succeeds → Home Screen
  5. If refresh fails → Login Screen
  6. If no token → Login Screen
```

---

### 11.2 Authentication Screens

#### Login Screen

```
┌─────────────────────────────────────┐
│                                     │
│            🚌 BusTrack              │
│                                     │
│  ┌─────────────────────────────┐    │
│  │ 👤 Username                 │    │
│  └─────────────────────────────┘    │
│  ┌─────────────────────────────┐    │
│  │ 🔒 Password                 │    │
│  └─────────────────────────────┘    │
│                                     │
│  ┌─────────────────────────────┐    │
│  │       ▶  LOGIN              │    │  ← Primary button, Electric Blue
│  └─────────────────────────────┘    │
│                                     │
│  ┌─────────────────────────────┐    │
│  │  🔵 Sign in with Google     │    │  ← Secondary button
│  └─────────────────────────────┘    │
│                                     │
│  Forgot Password?                   │
│                                     │
│  ── Don't have an account? ──       │
│        Register →                   │
│                                     │
└─────────────────────────────────────┘
```

**API Calls:**
1. `POST /auth/login` — on form submit
2. `POST /auth/google` — on Google Sign-In

**Token Storage:**
```javascript
// Store securely (use Keychain on iOS, Keystore on Android)
await SecureStore.setItemAsync('auth_token', token);
await SecureStore.setItemAsync('refresh_token', token); // same endpoint
await SecureStore.setItemAsync('user_data', JSON.stringify(user));
```

---

#### Register Screen

```
┌─────────────────────────────────────┐
│                                     │
│          Create Account             │
│                                     │
│  ┌─────────────────────────────┐    │
│  │ 👤 Username                 │    │
│  └─────────────────────────────┘    │
│  ┌─────────────────────────────┐    │
│  │ 📧 Email                    │    │
│  └─────────────────────────────┘    │
│  ┌─────────────────────────────┐    │
│  │ 🔒 Password                 │    │
│  └─────────────────────────────┘    │
│  ┌─────────────────────────────┐    │
│  │ 🔒 Confirm Password         │    │
│  └─────────────────────────────┘    │
│                                     │
│  ┌─────────────────────────────┐    │
│  │      ▶  REGISTER            │    │
│  └─────────────────────────────┘    │
│                                     │
│  Already have an account? Login →   │
│                                     │
└─────────────────────────────────────┘
```

**API Calls:**
1. `POST /auth/register` — on form submit
2. Navigate to "Check Email" screen

---

#### Email Verification Screen

```
┌─────────────────────────────────────┐
│                                     │
│            📧                       │
│     Check Your Email                │
│                                     │
│  We sent a verification link to:    │
│  john@example.com                   │
│                                     │
│  ┌─────────────────────────────┐    │
│  │   Resend Verification       │    │
│  └─────────────────────────────┘    │
│                                     │
│  Already verified? Login →          │
│                                     │
└─────────────────────────────────────┘
```

**API Calls:**
1. `POST /auth/resend-verification` — on "Resend" tap
2. Deep link handler → `POST /auth/verify-email`

---

### 11.3 Home Screen (Main Map)

This is the **core screen** of the app.

```
┌─────────────────────────────────────┐
│ 🔍 Where to?          👤  🔔       │  ← Top bar
├─────────────────────────────────────┤
│                                     │
│         ┌─────────┐                 │
│         │ Search  │                 │  ← Search bar (floating)
│         │  Bar    │                 │
│         └─────────┘                 │
│                                     │
│    ┌───┐                            │
│    │ 📍│  ← User location           │
│    └───┘                            │
│                                     │
│         🚌 ← Bus marker             │
│            (color = occupancy)      │
│                                     │
│    📍 ← Stop marker                 │
│                                     │
│  ┌─────────────────────────────┐    │
│  │  🔍 Plan Journey            │    │  ← Bottom sheet trigger
│  └─────────────────────────────┘    │
│                                     │
│                         [🧭] [+]    │  ← Map controls
│                         [-]         │
└─────────────────────────────────────┘
```

**Implementation:**

```javascript
// Home Screen Logic
const HomeScreen = () => {
  const [buses, setBuses] = useState([]);
  const [stops, setStops] = useState([]);
  const [selectedBus, setSelectedBus] = useState(null);

  // Poll for live positions
  useEffect(() => {
    const interval = setInterval(async () => {
      const data = await fetch('/vehicles/positions');
      setBuses(data.positions);
    }, 8000); // Every 8 seconds
    return () => clearInterval(interval);
  }, []);

  // Load stops on mount
  useEffect(() => {
    fetch('/stops?limit=500').then(data => setStops(data));
  }, []);

  return (
    <MapView>
      {Object.values(buses).map(bus => (
        <BusMarker
          key={bus.vehicle_id}
          bus={bus}
          color={getOccupancyColor(bus.occupancy_level)}
          onPress={() => setSelectedBus(bus)}
        />
      ))}
      {stops.map(stop => (
        <StopMarker key={stop.id} stop={stop} />
      ))}
    </MapView>
  );
};
```

**Color coding for bus markers:**
```javascript
const getOccupancyColor = (level) => {
  switch (level) {
    case 0: return '#10B981'; // Green
    case 1: return '#F59E0B'; // Amber
    case 2: return '#EF4444'; // Red
    default: return '#94A3B8'; // Gray (unknown)
  }
};
```

---

### 11.4 Journey Planner Screen

```
┌─────────────────────────────────────┐
│ ← Plan Your Journey                 │
├─────────────────────────────────────┤
│                                     │
│  ┌─────────────────────────────┐    │
│  │ 📍 From: [Current Location] │    │  ← Auto-detect or search
│  └─────────────────────────────┘    │
│         ↕ (swap button)             │
│  ┌─────────────────────────────┐    │
│  │ 🎯 To: [Search destination] │    │
│  └─────────────────────────────┘    │
│                                     │
│  ┌─────────────────────────────┐    │
│  │      🔍 SEARCH BUSES        │    │
│  └─────────────────────────────┘    │
│                                     │
│  ── Recent Searches ──              │
│  📍 Merkato → Bole                  │
│  📍 Stadium → Meskel Square         │
│                                     │
│  ── Favorites ──                    │
│  ❤️ Home to Work                    │
│  ❤️ Home to University              │
│                                     │
└─────────────────────────────────────┘
```

**API Calls:**
1. `POST /search/journey` — on search submit
2. Navigate to Results Screen with response data

---

### 11.5 Journey Results Screen

```
┌─────────────────────────────────────┐
│ ← Merkato → Bole         [Map|List] │
├─────────────────────────────────────┤
│                                     │
│  ┌─ Route 101 ──────────────────┐   │
│  │ 🚌 ET-1234-AB                 │   │
│  │ 🟡 Medium  ⏱️ 6 min  📍 1.2km│   │
│  │ ─────────────────────────────│   │
│  │ 🚌 ET-5678-CD                 │   │
│  │ 🟢 Empty   ⏱️ 12 min 📍 3.5km│   │
│  └───────────────────────────────┘   │
│                                     │
│  ┌─ Route 205 ──────────────────┐   │
│  │ 🚌 ET-9012-EF                 │   │
│  │ 🔴 Crowded  ⏱️ 8 min  📍 2km │   │
│  └───────────────────────────────┘   │
│                                     │
└─────────────────────────────────────┘
```

**Card Design:**
```
┌─────────────────────────────────────┐
│ Route 101 — Merkato to Bole    ↗️   │  ← Tap to see route on map
│                                     │
│ ┌─────────────────────────────────┐ │
│ │ 🚌 ET-1234-AB                   │ │
│ │ ●━━━━━━━━━━━━━━━━━━━━━━━○       │ │  ← Progress bar
│ │ 🟡 Medium  •  ⏱️ 6 min  •  ♡   │ │
│ │ Speed: 32 km/h  •  📍 1.2 km   │ │
│ └─────────────────────────────────┘ │
│                                     │
│ ┌─────────────────────────────────┐ │
│ │ 🚌 ET-5678-CD                   │ │
│ │ ●━━━━━━━━━━○                   │ │
│ │ 🟢 Empty   •  ⏱️ 12 min •  ♡   │ │
│ │ Speed: 18 km/h  •  📍 3.5 km   │ │
│ └─────────────────────────────────┘ │
└─────────────────────────────────────┘
```

**Occupancy Badge Component:**
```javascript
const OccupancyBadge = ({ level }) => {
  const config = {
    0: { label: 'Empty', color: '#10B981', icon: '🟢', bg: 'rgba(16,185,129,0.15)' },
    1: { label: 'Medium', color: '#F59E0B', icon: '🟡', bg: 'rgba(245,158,11,0.15)' },
    2: { label: 'Crowded', color: '#EF4444', icon: '🔴', bg: 'rgba(239,68,68,0.15)' },
  };
  const c = config[level] || { label: 'Unknown', color: '#94A3B8', icon: '⚪', bg: 'rgba(148,163,184,0.15)' };

  return (
    <View style={{
      backgroundColor: c.bg,
      borderRadius: 8,
      paddingHorizontal: 10,
      paddingVertical: 4,
      flexDirection: 'row',
      alignItems: 'center',
    }}>
      <Text style={{ color: c.color, fontSize: 13, fontWeight: '600' }}>
        {c.icon} {c.label}
      </Text>
    </View>
  );
};
```

---

### 11.6 Bus Detail Screen

```
┌─────────────────────────────────────┐
│ ← Bus Details              ♡  🔔   │
├─────────────────────────────────────┤
│                                     │
│         ┌─────────┐                 │
│         │  🚌     │                 │
│         │ ET-1234 │                 │
│         └─────────┘                 │
│                                     │
│  ┌─────────────────────────────┐    │
│  │  🟡 Medium Crowd           │    │
│  │  👥 ~15 people detected     │    │
│  └─────────────────────────────┘    │
│                                     │
│  Route: 101 (Merkato → Bole)       │
│  Speed: 32.5 km/h                   │
│  ETA to destination: 6 min          │
│  Distance: 1.2 km                   │
│                                     │
│  ── Route Stops ──                  │
│  ● Merkato Terminal (start)        │
│  ● Merkato Market                  │
│  ○ ...                              │
│  ○ Bole Terminal (destination)     │
│                                     │
│  ┌─────────────────────────────┐    │
│  │      ⭐ Rate This Journey   │    │
│  └─────────────────────────────┘    │
│                                     │
└─────────────────────────────────────┘
```

---

### 11.7 Favorites Screen

```
┌─────────────────────────────────────┐
│ ❤️ Favorites                        │
├─────────────────────────────────────┤
│                                     │
│  ┌─────────────────────────────┐    │
│  │ ❤️ Home to Work             │    │
│  │ Route 101 • Merkato → Bole  │    │
│  │ [Search Buses]              │    │
│  └─────────────────────────────┘    │
│                                     │
│  ┌─────────────────────────────┐    │
│  │ ❤️ Home to University       │    │
│  │ Route 205 → Route 101       │    │
│  │ [Search Buses]              │    │
│  └─────────────────────────────┘    │
│                                     │
│         + Add Favorite              │
│                                     │
└─────────────────────────────────────┘
```

**API Calls:**
1. `GET /favorites/{user_id}` — on screen load
2. `POST /favorites` — on add favorite
3. `POST /search/journey` — on "Search Buses" tap

---

### 11.8 Rating Screen

```
┌─────────────────────────────────────┐
│ ⭐ Rate Your Journey                │
├─────────────────────────────────────┤
│                                     │
│  How was your ride on Route 101?    │
│                                     │
│        ☆  ☆  ☆  ☆  ☆              │  ← Tap to rate (1-5)
│                                     │
│  ┌─────────────────────────────┐    │
│  │ Share your experience...    │    │  ← Optional comment
│  │                             │    │
│  └─────────────────────────────┘    │
│                                     │
│  ┌─────────────────────────────┐    │
│  │       SUBMIT RATING         │    │
│  └─────────────────────────────┘    │
│                                     │
└─────────────────────────────────────┘
```

**API Calls:**
1. `POST /ratings` — on submit

---

### 11.9 Profile Screen

```
┌─────────────────────────────────────┐
│ 👤 Profile                          │
├─────────────────────────────────────┤
│                                     │
│         ┌─────────┐                 │
│         │  👤     │                 │
│         │  Avatar │                 │
│         └─────────┘                 │
│         johndoe                     │
│         john@example.com            │
│                                     │
│  ┌─────────────────────────────┐    │
│  │ 🔔 Notification Settings  → │    │
│  └─────────────────────────────┘    │
│  ┌─────────────────────────────┐    │
│  │ ❤️ My Favorites           → │    │
│  └─────────────────────────────┘    │
│  ┌─────────────────────────────┐    │
│  │ ⭐ My Ratings             → │    │
│  └─────────────────────────────┘    │
│  ┌─────────────────────────────┐    │
│  │ ⚙️ Settings               → │    │
│  └─────────────────────────────┘    │
│  ┌─────────────────────────────┐    │
│  │ 🚪 Logout                   │    │
│  └─────────────────────────────┘    │
│                                     │
└─────────────────────────────────────┘
```

---

### 11.10 Notification Settings Screen

```
┌─────────────────────────────────────┐
│ ← Notification Settings             │
├─────────────────────────────────────┤
│                                     │
│  ┌─────────────────────────────┐    │
│  │ Route 101 — Home to Work    │    │
│  │ 🔔 Alert 10 min before      │    │
│  │ [Edit] [Delete]             │    │
│  └─────────────────────────────┘    │
│                                     │
│  ┌─────────────────────────────┐    │
│  │ + Add Notification Alert     │    │
│  └─────────────────────────────┘    │
│                                     │
└─────────────────────────────────────┘
```

**API Calls:**
1. `GET /notifications/settings/{user_id}` — on load
2. `POST /notifications/settings` — on add/edit

---

## 12. State Management & Async Patterns

### 12.1 Recommended Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Screens    │────►│   State     │────►│   API       │
│   (UI)       │◄────│   (Store)   │◄────│   Layer     │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
                    ┌──────┴──────┐
                    │  Secure     │
                    │  Storage    │
                    │  (Tokens)   │
                    └─────────────┘
```

### 12.2 API Client Setup

```javascript
// api/client.js
const BASE_URL = 'https://bustrack.dpdns.org/api/v1';

class ApiClient {
  constructor() {
    this.baseUrl = BASE_URL;
  }

  async request(endpoint, options = {}) {
    const token = await SecureStore.getItemAsync('auth_token');
    
    const headers = {
      'Content-Type': 'application/json',
      ...(token && { 'Authorization': `Bearer ${token}` }),
      ...options.headers,
    };

    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      ...options,
      headers,
    });

    if (response.status === 401) {
      // Try to refresh token
      const refreshed = await this.refreshToken();
      if (refreshed) {
        // Retry the original request
        return this.request(endpoint, options);
      } else {
        // Redirect to login
        throw new AuthError('Session expired');
      }
    }

    if (!response.ok) {
      const error = await response.json();
      throw new ApiError(error.detail, response.status);
    }

    return response.json();
  }

  async refreshToken() {
    try {
      const token = await SecureStore.getItemAsync('auth_token');
      const response = await fetch(`${this.baseUrl}/auth/refresh`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
      });
      if (response.ok) {
        const data = await response.json();
        await SecureStore.setItemAsync('auth_token', data.access_token);
        return true;
      }
      return false;
    } catch {
      return false;
    }
  }

  // Auth
  login(credentials) {
    return this.request('/auth/login', {
      method: 'POST',
      body: JSON.stringify(credentials),
    });
  }

  googleAuth(idToken) {
    return this.request('/auth/google', {
      method: 'POST',
      body: JSON.stringify({ id_token: idToken }),
    });
  }

  register(data) {
    return this.request('/auth/register', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // Search
  searchJourney(params) {
    return this.request('/search/journey', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  }

  // Vehicles
  getLivePositions() {
    return this.request('/vehicles/positions');
  }

  // Routes
  getRoutes() {
    return this.request('/routes');
  }

  getRouteDetail(id) {
    return this.request(`/routes/${id}`);
  }

  // Stops
  getStops() {
    return this.request('/stops');
  }

  // Favorites
  getFavorites(userId) {
    return this.request(`/favorites/${userId}`);
  }

  addFavorite(data) {
    return this.request('/favorites', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // Ratings
  addRating(data) {
    return this.request('/ratings', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // Notifications
  getNotificationSettings(userId) {
    return this.request(`/notifications/settings/${userId}`);
  }

  setNotification(data) {
    return this.request('/notifications/settings', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }
}

export const api = new ApiClient();
```

### 12.3 Polling Strategy for Live Data

```javascript
// hooks/useLivePositions.js
import { useState, useEffect, useRef } from 'react';
import { api } from '../api/client';

const POLL_INTERVAL = 8000; // 8 seconds
const STALE_THRESHOLD = 180000; // 3 minutes

export function useLivePositions() {
  const [positions, setPositions] = useState({});
  const [isLive, setIsLive] = useState(true);
  const [lastUpdate, setLastUpdate] = useState(null);
  const intervalRef = useRef(null);

  const fetchPositions = async () => {
    try {
      const data = await api.getLivePositions();
      setPositions(data.positions);
      setLastUpdate(Date.now());
      
      // Check if data is stale
      const serverAge = (Date.now() / 1000) - data.timestamp;
      setIsLive(serverAge < STALE_THRESHOLD);
    } catch (error) {
      console.error('Failed to fetch positions:', error);
    }
  };

  useEffect(() => {
    fetchPositions(); // Initial fetch
    intervalRef.current = setInterval(fetchPositions, POLL_INTERVAL);
    return () => clearInterval(intervalRef.current);
  }, []);

  return { positions, isLive, lastUpdate, refresh: fetchPositions };
}
```

### 12.4 WebSocket Hook (for Admin App)

```javascript
// hooks/useWebSocket.js
import { useState, useEffect, useRef, useCallback } from 'react';

export function useWebSocket(token) {
  const [connected, setConnected] = useState(false);
  const [messages, setMessages] = useState([]);
  const [error, setError] = useState(null);
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const reconnectDelayRef = useRef(1000);

  const connect = useCallback(() => {
    if (!token) return;

    const ws = new WebSocket(
      `wss://bustrack.dpdns.org/api/v1/ws/live?token=${token}`
    );

    ws.onopen = () => {
      setConnected(true);
      setError(null);
      reconnectDelayRef.current = 1000; // Reset backoff
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setMessages(prev => [...prev, data]);
    };

    ws.onerror = (err) => {
      setError('Connection error');
    };

    ws.onclose = () => {
      setConnected(false);
      // Auto-reconnect with exponential backoff
      reconnectTimeoutRef.current = setTimeout(() => {
        reconnectDelayRef.current = Math.min(reconnectDelayRef.current * 2, 60000);
        connect();
      }, reconnectDelayRef.current);
    };

    wsRef.current = ws;
  }, [token]);

  const sendPing = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'ping' }));
    }
  }, []);

  const disconnect = useCallback(() => {
    clearTimeout(reconnectTimeoutRef.current);
    wsRef.current?.close();
  }, []);

  useEffect(() => {
    connect();
    return disconnect;
  }, [connect, disconnect]);

  // Send ping every 30s to keep alive
  useEffect(() => {
    const pingInterval = setInterval(sendPing, 30000);
    return () => clearInterval(pingInterval);
  }, [sendPing]);

  return { connected, messages, error, sendPing, disconnect };
}
```

---

## 13. Push Notifications (FCM)

### Setup

The backend supports **Firebase Cloud Messaging (FCM)** for push notifications. The `FCM_SERVER_KEY` is configured on the backend.

### Notification Types

| Type | Trigger | Payload |
|------|---------|---------|
| **Proximity Alert** | Bus is N minutes away from user's stop (based on `lead_time_minutes` setting) | `{ "type": "proximity", "title": "Bus arriving soon", "body": "Route 101 is 5 min away from Merkato Terminal" }` |
| **Crowd Update** | Bus crowd level changes | `{ "type": "crowd", "title": "Crowd update", "body": "Route 101 is now crowded" }` |

### Implementation

```javascript
// notifications/setup.js
import messaging from '@react-native-firebase/messaging';

async function requestNotificationPermission() {
  const authStatus = await messaging().requestPermission();
  const enabled =
    authStatus === messaging.AuthorizationStatus.AUTHORIZED ||
    authStatus === messaging.AuthorizationStatus.PROVISIONAL;

  if (enabled) {
    const token = await messaging().getToken();
    // Send FCM token to backend (extend API if needed)
    console.log('FCM Token:', token);
  }
}

// Handle foreground messages
messaging().onMessage(async remoteMessage => {
  showLocalNotification(remoteMessage);
});

// Handle background/quit messages
messaging().setBackgroundMessageHandler(async remoteMessage => {
  console.log('Background message:', remoteMessage);
});
```

---

## 14. Testing the API

### Health Check

```bash
curl https://bustrack.dpdns.org/health
```

### Full Auth Flow Test

```bash
# 1. Register
curl -X POST https://bustrack.dpdns.org/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","email":"test@example.com","password":"testpass123"}'

# 2. Login
curl -X POST https://bustrack.dpdns.org/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"testpass123"}'

# 3. Get Profile (use token from step 2)
curl https://bustrack.dpdns.org/api/v1/auth/me \
  -H "Authorization: Bearer <token>"

# 4. Search Journey
curl -X POST https://bustrack.dpdns.org/api/v1/search/journey \
  -H "Content-Type: application/json" \
  -d '{"start_query":"Merkato","end_query":"Bole"}'

# 5. Get Live Positions
curl https://bustrack.dpdns.org/api/v1/vehicles/positions

# 6. List Routes
curl https://bustrack.dpdns.org/api/v1/routes

# 7. List Stops
curl https://bustrack.dpdns.org/api/v1/stops
```

---

## Quick Reference Card

```
┌──────────────────────────────────────────────────────────────┐
│                    BUS TRACK API QUICK REF                   │
├──────────────────────────────────────────────────────────────┤
│ BASE URL:  https://bustrack.dpdns.org/api/v1                │
│ AUTH:      Bearer JWT (24h expiry, refresh via /auth/refresh)│
│ FORMAT:    JSON                                              │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  AUTH                                                        │
│  POST   /auth/register        Sign up (email+password)       │
│  POST   /auth/login           Login → get JWT                │
│  POST   /auth/google          Google OAuth → get JWT         │
│  GET    /auth/me              Current user profile            │
│  POST   /auth/refresh         Refresh JWT                    │
│  POST   /auth/verify-email    Verify email with token        │
│  POST   /auth/forgot-password Request password reset         │
│  POST   /auth/reset-password  Reset password with token      │
│                                                              │
│  SEARCH (Core Feature)                                       │
│  POST   /search/journey       Search buses between locations │
│  POST   /search/point-to-point  Search between known stops   │
│                                                              │
│  VEHICLES                                                    │
│  GET    /vehicles/positions   All live bus positions ⭐      │
│  GET    /vehicles/positions/{id}  Single bus position        │
│  GET    /vehicles             List all vehicles              │
│  GET    /vehicles/{id}        Vehicle details                │
│                                                              │
│  ROUTES & STOPS                                              │
│  GET    /routes               List all routes                │
│  GET    /routes/{id}          Route with ordered stops       │
│  GET    /stops                List all stops                 │
│  GET    /stops/{id}           Stop details                   │
│                                                              │
│  SOCIAL                                                      │
│  POST   /favorites            Save favorite route            │
│  GET    /favorites/{user_id}  List user favorites            │
│  POST   /ratings              Rate a journey (1-5)          │
│  GET    /ratings/{assignment_id}  List ratings               │
│                                                              │
│  NOTIFICATIONS                                               │
│  POST   /notifications/settings  Set proximity alert         │
│  GET    /notifications/settings/{user_id}  Get settings      │
│                                                              │
│  REAL-TIME                                                   │
│  WSS    /ws/live?token=<jwt>  WebSocket (admin only)        │
│                                                              │
│  OCCUPANCY LEVELS:  0=Empty 🟢  1=Medium 🟡  2=Crowded 🔴   │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## Summary for AI Agent

**If you are an AI agent building this mobile app, here's what to build:**

1. **Splash Screen** → Check auth token → Route to Login or Home
2. **Auth Screens** → Login, Register, Google Sign-In, Email Verification, Forgot/Reset Password
3. **Home Screen** → Full-screen map with live bus markers (poll `/vehicles/positions` every 8s), color-coded by occupancy
4. **Journey Planner** → "From" and "To" inputs with autocomplete → `POST /search/journey` → Show results
5. **Results Screen** → List of routes with buses, ETA, occupancy badges, favorite buttons
6. **Bus Detail Screen** → Selected bus info, crowd level, route stops, rate button
7. **Favorites Screen** → Saved routes, quick search
8. **Rating Screen** → Star rating + comment
9. **Profile Screen** → User info, notification settings, logout
10. **Notification Settings** → Set proximity alerts per route
11. **Dark theme by default** with the specified color palette
12. **Secure token storage** with auto-refresh
13. **Error handling** for all API errors with user-friendly messages
14. **Loading states** with skeleton screens
15. **Offline detection** with retry prompts

**Design:** Futuristic dark theme, Electric Blue (#2563EB) primary, Neon Cyan (#06B6D4) accents, rounded corners (12-16px), smooth animations, occupancy color coding (Green/Amber/Red).

---

*This document covers the complete BusTrack API v1.0.0. For questions or updates, refer to the backend repository.*
