# QotDash

个人随手写的小工具，coding plan配额监控。

> 内置 Z.ai / MiniMax / Kimi provider 仅作测试和示例。

## 使用方法

在 `.env` 填入对应的变量名和你的 API Key，例如：

```powershell
echo "ZAI_API_KEY=..." > .env
echo "MINIMAX_API_KEY=..." >> .env
```

然后打开：

```
QotDash.cmd
```

或者带参数在终端运行：

```
QotDash --provider zai
QotDash -j --threshold 80
QotDash --tz Asia/Shanghai --watch 30
```

依赖 Python 3.9+。Windows 自动检测常见时区（41 条 IANA 映射）；不覆盖的可用 `--tz Asia/Shanghai` 显式指定。

## 参数

| 参数                            | 说明                                            | 默认                                             |
| ------------------------------- | ----------------------------------------------- | ------------------------------------------------ |
| `--version`                     | 打印版本并退出                                  | —                                                |
| `--provider {zai,minimax,kimi}` | 只查一个 provider                               | 全部（有 key 的自动跑）                          |
| `-j`, `--json`                  | 输出 JSON（每 quota 一个 dict）                 | 关闭                                             |
| `--inline`                      | 每 quota 一行紧凑格式                           | 关闭                                             |
| `--no-color`                    | 关闭 ANSI 颜色                                  | `stdout` 是 tty 且 `NO_COLOR` 未设置             |
| `--watch SEC` / `-w SEC`        | 每 N 秒原地刷新（Ctrl-C 中断）                  | 关闭                                             |
| `--threshold PCT` / `-t PCT`    | 任一 quota ≥ PCT 时退出码 2                     | 关闭                                             |
| `--tz TZ`                       | 覆盖自动检测时区（IANA 名，如 `Asia/Shanghai`） | 本地                                             |
| `--tz-check`                    | 打印解析时区并退出                              | —                                                |
| `--no-env-file`                 | 跳过 .env 加载                                  | —                                                |
| `--env-file PATH`               | 显式指定 .env 路径                              | `cwd/.env` → `~/.env` → `~/.config/QotDash/.env` |
| `--max-rows N`                  | 表格最多 N 行                                   | `6`（`0` = 不截断）                              |
| `--warn PCT`                    | 黄色阈值                                        | `70`                                             |
| `--critical PCT`                | 红色阈值（必须 `> --warn`）                     | `90`                                             |

## 加 provider

在 `QotDash/providers/` 下放一个 `.py` 新建一个 `ProviderConfig`、实现 `fetch(key, tz) -> list[Quota]`，用 `@register` 装饰。启动时自动扫描、并发调用，cli / core / render 都不用动。

### ProviderConfig

```python
@dataclass(frozen=True)
class ProviderConfig:
    label: str               # 表格 PROVIDER 列显示名
    urls: tuple[str, ...]    # GET endpoint 列表，按顺序尝试（多 endpoint 时用于容灾）
    key_env: str             # API Key 的环境变量名；gather 据此跳过没 key 的 provider
```

### Quota

每次 `fetch` 返回 `list[Quota]`，空列表视为错误（CLI 退出码 1）。字段：

| 字段              | 类型            | 说明                                                           |
| ----------------- | --------------- | -------------------------------------------------------------- |
| `label`           | `str`           | 通常 = `CONFIG.label`                                          |
| `provider`        | `str`           | 短标识；JSON 输出和 MiniMax 状态文件的 key                     |
| `plan`            | `str`           | 套餐名；未知填 `""`                                            |
| `name`            | `str`           | quota 名（如 `"5h-token"`）                                    |
| `pct`             | `float`         | 已用百分比，0–100                                              |
| `used`            | `float \| None` | 已用量；不知道就 `None`                                        |
| `total`           | `float \| None` | 总量；不知道就 `None`                                          |
| `remaining`       | `float \| None` | 剩余量；不知道就 `None`                                        |
| `resets_in`       | `str \| None`   | 距重置时长（人读），用 `fmt_duration(seconds)` 格式化          |
| `resets_at_utc`   | `str \| None`   | 重置 UTC 时间，ISO 8601 加 `Z`（如 `"2026-01-01T00:00:00Z"`）  |
| `resets_at_local` | `str \| None`   | 重置本地时间，按 `tz` 格式化（如 `"2026-01-01 08:00:00 CST"`） |

### core 里的可用工具

- `http_get(url, headers) -> dict` — `urllib` 包装，自动 JSON decode，超时 20s，失败抛 `urllib.error.HTTPError` / `URLError`
- `auth_headers(key, provider) -> dict` — `Authorization: Bearer` + `User-Agent: QotDash/<ver>`
- `fmt_duration(seconds) -> str` — 秒数转 `"1h 30m"`
- `load_env(path)` / `find_env_file(...)` — `.env` 加载（一般不用，CLI 已经处理）

### fetch 的错误约定

- `ValueError` — 业务错误（API 返回 `success=false`、JSON 缺字段、空列表）
- `urllib.error.HTTPError` / `URLError` — 网络错误
- `json.JSONDecodeError` — 响应不是 JSON

CLI 会统一转 `error: ...` 打印到 stderr，返回退出码 1。

### 完整示例

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

丢进 `QotDash/providers/foo.py`，启动 `QotDash` 就能看到 `Foo` 一行。

## 目录

```
QotDash.py              # 入口
QotDash.cmd             # Windows 实时仪表盘
QotDash/
├── cli.py              # 参数、主循环
├── core.py             # 类型、HTTP、env、格式化
├── _console.py         # Windows ANSI/UTF-8 控制台启用
├── render.py           # table / inline / json 渲染
└── providers/
    ├── zai.py
    ├── minimax.py
    └── kimi.py
```
