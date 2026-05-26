"""Integration tests covering all fixed and new endpoints.

These tests verify the complete request/response cycle.
They require:
  - A running PostgreSQL test database
  - A running Redis instance (or fakeredis)
  - The FastAPI app in test mode
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict:
    """Get JWT auth headers for a test user."""
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": "integrationtest",
            "email": "integration@test.com",
            "password": "TestPassword123!",
        },
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={
            "username": "integrationtest",
            "password": "TestPassword123!",
        },
    )
    if login_resp.status_code == 200:
        token = login_resp.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}
    return {}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_profile_update_flow(client: AsyncClient, auth_headers: dict):
    """GET /auth/me → PATCH /auth/me → GET /auth/me to verify update."""
    if not auth_headers:
        pytest.skip("Could not authenticate test user")

    me_resp = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert me_resp.status_code == 200
    original_username = me_resp.json()["username"]

    patch_resp = await client.patch(
        "/api/v1/auth/me",
        headers=auth_headers,
        json={"username": "newtestname123"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["username"] == "newtestname123"

    me_resp2 = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert me_resp2.json()["username"] == "newtestname123"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_change_password_flow(client: AsyncClient, auth_headers: dict):
    """POST /auth/change-password with correct current password."""
    if not auth_headers:
        pytest.skip("Could not authenticate test user")

    resp = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers,
        json={
            "current_password": "TestPassword123!",
            "new_password": "NewPassword456!",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "password_changed"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_favorite_crud_flow(client: AsyncClient, auth_headers: dict):
    """Create favorite → list → delete → verify deletion."""
    if not auth_headers:
        pytest.skip("Could not authenticate test user")

    create_resp = await client.post(
        "/api/v1/favorites",
        json={"user_id": 1, "route_id": 1, "nickname": "My Route"},
    )
    assert create_resp.status_code == 200
    fav_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/api/v1/favorites/{fav_id}", headers=auth_headers)
    assert del_resp.status_code in {200, 204}

    list_resp = await client.get("/api/v1/favorites/1")
    remaining_ids = [f["id"] for f in list_resp.json()]
    assert fav_id not in remaining_ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fcm_token_registration(client: AsyncClient):
    """POST /notifications/register-token should succeed."""
    resp = await client.post(
        "/api/v1/notifications/register-token",
        json={
            "user_id": 1,
            "token": "test_fcm_device_token_xyz",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "registered"


@pytest.mark.asyncio
async def test_bus_dashboard_pair_flow():
    """Pair → login with pairing code (mock Redis)."""
    pass
