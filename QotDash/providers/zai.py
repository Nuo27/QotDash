"""Z.ai quota provider."""

from __future__ import annotations

from datetime import datetime, timezone
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
    label="Z.ai",
    urls=("https://api.z.ai/api/monitor/usage/quota/limit",),
    key_env="ZAI_API_KEY",
)


def _quota_name(item: dict) -> str:
    kind = item.get("type")
    if kind == "TOKENS_LIMIT" and item.get("unit") == 3 and item.get("number") == 5:
        return "5h-token"
    if kind == "TOKENS_LIMIT" and item.get("unit") == 6 and item.get("number") == 1:
        return "weekly-token"
    if kind == "TIME_LIMIT":
        return "tool-search"
    return f"unknown({kind})"


@register("zai", CONFIG)
def fetch(key: str, tz: ZoneInfo) -> list[Quota]:
    payload = http_get(CONFIG.urls[0], auth_headers(key, "zai"))
    if not payload.get("success"):
        raise ValueError(str(payload.get("msg", "Z.ai returned success=false")))
    data = payload.get("data") or {}
    plan = str(data.get("level", "?"))
    now_utc = datetime.now(timezone.utc)
    out: list[Quota] = []
    for item in data.get("limits", []) or []:
        if not isinstance(item, dict):
            continue
        pct_raw = item.get("percentage")
        pct = float(pct_raw) if isinstance(pct_raw, (int, float)) and not isinstance(pct_raw, bool) else 0.0
        used_raw = item.get("currentValue")
        total_raw = item.get("usage")
        rem_raw = item.get("remaining")
        reset_raw = item.get("nextResetTime")
        resets_in = resets_at_utc = resets_at_local = None
        if isinstance(reset_raw, (int, float)) and not isinstance(reset_raw, bool):
            dt = datetime.fromtimestamp(reset_raw / 1000, tz=timezone.utc)
            resets_in = fmt_duration(int((dt - now_utc).total_seconds()))
            resets_at_utc = dt.isoformat().replace("+00:00", "Z")
            resets_at_local = dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %Z")
        out.append(Quota(
            label=CONFIG.label,
            provider="zai",
            plan=plan,
            name=_quota_name(item),
            pct=pct,
            used=float(used_raw) if isinstance(used_raw, (int, float)) and not isinstance(used_raw, bool) else None,
            total=float(total_raw) if isinstance(total_raw, (int, float)) and not isinstance(total_raw, bool) else None,
            remaining=float(rem_raw) if isinstance(rem_raw, (int, float)) and not isinstance(rem_raw, bool) else None,
            resets_in=resets_in,
            resets_at_utc=resets_at_utc,
            resets_at_local=resets_at_local,
        ))
    if not out:
        raise ValueError("Z.ai response has no quota items")
    return out