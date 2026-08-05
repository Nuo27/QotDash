"""Shared types, constants, and helpers for QotDash."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import __version__

HTTP_TIMEOUT = 20
BAR_WIDTH = 18
BLOCK = "\u2588"
EMPTY = "\u2591"
ANSI_RED = "\033[91m"
ANSI_YELLOW = "\033[93m"
ANSI_GREEN = "\033[92m"
ANSI_RESET = "\033[0m"
ANSI_DIM = "\033[2m"


@dataclass(frozen=True)
class ProviderConfig:
    label: str
    urls: tuple[str, ...]
    key_env: str


@dataclass(frozen=True)
class Quota:
    label: str
    provider: str
    plan: str
    name: str
    pct: float
    used: float | None
    total: float | None
    remaining: float | None
    resets_in: str | None
    resets_at_utc: str | None
    resets_at_local: str | None


def find_env_file(explicit: str | None, skip: bool) -> Path | None:
    if skip:
        return None
    if explicit:
        return Path(explicit)
    for candidate in (
        Path.cwd() / ".env",
        Path.home() / ".env",
        Path.home() / ".config" / "QotDash" / ".env",
    ):
        if candidate.is_file():
            return candidate
    return None


def load_env(path: Path) -> int:
    if not path.is_file():
        return 0
    loaded = 0
    try:
        with path.open("r", encoding="utf-8-sig") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                if key and key not in os.environ:
                    os.environ[key] = value
                    loaded += 1
    except OSError as err:
        print(f"warn: cannot read {path}: {err}", file=sys.stderr)
    return loaded


# Windows timezone display name -> IANA name. Covers the common cases.
# Used as fallback when `tzinfo.key` is unavailable (Windows without tzdata).
_WIN_TZ_TO_IANA = {
    "AUS Eastern Standard Time": "Australia/Sydney",
    "AUS Central Standard Time": "Australia/Adelaide",
    "Cen. Australia Standard Time": "Australia/Adelaide",
    "AUS Mountain Standard Time": "Australia/Darwin",
    "E. Australia Standard Time": "Australia/Brisbane",
    "AUS Western Standard Time": "Australia/Perth",
    "New Zealand Standard Time": "Pacific/Auckland",
    "Eastern Standard Time": "America/New_York",
    "Central Standard Time": "America/Chicago",
    "Mountain Standard Time": "America/Denver",
    "Pacific Standard Time": "America/Los_Angeles",
    "Alaskan Standard Time": "America/Anchorage",
    "Hawaiian Standard Time": "Pacific/Honolulu",
    "GMT Standard Time": "Europe/London",
    "W. Europe Standard Time": "Europe/Berlin",
    "Central Europe Standard Time": "Europe/Warsaw",
    "Romance Standard Time": "Europe/Paris",
    "E. Europe Standard Time": "Europe/Bucharest",
    "Russian Standard Time": "Europe/Moscow",
    "Turkey Standard Time": "Europe/Istanbul",
    "Israel Standard Time": "Asia/Jerusalem",
    "India Standard Time": "Asia/Kolkata",
    "China Standard Time": "Asia/Shanghai",
    "Singapore Standard Time": "Asia/Singapore",
    "Tokyo Standard Time": "Asia/Tokyo",
    "Korea Standard Time": "Asia/Seoul",
    "Hong Kong Standard Time": "Asia/Hong_Kong",
    "Taipei Standard Time": "Asia/Taipei",
    "SE Asia Standard Time": "Asia/Bangkok",
    "Arabian Standard Time": "Asia/Dubai",
    "Iran Standard Time": "Asia/Tehran",
    "Pakistan Standard Time": "Asia/Karachi",
    "Bangladesh Standard Time": "Asia/Dhaka",
    "Argentina Standard Time": "America/Argentina/Buenos_Aires",
    "Brazilian Standard Time": "America/Sao_Paulo",
    "SA Pacific Standard Time": "America/Bogota",
    "SA Western Standard Time": "America/La_Paz",
    "Mexico Standard Time": "America/Mexico_City",
    "Central America Standard Time": "America/Guatemala",
    "Atlantic Standard Time": "America/Halifax",
    "Newfoundland Standard Time": "America/St_Johns",
    "UTC": "UTC",
}


def detect_local_tz() -> str:
    """Return IANA name of the system's local timezone, fallback to UTC."""
    try:
        local_tz = datetime.now(timezone.utc).astimezone().tzinfo
        if hasattr(local_tz, "key") and local_tz.key:
            return local_tz.key
    except Exception:
        pass
    # Windows without tzdata: time.tzname[0] holds a Windows display name.
    import time
    win_name = time.tzname[0]
    if win_name in _WIN_TZ_TO_IANA:
        return _WIN_TZ_TO_IANA[win_name]
    return "UTC"


def resolve_tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        print(f"error: timezone {name!r} not found.", file=sys.stderr)
        print("On Windows + Python <3.13 install: py -3.10 -m pip install tzdata", file=sys.stderr)
        raise SystemExit(1)


def fmt_duration(seconds: int) -> str:
    if seconds <= 0:
        return "now"
    out: list[str] = []
    for unit, suffix in ((86400, "d"), (3600, "h"), (60, "m")):
        value, seconds = divmod(seconds, unit)
        if value:
            out.append(f"{value}{suffix}")
    if seconds:
        out.append(f"{seconds}s")
    return " ".join(out[:3])


def fmt_num(n: float | None) -> str:
    if n is None:
        return "-"
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if abs(n) >= 1_000:
        return f"{n / 1_000:.1f}k"
    return f"{n:g}"


def bar(pct: float, width: int = BAR_WIDTH, color: bool = True,
        warn: int = 70, critical: int = 90) -> str:
    pct = max(0.0, min(100.0, pct))
    fill = round(width * pct / 100)
    raw = BLOCK * fill + EMPTY * (width - fill)
    if not color:
        return raw
    code = ANSI_RED if pct >= critical else ANSI_YELLOW if pct >= warn else ANSI_GREEN
    return f"{code}{raw}{ANSI_RESET}"


def http_get(url: str, headers: dict[str, str]) -> dict:
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def auth_headers(key: str, provider: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {key}",
        "User-Agent": f"QotDash/{__version__} ({sys.platform}; {provider})",
    }