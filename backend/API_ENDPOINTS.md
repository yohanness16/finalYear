# BusTrack API Endpoint Reference

Base URL: `/api/v1`

## Auth

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/auth/register` | None | Passenger signup |
| POST | `/auth/login` | None | Email/password login |
| POST | `/auth/google` | None | Google OAuth login |
| GET | `/auth/me` | JWT | Get current user profile |
| PATCH | `/auth/me` | JWT | Update profile (username/email) |
| POST | `/auth/refresh` | JWT | Refresh token |
| POST | `/auth/change-password` | JWT | Change password |
| POST | `/auth/verify-email` | None | Verify with token from email |
| POST | `/auth/resend-verification` | None | Resend verification email |
| POST | `/auth/forgot-password` | None | Request password reset email |
| POST | `/auth/reset-password` | None | Reset password with token |
| POST | `/auth/driver-login` | None | Driver login (needs bus token) |
| POST | `/auth/driver-logout` | JWT | End driver session |
| POST | `/auth/bus-dashboard/login` | None | Bus dashboard device login |

## Pairing (Bus Dashboard Setup)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/admin/vehicles/{id}/generate-pairing-code` | Admin | Generate 5-min pairing code |
| POST | `/pair/verify` | None | Verify code + set password |
| POST | `/admin/vehicles/{id}/unpair` | Admin | Remove dashboard pairing |

## Search

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/search/point-to-point` | None | Routes between two stops |
| POST | `/search/journey` | None | Routes with geocoding |

## Favorites & Ratings

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/favorites` | None | Add favorite |
| GET | `/favorites/{user_id}` | None | List favorites |
| DELETE | `/favorites/{favorite_id}` | JWT | Remove favorite |
| POST | `/ratings` | None | Add rating |
| GET | `/ratings/{assignment_id}` | None | List ratings |

## Notifications

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/notifications/settings` | None | Set notification |
| GET | `/notifications/settings/{user_id}` | None | List notification settings |
| POST | `/notifications/register-token` | None | Register FCM token |

## Vehicles

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/vehicles/positions` | None | All live positions |
| GET | `/vehicles/positions/{vehicle_id}` | None | Single vehicle position |

## Admin

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/admin/vehicles/{id}/generate-pairing-code` | Admin | Pair dashboard |
| POST | `/admin/vehicles/{id}/unpair` | Admin | Unpair dashboard |
| All other admin endpoints... | | | |
