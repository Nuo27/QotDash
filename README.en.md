# QotDash

A small personal tool — coding plan quota monitor.

> The built-in Z.ai / MiniMax / Kimi providers are for testing and example only.

[中文版 →](./README.md)

## Usage

Fill in your API keys in `.env`:

```powershell
echo "ZAI_API_KEY=..." > .env
echo "MINIMAX_API_KEY=..." >> .env
```

Then open:

```
QotDash.cmd
```

Or run from a terminal with options:

```
QotDash --provider zai
QotDash -j --threshold 80
QotDash --tz Asia/Shanghai --watch 30
```

Requires Python 3.9+. On Windows, common timezones are auto-detected (41 IANA mappings); override with `--tz <IANA name>` for anything not covered.

## Options

| Flag                            | Description                                                       | Default                                          |
| ------------------------------- | ----------------------------------------------------------------- | ------------------------------------------------ |
| `--version`                     | Print version and exit                                            | —                                                |
| `--provider {zai,minimax,kimi}` | Query only one provider                                           | all (any with key set)                           |
| `-j`, `--json`                  | JSON output (one dict per quota)                                  | off                                              |
| `--inline`                      | One compact line per quota                                        | off                                              |
| `--no-color`                    | Disable ANSI color                                                | enabled when stdout is tty and `NO_COLOR` unset  |
| `--watch SEC` / `-w SEC`        | Refresh in place every N seconds (Ctrl-C to stop)                 | off                                              |
| `--threshold PCT` / `-t PCT`    | Exit 2 if any quota ≥ PCT                                         | off                                              |
| `--tz TZ`                       | Override auto-detected timezone (IANA name, e.g. `Asia/Shanghai`) | local                                            |
| `--tz-check`                    | Print resolved timezone and exit                                  | —                                                |
| `--no-env-file`                 | Skip `.env` loading                                               | —                                                |
| `--env-file PATH`               | Explicit path to `.env`                                           | `cwd/.env` → `~/.env` → `~/.config/QotDash/.env` |
| `--max-rows N`                  | Cap table rows                                                    | `6` (`0` = unlimited)                            |
| `--warn PCT`                    | Yellow threshold                                                  | `70`                                             |
| `--critical PCT`                | Red threshold (must be `> --warn`)                                | `90`                                             |

## Adding a provider

Drop a `.py` module under `QotDash/providers/`. Create a `ProviderConfig`,
implement `fetch(key, tz) -> list[Quota]`, decorate with `@register`.
Startup auto-discovers all submodules and calls them concurrently; cli /
core / render stay untouched.

### ProviderConfig

```python
@dataclass(frozen=True)
class ProviderConfig:
    label: str               # shown in the table's PROVIDER column
    urls: tuple[str, ...]    # GET endpoints, tried in order (use multiple for failover)
    key_env: str             # env var holding the API key; gather skips providers whose key isn't set
```

### Quota

`fetch` returns `list[Quota]`. An empty list is treated as an error
(CLI exits 1). Fields:

| Field             | Type            | Notes                                                                |
| ----------------- | --------------- | -------------------------------------------------------------------- |
| `label`           | `str`           | usually `CONFIG.label`                                               |
| `provider`        | `str`           | short id; used in JSON output and MiniMax state file                 |
| `plan`            | `str`           | plan name; `""` if unknown                                           |
| `name`            | `str`           | quota name (e.g. `"5h-token"`)                                       |
| `pct`             | `float`         | percent used, 0–100                                                  |
| `used`            | `float \| None` | amount used; `None` if unknown                                       |
| `total`           | `float \| None` | amount total; `None` if unknown                                      |
| `remaining`       | `float \| None` | amount remaining; `None` if unknown                                  |
| `resets_in`       | `str \| None`   | human-readable time to reset; format with `fmt_duration(seconds)`    |
| `resets_at_utc`   | `str \| None`   | reset time in UTC, ISO 8601 with `Z` (e.g. `"2026-01-01T00:00:00Z"`) |
| `resets_at_local` | `str \| None`   | reset time in user's tz (e.g. `"2026-01-01 08:00:00 CST"`)           |

### Helpers in core

- `http_get(url, headers) -> dict` — `urllib` wrapper, JSON-decoded, 20s timeout. Raises `urllib.error.HTTPError` / `URLError`.
- `auth_headers(key, provider) -> dict` — `Authorization: Bearer` + `User-Agent: QotDash/<ver>`.
- `fmt_duration(seconds) -> str` — e.g. `"1h 30m"`.
- `load_env` / `find_env_file` — `.env` loader (CLI already handles this, rarely needed in providers).

### Error conventions in `fetch`

- `ValueError` — business error (`success=false`, missing fields, empty list).
- `urllib.error.HTTPError` / `URLError` — network error.
- `json.JSONDecodeError` — response wasn't JSON.

CLI catches all of the above and prints `error: ...` to stderr with exit code 1.

### Full example

```python
# QotDash/providers/foo.py
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ..core import ProviderConfig, Quota, auth_headers, fmt_duration, http_get
from . import register

CONFIG = ProviderConfig(
    label="Foo",
    urls=("https://api.foo.com/v1/quota",),
    key_env="FOO_API_KEY",
)


@register("foo", CONFIG)
def fetch(key: str, tz: ZoneInfo) -> list[Quota]:
    payload = http_get(CONFIG.urls[0], auth_headers(key, "foo"))
    if not payload.get("ok"):
        raise ValueError(payload.get("error", "Foo returned ok=false"))

    now_utc = datetime.now(timezone.utc)
    out: list[Quota] = []

    for window in payload.get("windows", []):
        reset_ms = window.get("reset_at_ms")
        resets_in = resets_at_utc = resets_at_local = None
        if isinstance(reset_ms, (int, float)) and not isinstance(reset_ms, bool):
            dt = datetime.fromtimestamp(reset_ms / 1000, tz=timezone.utc)
            resets_in = fmt_duration(int((dt - now_utc).total_seconds()))
            resets_at_utc = dt.isoformat().replace("+00:00", "Z")
            resets_at_local = dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %Z")

        out.append(Quota(
            label=CONFIG.label,
            provider="foo",
            plan=str(window.get("plan", "")),
            name=str(window["name"]),
            pct=float(window["pct"]),
            used=window.get("used"),
            total=window.get("total"),
            remaining=window.get("remaining"),
            resets_in=resets_in,
            resets_at_utc=resets_at_utc,
            resets_at_local=resets_at_local,
        ))

    if not out:
        raise ValueError("Foo response contained no windows")
    return out
```

Drop it in `QotDash/providers/foo.py` and a `Foo` row appears in the next run.

## Layout

```
QotDash.py              # entry
QotDash.cmd             # Windows live dashboard
QotDash/
├── cli.py              # argparse, main loop, watch, threshold
├── core.py             # types, HTTP, env, tz, formatting
├── _console.py         # Windows ANSI/UTF-8 console enable
├── render.py           # table / inline / json output
└── providers/
    ├── zai.py
    ├── minimax.py
    └── kimi.py
```
