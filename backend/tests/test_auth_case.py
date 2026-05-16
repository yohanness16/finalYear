import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_login_invalid_credentials():
    # Using a non-existent user is safer for testing 'Unauthorized'
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "non_existent_user", "password": "wrongpassword"},
        )
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_register_duplicate_user():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "username": "existing",
            "email": "exists@example.com",
            "password": "password123",
        }
        # First registration
        await client.post("/api/v1/auth/register", json=payload)
        # Second registration (duplicate)
        response = await client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 400
