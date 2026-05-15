"""Custom firewall middleware — IP blocklisting, request pattern detection, and anomaly scoring."""

import ipaddress
import time
from collections import defaultdict
from pathlib import Path
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import get_settings


class FirewallMiddleware(BaseHTTPMiddleware):
    """
    Multi-layer firewall that sits before rate limiting.

    Layers:
      1. IP blocklist — static list + auto-ban on abuse
      2. Private/internal network blocking for public endpoints
      3. Request pattern analysis — detects scanners, bots, slowloris
      4. Per-IP anomaly scoring — auto-ban when threshold exceeded
      5. Path-based rules — stricter limits on sensitive endpoints
    """

    # Paths that should never be accessed from non-private IPs
    SENSITIVE_PATHS = {"/docs", "/redoc", "/openapi.json"}

    # Paths exempt from firewall (health checks, static)
    EXEMPT_PATHS = {"/health", "/favicon.ico"}

    # Anomaly score thresholds
    AUTO_BAN_THRESHOLD = 100
    AUTO_BAN_WINDOW_SECONDS = 300  # 5 minutes
    AUTO_BAN_DURATION_SECONDS = 3600  # 1 hour

    # Max requests per IP in a 10-second window before flagging
    BURST_THRESHOLD = 50
    BURST_WINDOW_SECONDS = 10

    # Suspicious user-agent patterns (scanners, bots)
    BLOCKED_UA_PATENS = [
        "sqlmap",
        "nikto",
        "nmap",
        "masscan",
        "dirbuster",
        "gobuster",
        "wfuzz",
        "burpsuite",
        "metasploit",
        "hydra",
        "openvas",
        "nessus",
        "arachni",
        "w3af",
        "skipfish",
        "zgrab",
        "masscan",
    ]

    def __init__(self, app, blocklist_path: str | None = None):
        super().__init__(app)
        self.settings = get_settings()

        # Static IP blocklist loaded from file
        self._static_blocklist: set[str] = set()
        self._blocklist_path = blocklist_path or str(
            Path(__file__).resolve().parents[2] / "storage" / "firewall_blocklist.txt"
        )
        self._load_blocklist()

        # Dynamic auto-ban store: ip -> ban_expiry_timestamp
        self._auto_bans: dict[str, float] = {}

        # Request tracking: ip -> list of timestamps
        self._request_log: dict[str, list[float]] = defaultdict(list)

        # Anomaly scores: ip -> score
        self._anomaly_scores: dict[str, int] = defaultdict(int)

        # Suspicious pattern counters: ip -> count
        self._suspicious_counts: dict[str, int] = defaultdict(int)

        self._lock = Lock()

    def _load_blocklist(self) -> None:
        """Load static IP blocklist from file."""
        path = Path(self._blocklist_path)
        if path.exists():
            for line in path.read_text().splitlines():
                line = line.strip()
                line = line.split("#")[0].strip()
                if line:
                    self._static_blocklist.add(line)

    def _is_blocked_ip(self, ip: str) -> bool:
        """Check if IP is in static blocklist or auto-banned."""
        if ip in self._static_blocklist:
            return True
        if ip in self._auto_bans:
            if time.time() < self._auto_bans[ip]:
                return True
            del self._auto_bans[ip]
        return False

    def _is_private_ip(self, ip: str) -> bool:
        """Check if IP is from a private/internal range."""
        try:
            return ipaddress.ip_address(ip).is_private
        except ValueError:
            return False

    def _check_user_agent(self, ua: str) -> bool:
        """Return True if user-agent matches known malicious patterns."""
        ua_lower = ua.lower()
        return any(pattern in ua_lower for pattern in self.BLOCKED_UA_PATENS)

    def _record_request(self, ip: str) -> dict:
        """Record request and return anomaly analysis."""
        now = time.time()
        with self._lock:
            log = self._request_log[ip]
            log.append(now)
            # Prune old entries
            cutoff = now - self.AUTO_BAN_WINDOW_SECONDS
            self._request_log[ip] = [t for t in log if t > cutoff]
            total_in_window = len(self._request_log[ip])

            # Burst detection
            burst_cutoff = now - self.BURST_WINDOW_SECONDS
            burst_count = sum(1 for t in log if t > burst_cutoff)

        return {
            "total_in_window": total_in_window,
            "burst_count": burst_count,
        }

    def _auto_ban(self, ip: str) -> None:
        """Auto-ban an IP for the configured duration."""
        with self._lock:
            self._auto_bans[ip] = time.time() + self.AUTO_BAN_DURATION_SECONDS

    def _add_anomaly_score(self, ip: str, points: int) -> None:
        """Add anomaly points to an IP. Auto-ban if threshold exceeded."""
        with self._lock:
            self._anomaly_scores[ip] += points
            if self._anomaly_scores[ip] >= self.AUTO_BAN_THRESHOLD:
                self._auto_ban(ip)
                del self._anomaly_scores[ip]

    def _get_client_ip(self, request: Request) -> str:
        """Extract real client IP, respecting X-Forwarded-For."""
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
        if request.client:
            return request.client.host
        return "unknown"

    async def dispatch(self, request: Request, call_next):
        ip = self._get_client_ip(request)
        path = request.url.path
        ua = request.headers.get("user-agent", "")

        # Skip exempt paths
        if path in self.EXEMPT_PATHS:
            return await call_next(request)

        # Layer 1: Static + auto-ban blocklist
        if self._is_blocked_ip(ip):
            return JSONResponse(
                status_code=403,
                content={"detail": "Forbidden", "reason": "ip_blocked"},
            )

        # Layer 2: Sensitive path protection
        if path in self.SENSITIVE_PATHS and not self._is_private_ip(ip):
            self._add_anomaly_score(ip, 10)
            return JSONResponse(
                status_code=403,
                content={"detail": "Forbidden", "reason": "sensitive_endpoint"},
            )

        # Layer 3: User-agent analysis
        if ua and self._check_user_agent(ua):
            self._add_anomaly_score(ip, 25)
            self._suspicious_counts[ip] += 1
            if self._suspicious_counts[ip] >= 3:
                self._auto_ban(ip)
            return JSONResponse(
                status_code=403,
                content={"detail": "Forbidden", "reason": "blocked_user_agent"},
            )

        # Layer 4: Request pattern analysis
        stats = self._record_request(ip)

        # Burst detection — flag rapid requests
        if stats["burst_count"] > self.BURST_THRESHOLD:
            self._add_anomaly_score(ip, 15)

        # High volume detection
        if stats["total_in_window"] > 500:
            self._add_anomaly_score(ip, 20)

        # Check if auto-banned during this request
        if self._is_blocked_ip(ip):
            return JSONResponse(
                status_code=403,
                content={"detail": "Forbidden", "reason": "auto_banned"},
            )

        response = await call_next(request)

        # Layer 5: Response-based anomaly scoring
        if response.status_code == 404:
            self._add_anomaly_score(ip, 1)  # Path scanning
        elif response.status_code == 401 or response.status_code == 403:
            self._add_anomaly_score(ip, 3)  # Auth probing
        elif response.status_code == 429:
            self._add_anomaly_score(ip, 5)  # Already rate-limited once

        return response
