"""Kimi (Moonshot AI) quota provider."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from ..core import (
    ProviderConfig,
    Quota,
    auth_headers,
    http_get,
)
from . import register

CONFIG = ProviderConfig(
    label="Kimi",
    urls=("https://api.moonshot.ai/v1/users/me/balance",),
    key_env="MOONSHOT_API_KEY",
)


def _num(payload: dict, key: str) -> float | None:
    """Moonshot returns money as [number, "CNY"]; unwrap the number."""
    v = payload.get(key)
    if isinstance(v, list) and v:
        v = v[0]
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return None


def _parse(payload: dict) -> list[Quota]:
    data = payload.get("data", {})
    if not data:
        raise ValueError("Kimi response missing 'data' field")

    balance = _num(data, "balance") or 0.0
    total_usage = _num(data, "total_usage") or 0.0
    denom = balance + total_usage
    pct = 100.0 * total_usage / denom if denom > 0 else 0.0

    return [Quota(
        label=CONFIG.label,
        provider="moonshot",
        plan="balance",
        name="account-balance",
        pct=pct,
        used=total_usage,
        total=denom or None,
        remaining=balance,
        resets_in=None,
        resets_at_utc=None,
        resets_at_local=None,
    )]


@register("kimi", CONFIG)
def fetch(key: str, tz: ZoneInfo) -> list[Quota]:
    return _parse(http_get(CONFIG.urls[0], auth_headers(key, "moonshot")))
