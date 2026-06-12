"""Request validation middleware — body size limits, content-type enforcement, method checks."""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import Message

class RequestValidationMiddleware(BaseHTTPMiddleware):
    """
    Validates incoming requests and ensures the body stream is preserved
    for downstream FastAPI route handlers.
    """

    MAX_BODY_SIZES = {
        "application/json": 1_048_576,
        "application/x-www-form-urlencoded": 524_288,
        "multipart/form-data": 10_485_760,
        "text/plain": 262_144,
    }
    DEFAULT_MAX_BODY = 524_288
    METHODS_REQUIRE_CONTENT_TYPE = {"POST", "PUT", "PATCH"}
    ALLOWED_CONTENT_TYPES = {
        "application/json",
        "application/x-www-form-urlencoded",
        "multipart/form-data",
    }
    BODY_LIMIT_EXEMPT_PATHS = {"/api/v1/vehicles/telemetry"}

    async def dispatch(self, request: Request, call_next):
        # 1. Read and buffer the body stream
        body_bytes = await request.body()
        
        # 2. Re-inject the body into the request
        # This creates a custom 'receive' function that FastAPI will use
        # to read the body instead of the already-drained original stream.
        async def receive() -> Message:
            return {"type": "http.request", "body": body_bytes, "more_body": False}
        
        request._receive = receive

        # 3. Validation Logic (now using the buffered body_bytes)
        path = request.url.path
        method = request.method
        content_type = request.headers.get("content-type", "")
        body_length = len(body_bytes)

        if method in self.METHODS_REQUIRE_CONTENT_TYPE:
            if not content_type:
                return JSONResponse(status_code=400, content={"detail": "Missing Content-Type"})

            if content_type not in self.ALLOWED_CONTENT_TYPES:
                return JSONResponse(
                    status_code=415,
                    content={"detail": "Unsupported Media Type", "allowed": list(self.ALLOWED_CONTENT_TYPES)},
                )

            if path not in self.BODY_LIMIT_EXEMPT_PATHS:
                max_size = self.MAX_BODY_SIZES.get(content_type.split(';')[0], self.DEFAULT_MAX_BODY)
                if body_length > max_size:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Request body too large", "max_bytes": max_size},
                    )

        # 4. Path traversal and security checks
        if "\x00" in path or ".." in path or "%25" in path:
            return JSONResponse(status_code=400, content={"detail": "Invalid request path"})

        # 5. Proceed with the request
        return await call_next(request)