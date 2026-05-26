"""Verify all API routes are registered and respond correctly."""

import pytest
from fastapi.routing import APIRoute

from app.main import app


@pytest.fixture
def all_routes() -> list[dict]:
    """Extract all routes from the FastAPI app."""
    routes = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            routes.append(
                {
                    "path": route.path,
                    "methods": route.methods or set(),
                    "name": route.name,
                    "tags": route.tags or [],
                }
            )
    return routes


def test_no_duplicate_routes(all_routes):
    """No two routes should have the same path + method combo."""
    seen = set()
    for route in all_routes:
        for method in route["methods"]:
            key = (route["path"], method)
            assert key not in seen, f"Duplicate route: {method} {route['path']}"
            seen.add(key)


def test_critical_endpoints_exist(all_routes):
    """All critical endpoints from the redesign plan should be registered."""
    all_paths = {r["path"] for r in all_routes}

    critical = [
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/google",
        "/api/v1/auth/me",
        "/api/v1/auth/refresh",
        "/api/v1/auth/change-password",
        "/api/v1/auth/verify-email",
        "/api/v1/auth/resend-verification",
        "/api/v1/auth/forgot-password",
        "/api/v1/auth/reset-password",
        "/api/v1/auth/driver-login",
        "/api/v1/auth/driver-logout",
        "/api/v1/auth/bus-dashboard/login",
        "/api/v1/search/point-to-point",
        "/api/v1/search/journey",
        "/api/v1/vehicles/positions",
        "/api/v1/favorites/{user_id}",
        "/api/v1/notifications/settings/{user_id}",
        "/api/v1/routes",
        "/api/v1/stops",
        "/api/v1/notifications/register-token",
        "/api/v1/admin/vehicles/{vehicle_id}/generate-pairing-code",
        "/api/v1/pair/verify",
        "/api/v1/admin/vehicles/{vehicle_id}/unpair",
    ]

    for endpoint in critical:
        found = endpoint in all_paths
        if not found:
            param_parts = endpoint.replace("{", "").replace("}", "").split("/")
            for path in all_paths:
                path_parts = path.split("/")
                if len(path_parts) == len(param_parts):
                    match = all(
                        pp == pe or pp.startswith("{") or pp == ""
                        for pp, pe in zip(path_parts, param_parts)
                    )
                    if match:
                        found = True
                        break
        assert found, f"Missing critical endpoint: {endpoint}"


def test_patch_auth_me_method(all_routes):
    """PATCH /auth/me must be registered (not GET or POST)."""
    patch_routes = [
        r
        for r in all_routes
        if r["path"] == "/api/v1/auth/me" and "PATCH" in r["methods"]
    ]
    assert len(patch_routes) >= 1, "PATCH /auth/me route must exist"
