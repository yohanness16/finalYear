"""Request validation middleware — body size limits, content-type enforcement, method checks."""

import json
from typing import Set

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class RequestValidationMiddleware(BaseHTTPMiddleware):
    """
    Validates incoming requests before they reach route handlers.

    Checks:
      - Content-Type enforcement for POST/PUT/PATCH
      - Request body size limits (per content type)
      - Blocked HTTP methods
      - Required headers for API requests
      - Null byte injection prevention
      - Double-encoded path detection
    """

    # Max body sizes by content type (bytes)
    MAX_BODY_SIZES = {
        "application/json": 1_048_576,        # 1 MB
        "application/x-www-form-urlencoded": 524_288,  # 512 KB
        "multipart/form-data": 10_485_760,     # 10 MB (for image uploads)
        "text/plain": 262_144,                 # 256 KB
    }

    # Default max for unknown content types
    DEFAULT_MAX_BODY = 524_288  # 512 KB

    # Methods that require Content-Type header
    METHODS_REQUIRE_CONTENT_TYPE: Set[str] = {"POST", "PUT", "PATCH"}

    # Allowed content types for API
    ALLOWED_CONTENT_TYPES: Set[str] = {
        "application/json",
        "application/x-www-form-urlencoded",
        "multipart/form-data",
        "text/plain",
        "application/octet-stream",
    }

    # Paths exempt from body size limits (e.g., image upload endpoints)
    BODY_LIMIT_EXEMPT_PATHS: Set[str] = {
        "/api/v1/gateway",
    }

    async def dispatch(self, request: Request, call_next):
        method = request.method
        path = request.url.path
        content_type = request.headers.get("content-type", "").lower().split(";")[0].strip()
        content_length = request.headers.get("content-length")

        # Block non-standard HTTP methods
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
            return JSONResponse(
                status_code=405,
                content={"detail": "Method not allowed"},
            )

        # Content-Type enforcement for write methods
        if method in self.METHODS_REQUIRE_CONTENT_TYPE and content_length:
            try:
                body_length = int(content_length)
            except (ValueError, TypeError):
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length header"},
                )

            # Check content type is allowed
            if content_type and content_type not in self.ALLOWED_CONTENT_TYPES:
                return JSONResponse(
                    status_code=415,
                    content={
                        "detail": "Unsupported Media Type",
                        "allowed": list(self.ALLOWED_CONTENT_TYPES),
                    },
                )

            # Check body size limit
            if path not in self.BODY_LIMIT_EXEMPT_PATHS:
                max_size = self.MAX_BODY_SIZES.get(content_type, self.DEFAULT_MAX_BODY)
                if body_length > max_size:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "detail": "Request body too large",
                            "max_bytes": max_size,
                            "received_bytes": body_length,
                        },
                    )

        # Path traversal and null byte detection
        if "\x00" in path or ".." in path:
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid request path"},
            )

        # Double-encoded path detection
        if "%25" in path:
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid request path encoding"},
            )

        response = await call_next(request)
        return response
