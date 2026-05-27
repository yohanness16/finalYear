import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


class FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()

    async def _get_redis() -> FakeRedis:
        return fake

    monkeypatch.setattr("app.services.token_service.get_redis", _get_redis)
    return fake


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
async def test_register_duplicate_user(fake_redis: FakeRedis):
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
