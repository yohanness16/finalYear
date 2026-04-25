"""Seed Addis Ababa bus routes with stops and GPS coordinates."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import Route, RouteStop
from app.models.stop import Stop

ADDIS_ABABA_ROUTES_SEED = [
    {
        "route_number": "121",
        "name": "Kality Bus Station ↔ Meskel Square",
        "origin": "Kality Bus Station",
        "destination": "Meskel Square",
        "stops": [
            {"name": "Kality Bus Station", "lat": 9.0167, "lon": 38.7667, "sequence": 1, "is_terminal": True},
            {"name": "Bole Road (near Ghana St)", "lat": 9.0200, "lon": 38.7700, "sequence": 2},
            {"name": "Africa Avenue (near St. Joseph)", "lat": 9.0250, "lon": 38.7750, "sequence": 3},
            {"name": "Meskel Square", "lat": 9.0300, "lon": 38.7800, "sequence": 4, "is_terminal": True},
        ],
    },
    {
        "route_number": "122",
        "name": "Akaki ↔ Entoto Hills",
        "origin": "Akaki",
        "destination": "Entoto Hills",
        "stops": [
            {"name": "Akaki Terminal", "lat": 9.0000, "lon": 38.7500, "sequence": 1, "is_terminal": True},
            {"name": "Bole International Approach", "lat": 9.0120, "lon": 38.7600, "sequence": 2},
            {"name": "Entoto Hills Base", "lat": 9.0450, "lon": 38.7800, "sequence": 3},
            {"name": "Entoto Hills Summit", "lat": 9.0500, "lon": 38.7850, "sequence": 4, "is_terminal": True},
        ],
    },
    {
        "route_number": "150",
        "name": "Gulele ↔ Saris",
        "origin": "Gulele",
        "destination": "Saris",
        "stops": [
            {"name": "Gulele Square", "lat": 9.0380, "lon": 38.7450, "sequence": 1, "is_terminal": True},
            {"name": "Wollo Sefer", "lat": 9.0400, "lon": 38.7550, "sequence": 2},
            {"name": "Saris Market", "lat": 9.0480, "lon": 38.7600, "sequence": 3, "is_terminal": True},
        ],
    },
]


async def seed_addis_ababa_routes(db: AsyncSession) -> None:
    """Seed routes, stops, and route-stop links if not already present."""
    for item in ADDIS_ABABA_ROUTES_SEED:
        route = (
            await db.execute(
                select(Route).where(Route.route_number == item["route_number"])
            )
        ).scalar_one_or_none()
        if not route:
            route = Route(
                route_number=item["route_number"],
                name=item["name"],
                origin=item["origin"],
                destination=item["destination"],
                active=True,
            )
            db.add(route)
            await db.flush()

        for stop_data in item["stops"]:
            stop = (
                await db.execute(
                    select(Stop).where(Stop.name == stop_data["name"])
                )
            ).scalar_one_or_none()
            if not stop:
                stop = Stop(
                    name=stop_data["name"],
                    lat=stop_data["lat"],
                    lon=stop_data["lon"],
                    base_dwell_time=stop_data.get("base_dwell_time", 30),
                    is_terminal=stop_data.get("is_terminal", False),
                    peak_multiplier=stop_data.get("peak_multiplier", 1.5),
                )
                db.add(stop)
                await db.flush()

            existing_route_stop = (
                await db.execute(
                    select(RouteStop).where(
                        RouteStop.route_id == route.id,
                        RouteStop.stop_id == stop.id,
                    )
                )
            ).scalar_one_or_none()

            if existing_route_stop:
                existing_route_stop.sequence_order = stop_data["sequence"]
            else:
                route_stop = RouteStop(
                    route_id=route.id,
                    stop_id=stop.id,
                    sequence_order=stop_data["sequence"],
                )
                db.add(route_stop)

    await db.commit()