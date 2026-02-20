"""Route and stop CRUD operations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.route import Route, RouteStop
from app.models.stop import Stop


async def get_route_by_id(db: AsyncSession, route_id: int) -> Route | None:
    result = await db.execute(
        select(Route).where(Route.id == route_id).options(selectinload(Route.route_stops).selectinload(RouteStop.stop))
    )
    return result.scalar_one_or_none()


async def get_route_by_number(db: AsyncSession, route_number: str) -> Route | None:
    result = await db.execute(select(Route).where(Route.route_number == route_number))
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


async def get_routes_through_stops(db: AsyncSession, start_stop_id: int, end_stop_id: int) -> list[Route]:
    """Find routes where start comes before end in sequence."""
    result = await db.execute(
        select(Route)
        .join(RouteStop, Route.id == RouteStop.route_id)
        .where(RouteStop.stop_id.in_([start_stop_id, end_stop_id]))
        .options(selectinload(Route.route_stops).selectinload(RouteStop.stop))
        .distinct()
    )
    routes = list(result.scalars().unique().all())
    # Filter: start must come before end
    valid = []
    for r in routes:
        stops_order = {rs.stop_id: rs.sequence_order for rs in r.route_stops}
        if start_stop_id in stops_order and end_stop_id in stops_order:
            if stops_order[start_stop_id] < stops_order[end_stop_id]:
                valid.append(r)
    return valid


async def create_route(
    db: AsyncSession,
    route_number: str,
    name: str | None = None,
    origin: str | None = None,
    destination: str | None = None,
    stop_sequence: list[tuple[int, int]] | None = None,
) -> Route:
    route = Route(route_number=route_number, name=name, origin=origin, destination=destination)
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
