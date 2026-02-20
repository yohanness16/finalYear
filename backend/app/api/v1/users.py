"""User endpoints (deprecated: use auth for register/login)."""

from fastapi import APIRouter

router = APIRouter()
# Register and login moved to app.api.v1.auth
