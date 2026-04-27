"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.v1 import (
    auth,
    admin_users,
    admin_dashboard,
    tracking,
    gateway,
    users,
    vehicles,
    routes,
    assignments,
    admin,
    websocket,
    search,
    favorites,
    notifications,
)
from app.utils.redis_client import close_redis
from app.services.redis_cache import close_redis_cache
from app.middleware.security_headers import SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown."""
    yield
    await close_redis()
    await close_redis_cache()


app = FastAPI(
    title="Smart Transport API",
    description="Real-time Public Transport Tracking & Density Prediction",
    version="1.0.0",
    lifespan=lifespan,
)
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
app.include_router(admin_users.router, prefix="/api/v1", tags=["admin"])
app.include_router(admin_dashboard.router, prefix="/api/v1", tags=["admin"])
app.include_router(tracking.router, prefix="/api/v1", tags=["tracking"])
app.include_router(gateway.router, prefix="/api/v1", tags=["gateway"])
app.include_router(users.router, prefix="/api/v1", tags=["users"])
app.include_router(vehicles.router, prefix="/api/v1", tags=["vehicles"])
app.include_router(routes.router, prefix="/api/v1", tags=["routes"])
app.include_router(assignments.router, prefix="/api/v1", tags=["assignments"])
app.include_router(admin.router, prefix="/api/v1", tags=["admin"])
app.include_router(websocket.router, prefix="/api/v1", tags=["websocket"])
app.include_router(search.router, prefix="/api/v1", tags=["search"])
app.include_router(favorites.router, prefix="/api/v1", tags=["favorites"])
app.include_router(notifications.router, prefix="/api/v1", tags=["notifications"])
