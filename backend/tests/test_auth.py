"""Auth tests: register, login, token validation."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import create_access_token, decode_token
from app.main import app


# Helper to generate unique data so tests don't clash in the DB
@pytest.fixture
def unique_user():
    uid = uuid.uuid4().hex[:6]
    return {
        "username": f"user_{uid}",
        "email": f"test_{uid}@example.com",
        "password": "secret12345",
    }


def test_create_and_decode_token():
    token = create_access_token(1)
    assert token
    payload = decode_token(token)
    assert payload
    assert payload["sub"] == "1"
    assert "exp" in payload


def test_decode_invalid_token():
    assert decode_token("invalid") is None
    assert decode_token("") is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_register_and_login(unique_user):
    """Requires running DB. Run with: pytest -m integration"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Register
        r = await client.post(
            "/api/v1/auth/register",
            json=unique_user,
        )

        # If this fails, print the error message from the server
        if r.status_code != 200:
            print(f"Registration failed: {r.json()}")

        assert r.status_code == 200
        data = r.json()
        assert data["username"] == unique_user["username"]
        # Default role check (adjust if your logic defaults to something else)
        assert data["role"] == "passenger"

        # 2. Login
        r2 = await client.post(
            "/api/v1/auth/login",
            json={
                "username": unique_user["username"],
                "password": unique_user["password"],
            },
        )
        assert r2.status_code == 200
        login_data = r2.json()
        assert "access_token" in login_data
        assert login_data["token_type"] == "bearer"
