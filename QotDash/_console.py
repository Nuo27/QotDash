"""Windows console helpers: enable VT100 escapes and UTF-8 output.

No-op on non-Windows. Idempotent. Call once at the top of CLI entry.
"""

from __future__ import annotations

import os
import sys


def enable() -> None:
    """Enable ANSI escape processing and UTF-8 encoding on Windows console."""
    if sys.platform != "win32":
        return
    os.system("")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass