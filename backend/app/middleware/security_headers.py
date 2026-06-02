"""Enhanced security headers middleware — CSP, HSTS, referrer policy, and more."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Add comprehensive security headers to every response.

    Headers applied:
      - Strict-Transport-Security (HSTS) — force HTTPS
      - Content-Security-Policy — prevent XSS/data injection
      - X-Content-Type-Options — prevent MIME sniffing
      - X-Frame-Options — prevent clickjacking
      - X-XSS-Protection — legacy XSS filter
      - Referrer-Policy — control referrer leakage
      - Permissions-Policy — restrict browser feature access
      - Cross-Origin-Opener-Policy — isolate browsing context
      - Cross-Origin-Resource-Policy — control cross-origin loading
      - Cache-Control for API responses — prevent caching sensitive data
    """

    def __init__(self, app):
        super().__init__(app)
        self._hsts_max_age = get_settings().HSTS_MAX_AGE

    # Content-Security-Policy for API (restrictive — APIs serve JSON, not HTML)
    CSP_POLICY = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"

    # Referrer policy: no referrer for API responses
    REFERRER_POLICY = "no-referrer"

    # Permissions policy: disable all browser features for API
    PERMISSIONS_POLICY = "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()"

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Transport security — force HTTPS
        response.headers["Strict-Transport-Security"] = (
            f"max-age={self._hsts_max_age}; includeSubDomains; preload"
        )

        # Content Security Policy
        response.headers["Content-Security-Policy"] = self.CSP_POLICY

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # Legacy XSS protection (defense in depth)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Control referrer information leakage
        response.headers["Referrer-Policy"] = self.REFERRER_POLICY

        # Restrict browser feature access
        response.headers["Permissions-Policy"] = self.PERMISSIONS_POLICY

        # Cross-origin isolation
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"

        # Prevent caching of API responses
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = (
                "no-store, no-cache, must-revalidate, max-age=0"
            )
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

        # Remove server identification headers
        if "server" in response.headers:
            del response.headers["server"]
        response.headers["Server"] = "SmartTransport"

        return response
