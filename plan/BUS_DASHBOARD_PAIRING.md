# Bus Dashboard Pairing & Driver Login — Complete Design & Plan
**Date:** 2026-05-26

---

## Part A: Bus Dashboard Pairing (One-Time Setup Key)

### The Problem
Currently, the bus dashboard login (`POST /auth/bus-dashboard/login`) requires:
- `vehicle_id`, `device_id`, `password`

This means every bus dashboard device needs a pre-configured password stored on the vehicle model. There's no way for an admin to quickly pair a new device. The `bus_token` JWT flow exists for driver login but not for initial device pairing.

### The Solution: Admin-Generated Pairing Code

**Flow:**
1. Admin goes to Vehicles page → selects a bus → clicks "Generate Pairing Code"
2. Backend creates a **one-time pairing code** (e.g., `BUS-A7X9-K3M2`) stored in Redis with a **5-minute TTL**
3. Backend returns the code to the admin, who displays it on screen
4. On the bus dashboard device (physical tablet), the technician enters:
   - The **pairing code**
   - A **new password** they want to set for this dashboard
5. Backend verifies the code, attaches the vehicle to the dashboard session, hashes and stores the password, marks vehicle as "paired"
6. Code is consumed (deleted) — cannot be reused
7. After pairing, the driver can log in daily with `device_id` + `password`

### Database Changes

#### No new columns needed on `vehicles` table
The `dashboard_password_hash` field (already referenced in `auth.py:237` via `getattr`) is used. We just need to make it a real column instead of `getattr`.

**Actual fix:** The `vehicles` table currently has NO `dashboard_password_hash` column. The code at `auth.py:237` does `getattr(vehicle, "dashboard_password_hash", None)` — which will always return None since the column doesn't exist. This means the bus dashboard login is **completely broken right now** — no vehicle can ever log in because the password check always fails.

### Backend Implementation

#### DB Migration: Add `dashboard_password_hash` to vehicles

```sql
ALTER TABLE vehicles ADD COLUMN dashboard_password_hash VARCHAR(255) NULL;
```

#### New endpoint: `POST /admin/vehicles/{vehicle_id}/generate-pairing-code`

**Where:** New file or add to `app/api/v1/admin_dashboard.py` (new subsection) or create `app/api/v1/pairing.py`

**Full implementation:**

```python
"""Bus dashboard pairing endpoints."""
import secrets
import string

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import RequireAdmin
from app.crud import vehicle as crud_vehicle
from app.db.session import get_db
from app.utils.redis_client import get_redis

router = APIRouter()


PAIRING_CODE_TTL = 300  # 5 minutes
PAIRING_CODE_LENGTH = 12


def _generate_code() -> str:
    """Generate a human-friendly pairing code: BUS-XXXX-XXXX."""
    alphabet = string.ascii_uppercase + string.digits
    # Exclude confusing characters: O/0, I/1/L
    alphabet = alphabet.replace("O", "").replace("0", "").replace("I", "").replace("L", "")
    segment = lambda n: "".join(secrets.choice(alphabet) for _ in range(n))
    return f"BUS-{segment(4)}-{segment(4)}"


class PairingCodeResponse(BaseModel):
    code: str
    vehicle_id: int
    plate_number: str
    device_id: str
    expires_in_seconds: int = PAIRING_CODE_TTL
    message: str


class PairVerifyRequest(BaseModel):
    code: str
    password: str = Field(..., min_length=6, max_length=100)


class PairVerifyResponse(BaseModel):
    status: str
    vehicle_id: int
    device_id: str
    message: str


@router.post("/admin/vehicles/{vehicle_id}/generate-pairing-code", response_model=PairingCodeResponse)
async def generate_pairing_code(
    vehicle_id: int,
    current_user: RequireAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Generate a one-time 5-minute pairing code for a bus dashboard device.

    Admin calls this from the Vehicles UI. The code is shown on screen
    for the technician to enter on the physical bus dashboard tablet.
    """
    vehicle = await crud_vehicle.get_vehicle_by_id(db, vehicle_id)
    if not vehicle:
        raise HTTPException(404, "Vehicle not found")

    # If already paired, reject — admin must unpair first
    if vehicle.dashboard_password_hash:
        raise HTTPException(
            400,
            "This bus dashboard is already paired. Unpair first to generate a new code."
        )

    code = _generate_code()
    redis = await get_redis()

    # Store code → vehicle_id mapping in Redis with TTL
    redis_key = f"pairing_code:{code}"
    await redis.set(
        redis_key,
        str(vehicle_id),
        ex=PAIRING_CODE_TTL,
    )

    return PairingCodeResponse(
        code=code,
        vehicle_id=vehicle.id,
        plate_number=vehicle.plate_number,
        device_id=vehicle.device_id,
        expires_in_seconds=PAIRING_CODE_TTL,
        message=f"Code expires in 5 minutes. Enter this code on the bus dashboard tablet.",
    )


@router.post("/pair/verify", response_model=PairVerifyResponse)
async def verify_pairing_code(
    body: PairVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verify a pairing code and set the bus dashboard password.

    Called from the physical bus dashboard device. One-time use.
    """
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__ident="2b")

    redis = await get_redis()
    redis_key = f"pairing_code:{body.code}"

    # Get and immediately delete (one-time use)
    vehicle_id_str = await redis.get(redis_key)
    if not vehicle_id_str:
        raise HTTPException(400, "Invalid or expired pairing code")

    await redis.delete(redis_key)

    vehicle = await crud_vehicle.get_vehicle_by_id(db, int(vehicle_id_str))
    if not vehicle:
        raise HTTPException(404, "Vehicle not found")

    if vehicle.dashboard_password_hash:
        raise HTTPException(400, "This bus dashboard is already paired")

    # Store hashed password
    from app.models.vehicle import Vehicle
    vehicle.dashboard_password_hash = pwd_context.hash(body.password)
    await db.flush()

    return PairVerifyResponse(
        status="paired",
        vehicle_id=vehicle.id,
        device_id=vehicle.device_id,
        message="Pairing complete. The dashboard can now be used. Drivers can log in with their credentials.",
    )


@router.post("/admin/vehicles/{vehicle_id}/unpair")
async def unpair_dashboard(
    vehicle_id: int,
    current_user: RequireAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Remove the dashboard password so a new pairing code can be generated."""
    vehicle = await crud_vehicle.get_vehicle_by_id(db, vehicle_id)
    if not vehicle:
        raise HTTPException(404, "Vehicle not found")

    vehicle.dashboard_password_hash = None
    await db.flush()

    return {"status": "unpaired", "vehicle_id": vehicle.id}
```

