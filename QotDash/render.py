"""Output renderers for QotDash."""

from __future__ import annotations

import json
from typing import Iterable

from .core import BAR_WIDTH, Quota, bar, fmt_num

HEADERS = ["PROVIDER", "PLAN", "QUOTA", "USED", "BAR", "USED/TOTAL", "RESETS IN", "RESETS AT"]
BAR_COL = 4
ROW_COUNT = 6


def _row_cells(q: Quota, color: bool, warn: int, critical: int) -> list[str]:
    used_total = (
        f"{fmt_num(q.used)}/{fmt_num(q.total)}"
        if q.used is not None and q.total is not None
        else "-"
    )
    return [
        q.label,
        q.plan or "-",
        q.name,
        f"{q.pct:.0f}%",
        bar(q.pct, BAR_WIDTH, color, warn, critical),
        used_total,
        q.resets_in or "-",
        q.resets_at_local or "-",
    ]


def render_table(
    quotas: Iterable[Quota],
    color: bool,
    status: str | None = None,
    max_rows: int = ROW_COUNT,
    warn: int = 70,
    critical: int = 90,
) -> list[str]:
    """Return fixed-size lines: header + rule + max_rows rows + status.

    Column widths auto-size to content; BAR column stays BAR_WIDTH. All
    lines (header/rule/data) use the same widths so columns align.
    """
    quotas = list(quotas)
    col_widths = [len(h) for h in HEADERS]

    rows_iter = quotas if max_rows <= 0 else quotas[:max_rows]
    rows = [_row_cells(q, color, warn, critical) for q in rows_iter]
    for cells in rows:
        for i, c in enumerate(cells):
            if i != BAR_COL and len(c) > col_widths[i]:
                col_widths[i] = len(c)

    def fmt(values: list[str]) -> str:
        return "  ".join(
            v.ljust(col_widths[i]) if i != BAR_COL else v
            for i, v in enumerate(values)
        ).rstrip()

    lines = [fmt(HEADERS), fmt(["-" * (BAR_WIDTH if i == BAR_COL else w) for i, w in enumerate(col_widths)])]
    lines.extend(fmt(cells) for cells in rows)

    while len(lines) < 2 + max_rows:
        lines.append("")

    if status is not None:
        lines.append(status)
    elif quotas:
        lines.append(f"loaded {len(quotas)} quotas")
    else:
        lines.append("(no quotas)")

    return lines


def render_inline(quotas: Iterable[Quota]) -> list[str]:
    return [
        f"{q.label}/{q.plan}: {q.name} {q.pct:.0f}% "
        f"({fmt_num(q.remaining)} left, {q.resets_in or 'no reset'})"
        for q in quotas
    ]


def render_json(quotas: Iterable[Quota]) -> str:
    return json.dumps(
        [
            {
                "provider": q.provider,
                "label": q.label,
                "plan": q.plan,
                "name": q.name,
                "pct_used": q.pct,
                "used": q.used,
                "total": q.total,
                "remaining": q.remaining,
                "resets_in": q.resets_in,
                "resets_at_utc": q.resets_at_utc,
                "resets_at_local": q.resets_at_local,
            }
            for q in quotas
        ],
        indent=2,
    )