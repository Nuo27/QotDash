"""CLI and orchestration for QotDash."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import __version__
from ._console import enable as enable_console
from .core import Quota, detect_local_tz, find_env_file, load_env, resolve_tz
from .providers import all_providers
from .render import render_inline, render_json, render_table


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="QotDash",
        description="Terminal quota monitor.",
    )
    parser.add_argument("--version", action="version", version=f"QotDash {__version__}")
    parser.add_argument(
        "--provider", choices=tuple(all_providers()),
        help="limit to one provider (default: fetch all with keys present)",
    )
    parser.add_argument("-j", "--json", action="store_true", help="JSON output")
    parser.add_argument("--inline", action="store_true", help="one compact line per quota")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI color")
    parser.add_argument(
        "--watch", "-w", type=int, metavar="SEC", default=None,
        help="refresh every N seconds (Ctrl-C to stop)",
    )
    parser.add_argument(
        "--threshold", "-t", type=float, metavar="PCT", default=None,
        help="exit 2 if any quota >= PCT",
    )
    parser.add_argument("--tz", default=None, help="override timezone (default: auto-detect local)")
    parser.add_argument("--tz-check", action="store_true", help="print resolved timezone and exit")
    parser.add_argument("--no-env-file", action="store_true", help="skip .env loading")
    parser.add_argument("--env-file", default=None, help="explicit path to .env")
    parser.add_argument(
        "--max-rows", type=int, metavar="N", default=6,
        help="max table rows (default: 6, 0 = unlimited)",
    )
    parser.add_argument(
        "--warn", type=int, metavar="PCT", default=70,
        help="yellow bar threshold (default: 70)",
    )
    parser.add_argument(
        "--critical", type=int, metavar="PCT", default=90,
        help="red bar threshold (default: 90)",
    )
    return parser.parse_args(argv)


def gather(args: argparse.Namespace) -> list[Quota]:
    providers = all_providers()
    if args.provider:
        names = [args.provider]
    else:
        names = [n for n, (cfg, _) in providers.items() if os.getenv(cfg.key_env)]
        if not names:
            keys = ", ".join(cfg.key_env for cfg, _ in providers.values())
            print(f"error: no provider keys set (set one of: {keys})", file=sys.stderr)
            raise SystemExit(1)

    tz_name = args.tz or detect_local_tz()
    tz = resolve_tz(tz_name)

    def fetch_one(name: str) -> list[Quota]:
        cfg, fetch_fn = providers[name]
        if not os.getenv(cfg.key_env):
            print(f"warn: skipping {name}: {cfg.key_env} not set", file=sys.stderr)
            return []
        return fetch_fn(os.environ[cfg.key_env], tz)

    with ThreadPoolExecutor(max_workers=max(1, len(names))) as ex:
        results = list(ex.map(fetch_one, names))

    out: list[Quota] = []
    for r in results:
        out.extend(r)
    return out


def _countdown(seconds: int) -> None:
    """Real-time countdown, overwriting the status line in place.

    Cursor is on the status line when this is called (run_once leaves it
    there). Trailing newline parks the cursor one line below so the next
    iteration's cursor-up lands cleanly on the header line.
    """
    for remaining in range(seconds, 0, -1):
        sys.stdout.write(f"\rrefresh in {remaining}s    ")
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write("\n")
    sys.stdout.flush()


def run_once(
    args: argparse.Namespace,
    color: bool,
    status: str | None = None,
    warn: int = 70,
    critical: int = 90,
    max_rows: int = 6,
) -> int:
    try:
        quotas = gather(args)
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace").strip()
        print(f"error: HTTP {err.code} {err.reason}", file=sys.stderr)
        if body:
            print(body, file=sys.stderr)
        return 1
    except urllib.error.URLError as err:
        print(f"error: network: {err.reason}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as err:
        print(f"error: invalid JSON from API: {err}", file=sys.stderr)
        return 1
    except ValueError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    if not quotas:
        print("(no quotas returned)", file=sys.stderr)
        return 1

    if args.json:
        out = render_json(quotas)
        nlines = out.count(chr(10)) + 1
    elif args.inline:
        lines = render_inline(quotas)
        out = "\n".join(lines)
        nlines = len(lines)
    else:
        lines = render_table(quotas, color, status=status, max_rows=max_rows, warn=warn, critical=critical)
        out = "\n".join(lines)
        nlines = len(lines)

    if args.watch:
        sys.stdout.write(f"\033[{nlines}A")
        sys.stdout.flush()
    sys.stdout.write(out)
    # In watch mode, leave cursor on the last line (status) so _countdown
    # can overwrite it in place. Single-shot mode ends with a newline.
    if not args.watch:
        sys.stdout.write("\n")
    sys.stdout.flush()

    if args.threshold is not None and any(q.pct >= args.threshold for q in quotas):
        return 2
    return 0


def tz_check(args: argparse.Namespace) -> int:
    name = args.tz or detect_local_tz()
    try:
        tz = resolve_tz(name)
    except SystemExit:
        return 1
    now = datetime.now(tz=tz)
    print(f"timezone:  {name}")
    print(f"resolved:  {tz}")
    print(f"now:       {now.isoformat()}")
    print(f"utc_off:   {now.utcoffset()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    enable_console()
    args = parse_args(argv)
    if args.watch is not None and args.watch < 1:
        print("error: --watch must be >= 1", file=sys.stderr)
        return 1
    if args.threshold is not None and not 0 <= args.threshold <= 100:
        print("error: --threshold must be 0..100", file=sys.stderr)
        return 1
    if not 0 <= args.warn <= 100 or not 0 <= args.critical <= 100:
        print("error: --warn/--critical must be 0..100", file=sys.stderr)
        return 1
    if args.warn >= args.critical:
        print("error: --warn must be < --critical", file=sys.stderr)
        return 1

    env_path = find_env_file(args.env_file, args.no_env_file)
    if env_path:
        loaded = load_env(env_path)
        if loaded and not args.watch:
            print(f"(loaded {loaded} key(s) from {env_path})", file=sys.stderr)

    if args.tz_check:
        return tz_check(args)

    color = not args.no_color and sys.stdout.isatty() and not os.getenv("NO_COLOR")
    watch = args.watch

    if watch:
        while True:
            code = run_once(args, color, status=f"refresh in {watch}s",
                            warn=args.warn, critical=args.critical, max_rows=args.max_rows)
            if code != 0:
                print()
                return code
            _countdown(watch)

    return run_once(args, color, warn=args.warn, critical=args.critical, max_rows=args.max_rows)