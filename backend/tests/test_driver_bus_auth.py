"""Tests for bus-bound driver authentication and session tracking endpoints."""

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.auth import pwd_context
from app.db.session import get_db
from app.main import app


@pytest.fixture
def override_db_dependency():
    async def _override_get_db():
        yield object()

    app.dependency_overrides[get_db] = _override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def override_current_user_dependency():
    from app.api.v1 import auth

    def _override_get_current_user():
        return SimpleNamespace(id=10, role="driver")

    app.dependency_overrides[auth.get_current_user] = _override_get_current_user
    yield
    app.dependency_overrides.pop(auth.get_current_user, None)


@pytest.mark.asyncio
async def test_driver_login_creates_bus_session(monkeypatch, override_db_dependency):
    from app.api.v1 import auth

    password = "driver-pass-123"
    user = SimpleNamespace(
        id=10,
        username="driver_one",
        role="driver",
        password_hash=pwd_context.hash(password),
    )
    vehicle = SimpleNamespace(id=5, plate_number="AA-50505", device_id="IMEI-50505")
    created_session = SimpleNamespace(id=77)

    async def _get_user(*args, **kwargs):
        return user

    async def _get_vehicle(*args, **kwargs):
        return vehicle

    async def _no_active(*args, **kwargs):
        return None

    async def _create_session(*args, **kwargs):
        return created_session

    monkeypatch.setattr(auth.crud_user, "get_user_by_username", _get_user)
    monkeypatch.setattr(auth.crud_vehicle, "get_vehicle_by_device_id", _get_vehicle)
    monkeypatch.setattr(auth.crud_driver_session, "get_active_session_for_driver", _no_active)
    monkeypatch.setattr(auth.crud_driver_session, "create_session", _create_session)

    bus_token = auth.jwt.encode(
        {"sub": str(vehicle.id), "type": "bus_dashboard"},
        auth.settings.SECRET_KEY,
        algorithm=auth.ALGORITHM,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/driver-login",
            json={
                "username": "driver_one",
                "password": password,
                "device_id": "IMEI-50505",
                "bus_token": bus_token,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == 77
    assert payload["driver_id"] == 10
    assert payload["vehicle_id"] == 5
    assert payload["device_id"] == "IMEI-50505"
    assert payload["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_driver_logout_closes_session(
    monkeypatch, override_db_dependency, override_current_user_dependency
):
    from app.api.v1 import auth

    async def _get_session(*args, **kwargs):
        return SimpleNamespace(id=88, driver_id=10)

    async def _end_session(*args, **kwargs):
        return SimpleNamespace(id=88)

    monkeypatch.setattr(auth.crud_driver_session, "get_session_by_id", _get_session)
    monkeypatch.setattr(auth.crud_driver_session, "end_session", _end_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/driver-logout", json={"session_id": 88})

    assert response.status_code == 200
    assert response.json() == {"status": "logged_out", "session_id": 88}


@pytest.mark.asyncio
async def test_bus_dashboard_login_requires_configured_password(monkeypatch, override_db_dependency):
    from app.api.v1 import auth

    vehicle = SimpleNamespace(id=9, device_id="IMEI-90909", dashboard_password_hash=None)

    async def _get_vehicle(*args, **kwargs):
        return vehicle

    monkeypatch.setattr(auth.crud_vehicle, "get_vehicle_by_id", _get_vehicle)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/bus-dashboard/login",
            json={
                "vehicle_id": 9,
                "device_id": "IMEI-90909",
                "password": "bus-pass-123",
            },
        )

    assert response.status_code == 400
    assert "not configured" in response.json()["detail"]
