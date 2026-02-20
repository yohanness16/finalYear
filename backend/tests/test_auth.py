"""Auth tests: register, login, token validation."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.security import create_access_token, decode_token


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
async def test_register_and_login():
    """Requires running DB. Run with: pytest -m integration"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/register",
            json={"username": "testuser2", "email": "test2@example.com", "password": "secret12345"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["username"] == "testuser2"
        assert data["role"] == "passenger"

        r2 = await client.post(
            "/api/v1/auth/login",
            json={"username": "testuser2", "password": "secret12345"},
        )
        assert r2.status_code == 200
        assert "access_token" in r2.json()
