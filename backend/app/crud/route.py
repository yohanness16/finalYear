"""Route and stop CRUD operations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.route import Route, RouteStop
from app.models.stop import Stop
from app.utils.gps_validation import haversine_meters


async def get_route_stops_ordered(db: AsyncSession, route_id: int) -> list[Stop]:
    """Stops on a route in sequence order (for GPS validation)."""
    route = await get_route_by_id(db, route_id)
    if not route or not route.route_stops:
        return []
    ordered = sorted(route.route_stops, key=lambda rs: rs.sequence_order)
    return [rs.stop for rs in ordered if rs.stop is not None]


async def get_route_by_id(db: AsyncSession, route_id: int) -> Route | None:
    result = await db.execute(
        select(Route)
        .where(Route.id == route_id)
        .options(selectinload(Route.route_stops).selectinload(RouteStop.stop))
    )
    return result.scalar_one_or_none()


async def get_route_by_number(
    db: AsyncSession,
    route_number: str,
    direction: str | None = None,
) -> Route | None:
    stmt = select(Route).where(Route.route_number == route_number)
    if direction:
        stmt = stmt.where(Route.direction == direction)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_routes(db: AsyncSession, skip: int = 0, limit: int = 100) -> list[Route]:
    result = await db.execute(select(Route).offset(skip).limit(limit))
    return list(result.scalars().all())


async def get_stop_by_id(db: AsyncSession, stop_id: int) -> Stop | None:
    result = await db.execute(select(Stop).where(Stop.id == stop_id))
    return result.scalar_one_or_none()


async def get_stops(db: AsyncSession, skip: int = 0, limit: int = 100) -> list[Stop]:
    result = await db.execute(select(Stop).offset(skip).limit(limit))
    return list(result.scalars().all())


async def get_nearest_stop(db: AsyncSession, lat: float, lon: float) -> Stop | None:
    """Return the nearest stop to the provided coordinates."""
    result = await db.execute(select(Stop))
    stops = list(result.scalars().all())
    if not stops:
        return None
    return min(stops, key=lambda s: haversine_meters(lat, lon, s.lat, s.lon))


async def get_nearest_stops(
    db: AsyncSession, lat: float, lon: float, limit: int = 3
) -> list[Stop]:
    """Return the nearest stops, ordered by distance."""
    result = await db.execute(select(Stop))
    stops = list(result.scalars().all())
    if not stops:
        return []
    stops.sort(key=lambda s: haversine_meters(lat, lon, s.lat, s.lon))
    return stops[: max(1, int(limit))]


async def get_routes_through_stops(
    db: AsyncSession, start_stop_id: int, end_stop_id: int
) -> list[Route]:
    """Find routes containing both stops with correct travel direction.

    Only returns route-direction combinations where the start stop comes
    before the end stop in the route's sequence (i.e. the bus actually
    travels from start→end, not end→start).
    """
    result = await db.execute(
        select(Route)
        .join(RouteStop, Route.id == RouteStop.route_id)
        .where(RouteStop.stop_id.in_([start_stop_id, end_stop_id]))
        .options(selectinload(Route.route_stops).selectinload(RouteStop.stop))
        .distinct()
    )
    routes = list(result.scalars().unique().all())
    # Filter: route must contain both stops with correct direction
    valid = []
    for r in routes:
        stops_order = {rs.stop_id: rs.sequence_order for rs in r.route_stops}
        if start_stop_id not in stops_order or end_stop_id not in stops_order:
            continue
        if start_stop_id == end_stop_id:
            continue
        # Only include this route if start comes before end in sequence
        if stops_order[start_stop_id] < stops_order[end_stop_id]:
            valid.append(r)
    return valid


async def create_route(
    db: AsyncSession,
    route_number: str,
    direction: str = "forward",
    name: str | None = None,
    origin: str | None = None,
    destination: str | None = None,
    stop_sequence: list[tuple[int, int]] | None = None,
) -> Route:
    route = Route(
        route_number=route_number,
        direction=direction,
        name=name,
        origin=origin,
        destination=destination,
    )
    db.add(route)
    await db.flush()
    if stop_sequence:
        for stop_id, order in stop_sequence:
            rs = RouteStop(route_id=route.id, stop_id=stop_id, sequence_order=order)
            db.add(rs)
    await db.refresh(route)
    return route


async def create_stop(
    db: AsyncSession,
    name: str,
    lat: float,
    lon: float,
    base_dwell_time: int = 30,
    is_terminal: bool = False,
    peak_multiplier: float = 1.5,
) -> Stop:
    stop = Stop(
        name=name,
        lat=lat,
        lon=lon,
        base_dwell_time=base_dwell_time,
        is_terminal=is_terminal,
        peak_multiplier=peak_multiplier,
    )
    db.add(stop)
    await db.flush()
    await db.refresh(stop)
    return stop
