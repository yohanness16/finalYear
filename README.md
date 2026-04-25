/# Smart Transport Tracking System - Complete Implementation

## 🏗️ Project Overview
Full-stack real-time public transport tracking system for Addis Ababa with per-bus GPS tracking, route validation, and admin dashboard.

## 🚀 Architecture

```
Frontend (Next.js Admin Dashboard)
    ↓ HTTPS
Backend (FastAPI REST API)
    ↓ PostgreSQL + Redis
Database & Cache Layer
    ↓
Hardware (SIM7600 GPS/GSM + ESP32-CAM)
```

## 📋 Backend Components

### API Endpoints
- `POST /api/v1/vehicles` - Register new bus (SIM7600 IMEI)
- `GET /api/v1/vehicles` - List all buses
- `GET /api/v1/vehicles/positions` - Live GPS positions
- `POST /api/v1/telemetry` - Receive GPS telemetry
- `GET /api/v1/routes` - List routes
- `POST /api/v1/routes` - Create route with stops

### Models
- **Vehicle**: Bus with device_id (SIM7600 IMEI), route assignment
- **Stop**: GPS coordinates + operational data
- **Route**: Ordered sequence of stops
- **RawTelemetry**: Bronze layer GPS data

### GPS Validation
- Haversine distance calculation
- 500m max jump threshold (outlier rejection)
- Per-bus context validation
- Fallback to average position

## 🎨 Admin Dashboard (Next.js)

### Features
- **Live Map**: Real-time bus positions with Leaflet
- **KPI Cards**: Active trips, vehicles, routes, users, telemetry
- **Charts**: Assignments, occupancy, telemetry, route usage, ETA accuracy
- **Route Management**: Create/edit routes with stops
- **Vehicle Management**: Register/monitor buses
- **User Management**: Admin/driver accounts

### Navigation
- Dashboard (Overview + Live Map)
- Analytics
- Vehicles
- Routes & Stops
- Assignments
- Users
- Settings & ML

## 🌍 Addis Ababa Routes

### Route 121: Kality ↔ Meskel Square
- Kality Bus Station (9.0167°N, 38.7667°E) - Terminal
- Bole Road (9.0200°N, 38.7700°E)
- Africa Avenue (9.0250°N, 38.7750°E)
- Meskel Square (9.0300°N, 38.7800°E) - Terminal

### Route 122: Akaki ↔ Entoto Hills
- Akaki Terminal (9.0000°N, 38.7500°E) - Terminal
- Bole International Approach (9.0120°N, 38.7600°E)
- Entoto Hills Base (9.0450°N, 38.7800°E)
- Entoto Hills Summit (9.0500°N, 38.7850°E) - Terminal

### Route 150: Gulele ↔ Saris
- Gulele Square (9.0380°N, 38.7450°E) - Terminal
- Wollo Sefer (9.0400°N, 38.7550°E)
- Saris Market (9.0480°N, 38.7600°E) - Terminal

## 🛠️ Setup Instructions

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Database
```bash
alembic upgrade head  # OR npx prisma migrate dev
```

### Redis
```bash
redis-server
```

### Frontend
```bash
cd bustrack-admin
npm install
npm run dev
```

## 🔑 Environment Variables
```
DATABASE_URL=postgresql://user:pass@localhost:5432/finalyear
REDIS_URL=redis://127.0.0.1:6379
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## 🧪 Testing
```bash
# Backend tests
python -m pytest tests/ -v

# Specific GPS tests
python -m pytest tests/test_gps_validation.py -v
```

Simulation stack (setup scripts, admin map, telemetry): see [docs/SIMULATION_AND_ADMIN_MAP.md](docs/SIMULATION_AND_ADMIN_MAP.md).

## ✅ Production Ready Features
- ✅ Per-bus GPS tracking (SIM7600 IMEI)
- ✅ Real-time map visualization
- ✅ GPS outlier detection & rejection
- ✅ On-route validation
- ✅ Redis caching for performance
- ✅ Database migrations
- ✅ Comprehensive test coverage
- ✅ Protected admin endpoints
- ✅ Responsive dashboard UI
- ✅ 9 full API endpoints

## 📊 Performance
- GPS updates: 1 point/5 seconds per bus
- API rate limit: 300/minute per device
- Cache TTL: 5 min (positions), 1 hr (stops)
- Dashboard auto-refresh: 30s

## 🎯 Hardware Integration
- **SIM7600 GPS/GSM**: Sends lat/lon via HTTP POST
- **ESP32-CAM**: Sends pixel count for occupancy detection
- **API Format**: JSON telemetry ingestion

## 📝 License
MIT