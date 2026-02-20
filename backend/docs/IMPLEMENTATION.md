# Implementation Guide

## Setup

1. Copy `.env.example` to `.env`
2. Create first admin user (run in Python after migrations):
   ```python
   from app.db.session import AsyncSessionLocal
   from app.crud.user import create_user
   from passlib.context import CryptContext
   pwd = CryptContext(schemes=["bcrypt"]).hash("admin123")
   async with AsyncSessionLocal() as db:
       await create_user(db, "admin", "admin@example.com", pwd, "admin")
       await db.commit()
   ```
2. Set `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`
3. For Google OAuth: set `GOOGLE_CLIENT_ID`
4. Run `docker-compose up -d`
5. Run `alembic upgrade head`
6. Start: `uvicorn app.main:app --reload`

## Auth

### Obtain JWT

```bash
# Register (passenger)
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"user1","email":"user@test.com","password":"secret123"}'

# Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"user1","password":"secret123"}'
```

### Use JWT in Headers

```
Authorization: Bearer <access_token>
```

### Admin Create Driver/Admin

First create an admin user manually in DB (role='admin'), then:

```bash
curl -X POST http://localhost:8000/api/v1/admin/users \
  -H "Authorization: Bearer <admin_jwt>" \
  -H "Content-Type: application/json" \
  -d '{"username":"driver1","email":"d@test.com","password":"pass123","role":"driver"}'
```

## ML

- Train: `POST /admin/ml/train` (admin JWT required)
- Model saved to `app/services/delay_predictor.joblib`
- Status: `GET /admin/ml/status`

## Cleanup

- Run: `POST /admin/cleanup` (admin JWT)
- Retention: `RAW_TELEMETRY_RETENTION_DAYS` (default 30), `TRIP_HISTORY_RETENTION_DAYS` (default 365)

## Admin Dashboard

- Summary: `GET /admin/dashboard/summary`
- Assignments over time: `GET /admin/dashboard/assignments-over-time?days=7`
- Occupancy: `GET /admin/dashboard/occupancy-distribution`
- ETA accuracy: `GET /admin/dashboard/eta-accuracy`
- Route usage: `GET /admin/dashboard/route-usage?days=30`
- Telemetry volume: `GET /admin/dashboard/telemetry-volume`