### Existing Login Flow After Pairing

Once paired, the existing `POST /auth/bus-dashboard/login` works as the **daily driver login**:

1. Driver opens the bus dashboard tablet
2. Enters `vehicle_id`, `device_id`, `password` (the password set during pairing)
3. Backend verifies against the stored `dashboard_password_hash`
4. Returns a short-lived JWT token
5. Token is used for subsequent API calls during the shift

**No change needed to the existing login endpoint** — it works correctly once the password column is populated via pairing.

### Frontend (Admin Dashboard) — New UI

**File:** `bustrack-admin/src/app/vehicles/page.tsx`

Add a "Generate Pairing Code" button to each vehicle row:

```tsx
// In the vehicles table actions column:
<Button
  variant="outline"
  size="sm"
  disabled={vehicle.dashboard_password_hash !== null}
  onClick={() => handleGenerateCode(vehicle.id)}
>
  {vehicle.dashboard_password_hash ? "Paired" : "Pair Device"}
</Button>

// Modal that shows after code generation:
{
  pairingCode && (
    <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-4">
      <p className="text-sm font-mono text-center text-2xl tracking-widest font-bold">
        {pairingCode.code}
      </p>
      <p className="text-xs text-center text-green-600 mt-2">
        Expires in 5 minutes. Enter this on the bus dashboard tablet.
      </p>
      <Button
        variant="destructive"
        size="sm"
        className="mt-3 w-full"
        onClick={() => handleUnpair(pairingCode.vehicle_id)}
      >
        Unpair Device
      </Button>
    </div>
  )
}
```

### Frontend (Bus Dashboard Device) — Pairing Screen

The bus dashboard app (physical tablet) needs a **pairing screen** before login:

1. **Unpaired state:** Show "Enter Pairing Code" screen
   - Input field for the `BUS-XXXX-XXXX` code
   - Input field for the new password (set once, used daily)
   - "Pair" button → calls `POST /pair/verify`

2. **Paired state:** Show the normal login screen
   - `device_id` + `password` → calls `POST /auth/bus-dashboard/login`

### Summary of Backend Changes for Pairing

| File | Change |
|------|--------|
| `app/models/vehicle.py` | Add `dashboard_password_hash` column |
| Alembic migration | Add column to DB |
| `app/api/v1/pairing.py` (NEW) | 3 endpoints: generate, verify, unpair |
| `app/api/v1/__init__.py` | Register the new router |
| **Total effort** | **~1 hour** |

---

## Part B: Show Only Searched Buses on Mobile Map

### The Problem
The mobile app's home screen map calls `GET /vehicles/positions` and draws **every bus in the entire system**. A passenger in Megenagna sees buses in Bole, Merkato, Saris — completely irrelevant.

