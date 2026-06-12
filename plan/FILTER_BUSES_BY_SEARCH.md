# Plan: Show Only Searched Buses to Users
**Date:** 2026-05-26
**Requirement:** Users should only see buses relevant to their searched route, NOT every bus in the system.

---

## Current Behavior (What's Wrong)

### Home Screen (Map Tab)
- The `BusTracker` provider calls `GET /vehicles/positions` which returns **ALL** active buses in the entire system
- `_buildMapMarkers()` renders every single bus on the map
- The user sees 10, 20, 50+ buses regardless of where they are going
- This is overwhelming and not useful — a bus on the other side of the city is irrelevant

### Journey Results Screen
- `POST /search/point-to-point` reads ETA from Redis `route:{number}:stop:{stop_id}` but doesn't return vehicle plate numbers
- `busPlate` is always null, so it always says "No active bus"
- This screen doesn't filter anything — it just shows route numbers with empty ETA data

### Route Detail Screen
- Correctly filters buses: `liveBuses.values.where((bus) => targetJourney!.etas.containsKey(bus.assignmentId.toString()))`
- Only shows buses whose `assignment_id` matches an ETA entry for this route
- **This is the model for how the home screen should work** — but only AFTER a search

---

## Desired Behavior

### Scenario 1: User Has Not Searched Yet
- Show **NO buses** on the map (or show a prompt to search)
- The home screen should orient the user toward searching first

### Scenario 2: User Searches (Point-to-Point)
- After the user selects origin → destination and taps "Find Buses"
- The `POST /search/point-to-point` response should include relevant bus data
- The home map should show **only buses on routes that serve the searched path**
- Other buses (on unrelated routes) should be hidden

### Scenario 3: User Views Route Detail
- Already correct — only shows buses on the specific route with matching assignments
- No change needed here

---

## Architecture Changes Required

### Change 1: Backend — Enrich Point-to-Point Response with Bus Data

**File:** `backend/app/api/v1/search.py`

**Current code (line 66-84):**
```python
for route in routes:
    key = f"route:{route.route_number}:stop:{body.start_stop_id}"
    data = {}
    if redis is not None:
        try:
            data = await redis.hgetall(key)
        except Exception:
            data = {}
    if data:
        results.append({"route_number": route.route_number, "etas": data})
    else:
        results.append({"route_number": route.route_number, "etas": {}})
```

**Problem:** The Redis ETA hash (`route:{no}:stop:{id}`) doesn't contain bus_plate or vehicle_id. It only has `eta_seconds`, `computed_at`, etc.

**Fix:** After reading ETA from Redis, cross-reference with the vehicle positions to find which buses are on this route, and include full bus data:

```python
for route in routes:
    key = f"route:{route.route_number}:stop:{body.start_stop_id}"
    data = {}
    if redis is not None:
        try:
            data = await redis.hgetall(key)
        except Exception:
            data = {}
    
    # Find live buses on this route
    route_buses = [
        bus for bus in live_positions.values()
        if bus.get("route_id") == route.id
    ]
    
    if data:
        results.append({
            "route_number": route.route_number,
            "etas": data,
            "buses": route_buses,  # ← NEW: full bus data
        })
    else:
        results.append({
            "route_number": route.route_number,
            "etas": {},
            "buses": route_buses,  # ← still include buses even if no ETA
        })
```

**Also need:** `live_positions` must be fetched. Currently it's not fetched in the point-to-point endpoint (only in the journey endpoint). Add:

```python
# Before the routes loop:
live_positions = await crud_vehicle.get_live_positions(db)
```

### Change 2: Backend — Add `bus_plate` to Redis ETA Hash

**File:** `backend/app/services/route_eta.py`

When computing and storing ETAs, include the vehicle plate number:
```python
# In estimate_route_stop_eta_payloads() or where the Redis hash is written:
await redis.hset(bus_live_key(plate), mapping={
    "eta_seconds": ...,
    "computed_at": ...,
    "stop_name": ...,
    "distance_m": ...,
    "occupancy_level": ...,
    "bus_plate": plate,  # ← NEW
    "vehicle_id": str(vehicle_id),  # ← NEW
})
```

