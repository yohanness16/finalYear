"""Tests for route direction and reverse matching."""

from uuid import uuid4

import pytest

from app.crud.route import create_route, create_stop, get_routes_through_stops
from app.db.session import AsyncSessionLocal


@pytest.mark.asyncio
async def test_routes_through_stops_supports_forward_and_reverse_routes():
    suffix = uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        stop_a = await create_stop(
            db,
            name=f"Stop A {suffix}",
            lat=9.0,
            lon=38.0,
        )
        stop_b = await create_stop(
            db,
            name=f"Stop B {suffix}",
            lat=9.1,
            lon=38.1,
        )

        forward_route = await create_route(
            db,
            route_number=f"R{suffix}",
            direction="forward",
            name=f"Route {suffix} forward",
            origin=stop_a.name,
            destination=stop_b.name,
            stop_sequence=[(stop_a.id, 1), (stop_b.id, 2)],
        )
        reverse_route = await create_route(
            db,
            route_number=f"R{suffix}",
            direction="reverse",
            name=f"Route {suffix} reverse",
            origin=stop_b.name,
            destination=stop_a.name,
            stop_sequence=[(stop_b.id, 1), (stop_a.id, 2)],
        )
        await db.commit()

        routes = await get_routes_through_stops(db, stop_a.id, stop_b.id)

        matched = {(route.route_number, route.direction) for route in routes}
        assert (forward_route.route_number, "forward") in matched
        assert (reverse_route.route_number, "reverse") in matched
        assert len(routes) == 2
