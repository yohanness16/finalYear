# BusTrack — System Analysis & Plans
**Date:** 2026-05-26
**Analyst:** OWL (automated analysis)

---

## What This Folder Contains

This folder is the result of a comprehensive analysis of the **BusTrack** system — comparing the backend (FastAPI/Python) against the mobile app (Flutter/Dart) and the system's stated goals (from thesis, docs, and README).

### Files

| File | Purpose |
|------|---------|
| **`DATA_FLOW_MATRIX.md`** | ⭐ **Start here.** Complete field-by-field comparison of every API endpoint. Shows exactly what the backend sends vs what the mobile app expects. 52 fields checked across 15 endpoints. |
| **`BACKEND_DATA_AUDIT.md`** | Deep audit of the backend: what it sends, what it should send, bugs found, and data that should be cleaned up. |
| **`MOBILE_APP_GAP_ANALYSIS.md`** | Deep audit of the mobile app: what it expects, what's missing, bugs, and features not yet implemented. |
| **`BACKEND_REMAINING_WORK.md`** | Prioritized implementation plan for the backend. 10 tasks, ~4 hours total. |
| **`MOBILE_REMAINING_WORK.md`** | Prioritized implementation plan for the mobile app. 14 tasks, ~4-12 hours depending on scope. |

---

## Key Findings

### 🔴 Critical Issues (5)

1. **`bus_plate` missing from point-to-point ETA response** — Mobile always shows "No active bus" even when buses exist
2. **`PATCH /auth/me` not implemented** — Profile update fails silently through 3 fallback endpoints
3. **`POST /auth/change-password` not implemented** — Password change fails silently
4. **`DELETE /favorites/{id}` not implemented** — Remove favorite shows "pending backend support"
5. **`POST /notifications/register-token` not implemented** — FCM token registration fails

### 🟡 Medium Issues (6)

6. `is_verified` and `google_id` missing from `UserResponse` schema
7. `last_updated` (ISO 8601) missing from `VehiclePosition` — mobile always null
8. `density_level` is redundant with `occupancy_level` in vehicle positions
9. WebSocket imported in mobile but never used (15s polling instead)
10. `inference_ms` dropped from WebSocket CV broadcast
11. `human_count` redundant with `people_count` in CV pipeline

### 🟢 Low Issues (5)

12. `eta_minutes` check in mobile is dead code (backend sends `eta_seconds`)
13. `isTerminal` and `peakMultiplier` parsed but never displayed
14. `web_socket_channel` dependency unused in mobile
15. Positions envelope keyed by `vehicle_id` instead of `plate_number` (works as-is)

---

## Recommended Execution Order

### Phase 1: Backend Critical Fixes (~2 hours)
1. Add `PATCH /auth/me` endpoint
2. Add `POST /auth/change-password` endpoint
3. Add `DELETE /favorites/{id}` endpoint
4. Add `POST /notifications/register-token` endpoint
5. Add `bus_plate` to point-to-point ETA response

### Phase 2: Mobile Critical Fixes (~1 hour)
6. Remove fallback chains for profile/password/FCM
7. Wire up remove favorite button
8. Fix `bus_plate` display in journey results

### Phase 3: Backend Cleanup (~1 hour)
9. Add `is_verified`, `google_id` to `UserResponse`
10. Add `last_updated` to `VehiclePosition`
11. Remove `density_level` redundancy
12. Remove `human_count` from CV pipeline
13. Add `inference_ms` to WebSocket CV broadcast

### Phase 4: Mobile Enhancements (~4 hours)
14. Implement email verification flow
15. Implement password reset flow
16. Show bus speed in journey results
17. Add ML/heuristic ETA indicator
18. Display bus type in bottom sheet
19. Display terminal badge on stops
20. Remove dead code

### Phase 5: Real-Time Updates (~4+ hours)
21. Add passenger-facing WebSocket endpoint on backend
22. Implement WebSocket in mobile app
23. Add crowd density detail to REST endpoint
24. Show crowd density in mobile UI

---

## System Architecture Summary

```
┌─────────────┐     HTTP/REST      ┌──────────────┐
│   Flutter   │◄──────────────────►│   FastAPI    │
│ Mobile App  │   (polling 15s)    │   Backend    │
│  (Passenger)│                    │   (Python)   │
└─────────────┘                    └──────┬───────┘
                                          │
┌─────────────┐     WebSocket      ┌──────┴───────┐
│   Next.js   │◄──────────────────►│   Redis      │
│   Admin     │   (live stream)    │  (Upstash)   │
│  Dashboard  │                    └──────┬───────┘
└─────────────┘                           │
                                   ┌──────┴───────┐
┌─────────────┐     HTTP/REST      │  PostgreSQL  │
│   Next.js   │◄──────────────────►│  + PostGIS   │
│    Bus      │                    └──────────────┘
│  Dashboard  │
└─────────────┘
       ▲
       │ HTTP POST (telemetry)
       │
┌─────────────┐
│  IoT Device │
│ SIM7600 +   │
│ ESP32-CAM   │
└─────────────┘
```
