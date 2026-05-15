"""IP blocklist manager — add, remove, and query blocked IPs."""

import ipaddress
from pathlib import Path
from datetime import datetime, timezone

from app.core.config import get_settings


def _get_blocklist_path() -> Path:
    """Get the blocklist file path."""
    settings = get_settings()
    return Path(settings.BLOCKLIST_PATH)


def _ensure_file(path: Path) -> None:
    """Ensure the blocklist file exists."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Smart Transport API — IP Blocklist\n")
        path.write_text("# Format: IP|CIDR # optional comment\n")
        path.write_text("# Lines starting with # are ignored\n\n")


def add_ip(ip: str, reason: str = "manual", permanent: bool = True) -> bool:
    """
    Add an IP or CIDR range to the blocklist.

    Args:
        ip: IP address (e.g., "192.168.1.1") or CIDR range (e.g., "10.0.0.0/8")
        reason: Why the IP is being blocked
        permanent: If True, persists to file; if False, is temporary

    Returns:
        True if added successfully, False if invalid IP
    """
    # Validate IP/CIDR
    try:
        ipaddress.ip_network(ip, strict=False)
    except ValueError:
        return False

    path = _get_blocklist_path()
    _ensure_file(path)

    # Check if already blocked
    existing = list_blocked()
    if any(entry["ip"] == ip for entry in existing):
        return True

    timestamp = datetime.now(timezone.utc).isoformat()
    entry = f"{ip} # {reason} | {timestamp}"
    if not permanent:
        entry += " | temp"

    with open(path, "a") as f:
        f.write(entry + "\n")

    return True


def remove_ip(ip: str) -> bool:
    """
    Remove an IP from the blocklist.

    Returns:
        True if removed, False if not found
    """
    path = _get_blocklist_path()
    if not path.exists():
        return False

    lines = path.read_text().splitlines()
    new_lines = []
    found = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            new_lines.append(line)
            continue
        entry_ip = stripped.split("#")[0].strip()
        if entry_ip == ip:
            found = True
            continue
        new_lines.append(line)

    if found:
        path.write_text("\n".join(new_lines) + "\n")

    return found


def is_blocked(ip: str) -> bool:
    """Check if an IP matches any entry in the blocklist."""
    blocked = list_blocked()
    try:
        check_addr = ipaddress.ip_address(ip)
    except ValueError:
        return False

    for entry in blocked:
        try:
            network = ipaddress.ip_network(entry["ip"], strict=False)
            if check_addr in network:
                return True
        except ValueError:
            continue

    return False


def list_blocked() -> list[dict]:
    """List all blocked IPs with metadata."""
    path = _get_blocklist_path()
    if not path.exists():
        return []

    entries = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        parts = stripped.split("#", 1)
        ip = parts[0].strip()
        comment = parts[1].strip() if len(parts) > 1 else ""

        # Parse comment for metadata
        reason = "unknown"
        timestamp = ""
        permanent = True

        if "|" in comment:
            segments = [s.strip() for s in comment.split("|")]
            if segments:
                reason = segments[0]
            if len(segments) > 1:
                timestamp = segments[1]
            if len(segments) > 2 and "temp" in segments[2].lower():
                permanent = False

        entries.append({
            "ip": ip,
            "reason": reason,
            "timestamp": timestamp,
            "permanent": permanent,
        })

    return entries


def clear_all(confirm: bool = False) -> int:
    """
    Clear all blocklist entries.

    Args:
        confirm: Must be True to actually clear

    Returns:
        Number of entries cleared
    """
    if not confirm:
        return 0

    path = _get_blocklist_path()
    if not path.exists():
        return 0

    entries = list_blocked()
    _ensure_file(path)
    return len(entries)