### The Requirement
- **Before search:** Show NO buses (or a search prompt)
- **After search (point-to-point):** Show only buses whose `route_id` matches a route serving the searched path
- **Search context persists** across tab switches and has a 15-minute TTL

### Architecture

```
User searches: Stop A → Stop B
    │
    ▼
POST /search/point-to-point  ←  backend enriches with bus data
    │                             (FIX 2.1 from BACKEND_FIXES.md)
    ▼
Response includes: route_number + etas + buses[{vehicle_id, plate, route_id, ...}]
    │
    ▼
Mobile: stores route_ids from the response
    │
    ▼
Home map: filters BusTracker data to only show buses where bus.routeId ∈ searchedRouteIds
    │
    ▼
TTL expires after 15 min → clear search context → map shows search prompt again
```

### Changes Needed

#### 1. Backend — Already covered in FIX 2.1 of BACKEND_FIXES.md

The `POST /search/point-to-point` endpoint needs to:
- Fetch live positions via `crud_vehicle.get_live_positions(db)`
- For each matched route, find buses with matching `route_id`
- Return a `buses` array in the response

The `estimate_route_stop_eta_payloads()` needs `plate_number` and `vehicle_id` added to the Redis ETA hash so subsequent reads include bus identity.

#### 2. Mobile — New Provider: `ActiveSearch`

**New file:** `client_app/lib/features/home/domain/models/active_search.dart`

```dart
class ActiveSearch {
  const ActiveSearch({
    required this.routeIds,
    required this.searchedAt,
    this.startStopName,
    this.endStopName,
  });

  final Set<int> routeIds;
  final DateTime searchedAt;
  final String? startStopName;
  final String? endStopName;

  bool get hasSearch => routeIds.isNotEmpty;

  bool get isStale {
    if (!hasSearch) return true;
    return DateTime.now().difference(searchedAt).inMinutes >= 15;
  }

  const ActiveSearch.empty()
      : routeIds = const {},
        searchedAt = DateTime(2000),
        startStopName = null,
        endStopName = null;
}
```

**New file:** `client_app/lib/features/home/presentation/providers/active_search_provider.dart`

```dart
import 'package:riverpod_annotation/riverpod_annotation.dart';
import '../../domain/models/active_search.dart';

part 'active_search_provider.g.dart';

@riverpod
class ActiveSearchController extends _$ActiveSearchController {
  @override
  ActiveSearch build() => const ActiveSearch.empty();

  void setSearch({
    required List<int> routeIds,
    String? startStopName,
    String? endStopName,
  }) {
    state = ActiveSearch(
      routeIds: routeIds.toSet(),
      searchedAt: DateTime.now(),
      startStopName: startStopName,
      endStopName: endStopName,
    );
  }

  void clear() {
    state = const ActiveSearch.empty();
  }
}

/// Returns the active search, or empty if stale (15 min TTL).
@riverpod
ActiveSearch activeSearchWithTtl(Ref ref) {
  final search = ref.watch(activeSearchControllerProvider);
  if (search.isStale) {
    // Auto-clear after TTL
    Future.microtask(() {
      ref.read(activeSearchControllerProvider.notifier).clear();
    });
    return const ActiveSearch.empty();
  }
  return search;
}
```

#### 3. Mobile — New Provider: `VisibleBuses`

**New file:** `client_app/lib/features/home/presentation/providers/visible_buses_provider.dart`

```dart
import 'package:riverpod_annotation/riverpod_annotation.dart';
import '../../../tracking/data/services/websocket_service.dart';
import '../../../tracking/domain/models/bus_location.dart';
import 'active_search_provider.dart';

part 'visible_buses_provider.g.dart';

@riverpod
Map<String, BusLocation> visibleBuses(Ref ref) {
  final allBuses = ref.watch(busTrackerProvider);
  final search = ref.watch(activeSearchWithTtlProvider);

  if (!search.hasSearch) {
    return {}; // No search = no buses shown
  }

  return Map.fromEntries(
    allBuses.entries.where((entry) {
      final bus = entry.value;
      // Match by routeId from the busRouteIndex
      final routeId = ref.read(busRouteIndexProvider)[bus.plateNumber];
      return routeId != null && search.routeIds.contains(routeId);
    }),
  );
}
```

#### 4. Mobile — Update Home Screen

**File:** `client_app/lib/features/home/presentation/screens/home_screen.dart`

Replace at line 52:
```dart
final busMap = ref.watch(busTrackerProvider);
```

With:
```dart
final busMap = ref.watch(visibleBusesProvider);
final activeSearch = ref.watch(activeSearchWithTtlProvider);
```