### Change 3: Mobile — Add Search-Aware Filtering to Home Screen

**File:** `client_app/lib/features/home/presentation/screens/home_screen.dart`

**Current code (line 52):**
```dart
final busMap = ref.watch(busTrackerProvider);
```

This gets ALL buses. Need to add a filtered view.

**New approach:**

The `BusTracker` polls all vehicles. That's fine — we need the full data for route detail too. The filtering should happen at the **display layer**, not the data layer.

Create a new provider that filters based on search state:

**File (new or modified):** `client_app/lib/features/home/presentation/providers/visible_buses_provider.dart`
```dart
// Combines the full bus tracker with the current search selection
// If user has searched: only show buses on matching routes
// If user hasn't searched: show no buses (or all — configurable)
```

**In `home_screen.dart`:**

Replace:
```dart
final busMap = ref.watch(busTrackerProvider);
```

With:
```dart
final busMap = ref.watch(visibleBusesProvider);
```

### Change 4: Mobile — Track Which Route IDs Are Active in Search

**File:** `client_app/lib/features/search/presentation/providers/search_provider.dart`

When point-to-point search completes, store the relevant route IDs and bus data:

```dart
@riverpod
class ActiveSearch extends _$ActiveSearch {
  @override
  SearchActiveData build() {
    return SearchActiveData.empty();
  }

  void setSearchResults(List<JourneyResultModel> results, List<int> routeIds) {
    state = SearchActiveData(
      routeIds: routeIds,
      hasSearch: true,
    );
  }

  void clear() {
    state = SearchActiveData.empty();
  }
}

class SearchActiveData {
  final Set<int> routeIds;
  final bool hasSearch;
  
  const SearchActiveData({required this.routeIds, required this.hasSearch});
  const SearchActiveData.empty() : routeIds = const {}, hasSearch = false;
}
```

### Change 5: Mobile — Wire Visibility into Search Flow

**File:** `client_app/lib/features/search/presentation/screens/journey_results_screen.dart`

When search results arrive, extract route IDs and update the active search state:

```dart
// In the provider that fetches results, after parsing:
ref.read(activeSearchProvider.notifier).setSearchResults(
  routeIds: results.map((r) => /* get route IDs from vehicle positions */).toList(),
);
```

---

## Detailed Implementation Plan

### Step 1: Backend — Fetch live positions in point-to-point search
**File:** `backend/app/api/v1/search.py`  
**Effort:** 10 minutes

Add `live_positions = await crud_vehicle.get_live_positions(db)` before the routes loop in `point_to_point_search()`.

### Step 2: Backend — Include bus data in point-to-point response
**File:** `backend/app/api/v1/search.py`  
**Effort:** 20 minutes

In `point_to_point_search()`, for each route, find matching buses from `live_positions` and include them in the response. Change the response from:
```json
{"route_number": "12", "etas": {...}}
```
to:
```json
{"route_number": "12", "etas": {...}, "buses": [{vehicle_id, plate_number, lat, lon, speed, occupancy_level}]}
```

### Step 3: Backend — Store `bus_plate` in Redis ETA hash
**File:** `backend/app/services/route_eta.py` or wherever the ETA hash is written  
**Effort:** 15 minutes

When computing ETA payloads per route-stop, include `bus_plate` and `vehicle_id` in the hash.

### Step 4: Mobile — Add `ActiveSearch` provider
**File:** `client_app/lib/features/search/presentation/providers/search_provider.dart`  
**Effort:** 20 minutes

Add a new Riverpod notifier that tracks which route IDs are relevant to the current search.

### Step 5: Mobile — Add `VisibleBuses` provider
**New file:** `client_app/lib/features/home/presentation/providers/visible_buses_provider.dart`  
**Effort:** 30 minutes

