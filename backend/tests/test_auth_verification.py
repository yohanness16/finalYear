"""Tests for email verification and password reset flows."""

import pytest
from httpx import AsyncClient


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
async def test_register_sends_verification_token(
    client: AsyncClient, fake_redis: FakeRedis
):
    """Register should create user with is_verified=False."""
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "verifytest",
            "email": "verify@test.com",
            "password": "Password123!",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_verified"] is False


@pytest.mark.asyncio
async def test_verify_email_with_invalid_token(
    client: AsyncClient, fake_redis: FakeRedis
):
    """Invalid verification token should return 400."""
    resp = await client.post(
        "/api/v1/auth/verify-email",
        json={
            "token": "invalid_token_xyz",
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_resend_verification_nonexistent_email(
    client: AsyncClient, fake_redis: FakeRedis
):
    """Resending to nonexistent email should not reveal existence."""
    resp = await client.post(
        "/api/v1/auth/resend-verification",
        json={
            "email": "doesnotexist@test.com",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "sent"


@pytest.mark.asyncio
async def test_forgot_password_nonexistent_email(
    client: AsyncClient, fake_redis: FakeRedis
):
    """Forgot password for nonexistent email should not reveal."""
    resp = await client.post(
        "/api/v1/auth/forgot-password",
        json={
            "email": "doesnotexist@test.com",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "sent"


@pytest.mark.asyncio
async def test_reset_password_invalid_token(client: AsyncClient, fake_redis: FakeRedis):
    """Invalid reset token should return 400."""
    resp = await client.post(
        "/api/v1/auth/reset-password",
        json={
            "token": "invalid_token_xyz",
            "new_password": "NewPassword123!",
        },
    )
    assert resp.status_code == 400
