"""MiniMax quota provider."""

from __future__ import annotations

import json
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ..core import (
    ProviderConfig,
    Quota,
    auth_headers,
    fmt_duration,
    http_get,
)
from . import register

CONFIG = ProviderConfig(
    label="MiniMax",
    urls=(
        "https://api.minimax.io/v1/token_plan/remains",
        "https://api.minimaxi.com/v1/token_plan/remains",
    ),
    key_env="MINIMAX_API_KEY",
)

# ponytail: XDG-style state, matches env fallback ~/.config/QotDash/
STATE_PATH = Path.home() / ".config" / "QotDash" / "state.json"
_AUTH_PLATFORM_CODES = {1004, 2049}


class _AuthError(ValueError):
    pass


def _slugify_model(name: str, limit: int = 14) -> str:
    """Turn 'model/Name-V2' into 'model-name-v2', truncated to `limit`."""
    slug = "".join(c if c.isalnum() or c == "-" else "-" for c in name.lower()).strip("-")
    return slug[:limit] or "model"


def _looks_like_auth_error(payload: dict) -> bool:
    base = payload.get("base_resp")
    return isinstance(base, dict) and base.get("status_code") in _AUTH_PLATFORM_CODES


def _load_state() -> dict:
    try:
        with STATE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with STATE_PATH.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except OSError:
        pass


def _parse(payload: dict, tz: ZoneInfo) -> list[Quota]:
    base = payload.get("base_resp")
    if isinstance(base, dict) and base.get("status_code") != 0:
        raise ValueError(f"MiniMax error {base.get('status_code')}: {base.get('status_msg')}")
    items = payload.get("model_remains")
    if isinstance(items, list):
        return _parse_per_model(items, tz)
    return _parse_flat(payload)


def _parse_per_model(items: list, tz: ZoneInfo) -> list[Quota]:
    out: list[Quota] = []
    now_utc = datetime.now(timezone.utc)
    for entry in items:
        if not isinstance(entry, dict):
            continue
        model = str(entry.get("model_name", "?"))
        compact = _slugify_model(model)
        r5 = entry.get("current_interval_remaining_percent")
        rw = entry.get("current_weekly_remaining_percent")
        t5 = entry.get("remains_time")
        tw = entry.get("weekly_remains_time")
        if isinstance(r5, (int, float)) and not isinstance(r5, bool):
            out.append(_make_quota(compact, "5h", 100.0 - float(r5), t5, now_utc, tz))
        if isinstance(rw, (int, float)) and not isinstance(rw, bool):
            out.append(_make_quota(compact, "weekly", 100.0 - float(rw), tw, now_utc, tz))
    if not out:
        raise ValueError("MiniMax per-model response missing quota fields")
    return out


def _parse_flat(payload: dict) -> list[Quota]:
    def num(key: str) -> float | None:
        v = payload.get(key)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    pairs = (
        ("5h-token", num("current_interval_usage_count"), num("current_interval_total_count")),
        ("weekly-token", num("current_weekly_usage_count"), num("current_weekly_total_count")),
    )
    out: list[Quota] = []
    for name, remaining, total in pairs:
        if remaining is None or total is None or total <= 0:
            continue
        used = max(total - remaining, 0.0)
        out.append(Quota(
            label=CONFIG.label,
            provider="minimax",
            plan="token-plan",
            name=name,
            pct=100.0 * used / total,
            used=used, total=total, remaining=remaining,
            resets_in=None, resets_at_utc=None, resets_at_local=None,
        ))
    if not out:
        raise ValueError("MiniMax flat response missing quota fields")
    return out


def _make_quota(model: str, window: str, pct: float, remains_ms,
                now_utc: datetime, tz: ZoneInfo) -> Quota:
    resets_in = resets_at_utc = resets_at_local = None
    if isinstance(remains_ms, (int, float)) and not isinstance(remains_ms, bool) and remains_ms > 0:
        seconds = int(remains_ms / 1000)
        resets_in = fmt_duration(seconds)
        dt = datetime.fromtimestamp(now_utc.timestamp() + seconds, tz=timezone.utc)
        resets_at_utc = dt.isoformat().replace("+00:00", "Z")
        resets_at_local = dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %Z")
    return Quota(
        label=CONFIG.label,
        provider="minimax",
        plan="token-plan",
        name=f"{model}/{window}",
        pct=pct, used=None, total=None, remaining=None,
        resets_in=resets_in, resets_at_utc=resets_at_utc, resets_at_local=resets_at_local,
    )


@register("minimax", CONFIG)
def fetch(key: str, tz: ZoneInfo) -> list[Quota]:
    state = _load_state()
    saved = state.get("minimax")
    urls = list(CONFIG.urls)
    if saved and saved in urls:
        urls.remove(saved)
        urls.insert(0, saved)

    payload: dict | None = None
    working_url: str | None = None
    for url in urls:
        try:
            payload = http_get(url, auth_headers(key, "minimax"))
        except urllib.error.HTTPError as err:
            if err.code not in (401, 403):
                raise
        else:
            if _looks_like_auth_error(payload):
                payload = None
            else:
                working_url = url
                break

    if payload is None or working_url is None:
        state.pop("minimax", None)
        _save_state(state)
        raise _AuthError("MiniMax auth failed on all endpoints")

    if state.get("minimax") != working_url:
        state["minimax"] = working_url
        _save_state(state)

    return _parse(payload, tz)