Create a derived provider that:
- Watches `busTrackerProvider` (all buses) AND `activeSearchProvider`
- If `hasSearch == false`: return empty map (no buses)
- If `hasSearch == true`: filter `busTrackerProvider` to only buses whose `routeId` is in the active search's `routeIds`

### Step 6: Mobile — Wire up home screen
**File:** `client_app/lib/features/home/presentation/screens/home_screen.dart`  
**Effort:** 15 minutes

Replace `ref.watch(busTrackerProvider)` with `ref.watch(visibleBusesProvider)`.

When no search has been performed, show a prompt: "Search for a route to see buses"

### Step 7: Mobile — Update search results to populate active routes
**File:** `client_app/lib/features/search/presentation/screens/journey_results_screen.dart`  
**Effort:** 20 minutes

When results come back from the backend's enriched `POST /search/point-to-point`, extract route IDs and call `activeSearchProvider.notifier().setSearchResults()`.

### Step 8: Mobile — Clear search state on app restart or explicit "clear"
**Files:** Multiple  
**Effort:** 15 minutes

Add a "Clear Search" action (or auto-clear when navigating away from results) that resets `activeSearchProvider` and returns the map to the empty state.

---

## Summary of Files to Change

### Backend (2 files)
| File | Change |
|------|--------|
| `app/api/v1/search.py` | Fetch live positions in point-to-point; include bus data in response |
| `app/services/route_eta.py` | Add `bus_plate` / `vehicle_id` to Redis ETA hash |

### Mobile (4 files changed, 1 new file)
| File | Change |
|------|--------|
| `home/presentation/screens/home_screen.dart` | Use `visibleBusesProvider` instead of `busTrackerProvider`; show "search first" prompt |
| `search/presentation/providers/search_provider.dart` | Add `ActiveSearch` notifier with route IDs from search results |
| `home/presentation/providers/visible_buses_provider.dart` | **NEW** — derived provider that filters buses by search |
| `search/presentation/screens/journey_results_screen.dart` | Populate `activeSearchProvider` when results arrive |

---

## Data Flow After Changes

```
User selects origin → destination → "Find Buses"
  │
  ▼
Backend: POST /search/point-to-point
  ├─ Finds routes through both stops
  ├─ Reads ETA from Redis (now includes bus_plate, vehicle_id)
  ├─ Cross-references with live positions
  └─ Returns: [{route_number, etas, buses:[{vehicle_id, plate, lat, lon, ...}]}]
  │
  ▼
Mobile: JourneyResultsScreen
  ├─ Displays route cards with bus data
  └─ Calls activeSearchProvider.setSearchResults([route_ids])
  │
  ▼
Mobile: VisibleBusesProvider (derived)
  ├─ Watches activeSearchProvider.routeIds
  ├─ Watches busTrackerProvider (all buses)
  └─ Filters: only buses where bus.routeId ∈ activeSearch.routeIds
  │
  ▼
Mobile: Home Screen Map
  └─ Shows ONLY buses on the user's searched route(s)
```

---

## Edge Cases & Notes

1. **Multiple routes share buses:** If the user's search returns routes 12 and 45, and a bus is on route 12, it shows. If route 45 is a different direction, its buses also show. This is correct.

2. **No active buses on searched route:** The filtered map shows no buses. The journey results screen should explain this: "No active buses on this route right now. Check back in a few minutes."

3. **User switches tabs:** The search context persists. When the user goes to the Map tab, they still see their filtered buses. This is correct — the search is still "active."

4. **Stale search:** If the user searched 30 minutes ago, the route context is stale. Consider adding a TTL (e.g., 15 minutes) after which the search context clears and the map returns to the empty/search-prompt state.

5. **Existing route detail screen:** Already filters correctly. No changes needed. The route detail screen uses the backend's `search/journey` endpoint and its own `targetJourney` filtering logic, which is separate from this home-screen filtering.

6. **Favorites quick-access:** When the user taps a favorite route chip on the home screen, it should trigger a "virtual search" for that route's ID, setting the active search to that single route's buses. Add this to the favorites chip `onPressed` handler.