Add a "no search" overlay when no search is active:
```dart
// Inside the Stack, after the FlutterMap:
if (!activeSearch.hasSearch)
  Center(
    child: Container(
      margin: const EdgeInsets.all(32),
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [BoxShadow(color: Colors.black.withAlpha(30), blurRadius: 20)],
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.search, size: 48, color: Color(0xFF0095FF)),
          const SizedBox(height: 16),
          const Text(
            'Search for a route to see\nlive buses on the map',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 16),
          ElevatedButton.icon(
            onPressed: () => context.push('/search'),
            icon: const Icon(Icons.directions_bus),
            label: const Text('Plan a Journey'),
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFF0095FF),
              foregroundColor: Colors.white,
            ),
          ),
        ],
      ),
    ),
  ),
```

When search IS active, show a chip showing the route context:
```dart
// Near the top bar, show search context
if (activeSearch.hasSearch)
  Positioned(
    top: MediaQuery.of(context).padding.top + 70,
    left: 16,
    right: 16,
    child: Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        boxShadow: [BoxShadow(color: Colors.black.withAlpha(20), blurRadius: 8)],
      ),
      child: Row(
        children: [
          const Icon(Icons.route, size: 16, color: Color(0xFF0095FF)),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              '${activeSearch.startStopName ?? "..."} → ${activeSearch.endStopName ?? "..."}',
              style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
              overflow: TextOverflow.ellipsis,
            ),
          ),
          GestureDetector(
            onTap: () => ref.read(activeSearchControllerProvider.notifier).clear(),
            child: const Icon(Icons.close, size: 16, color: Colors.grey),
          ),
        ],
      ),
    ),
  ),
```

#### 5. Mobile — Wire Search Results to Active Search

**File:** `client_app/lib/features/search/presentation/providers/search_provider.dart`

Update the `journeyResults` provider to populate the active search:

```dart
@riverpod
Future<List<JourneyResultModel>> journeyResults(
  Ref ref, {
  required int startStopId,
  required int endStopId,
}) async {
  final repo = ref.watch(searchRepositoryProvider);
  final results = await repo.searchPointToPoint(startStopId, endStopId);

  // Extract route IDs from the backend response (now includes buses array)
  final routeIds = <int>{};
  for (final result in results) {
    // The backend now returns bus data per route
    // We need the bus reposnse to include route_id
    // Since JourneyResultModel.etas map now has vehicle data,
    // extract unique route IDs
    if (result.etas['route_id'] != null) {
      final rid = int.tryParse(result.etas['route_id'].toString());
      if (rid != null) routeIds.add(rid);
    }
  }

  if (routeIds.isNotEmpty) {
    ref.read(activeSearchControllerProvider.notifier).setSearch(
      routeIds: routeIds.toList(),
      startStopName: 'Origin',  // TODO: pass actual names
      endStopName: 'Destination',
    );
  }

  return results;
}
```

#### 6. Backend — Include `route_id` in ETA Response

In `search.py`, the point-to-point response now includes `buses[]`. The mobile extracts route IDs from `buses[i].route_id`. No additional change needed beyond FIX 2.1.

### Summary — Files to Change for Filtered Buses

| File | Change | New/Modified |
|------|--------|-------------|
| `home/domain/models/active_search.dart` | Search context model + TTL | **NEW** |
| `home/presentation/providers/active_search_provider.dart` | Riverpod notifier + TTL provider | **NEW** |
| `home/presentation/providers/visible_buses_provider.dart` | Filters buses by search | **NEW** |
| `home/presentation/screens/home_screen.dart` | Uses filtered provider + UI prompts | Modified |
| `search/presentation/providers/search_provider.dart` | Populates active search on results | Modified |
| `api/v1/search.py` | Include bus data in point-to-point response | Modified (FIX 2.1) |
| `services/route_eta.py` | Pass plate/vehicle_id into ETA payload | Modified (FIX 2.1) |

---

## Complete File Checklist

### 11 files total (6 backend + 5 mobile)

**Backend:**
1. `app/models/vehicle.py` — Add `dashboard_password_hash` column
2. Alembic migration — Add column
3. `app/api/v1/pairing.py` — **NEW** — 3 endpoints (generate/verify/unpair)
4. `app/api/v1/__init__.py` — Register pairing router
5. `app/api/v1/search.py` — Enrich point-to-point with bus data (FIX 2.1)
6. `app/services/route_eta.py` — Add plate/vehicle_id to ETA hash (FIX 2.1)

**Mobile:**
7. `home/domain/models/active_search.dart` — **NEW**
8. `home/presentation/providers/active_search_provider.dart` — **NEW**
9. `home/presentation/providers/visible_buses_provider.dart` — **NEW**
10. `home/presentation/screens/home_screen.dart` — Map uses filtered buses + prompts
11. `search/presentation/providers/search_provider.dart` — Wire search → active search
