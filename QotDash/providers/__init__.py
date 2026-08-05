"""Provider registry with auto-discovery."""

from __future__ import annotations

import importlib
import pkgutil
from typing import Callable

from zoneinfo import ZoneInfo

from ..core import ProviderConfig, Quota

FetcherFn = Callable[[str, ZoneInfo], list[Quota]]

_FETCHERS: dict[str, tuple[ProviderConfig, FetcherFn]] = {}


def register(name: str, config: ProviderConfig) -> Callable[[FetcherFn], FetcherFn]:
    def decorator(fn: FetcherFn) -> FetcherFn:
        _FETCHERS[name] = (config, fn)
        return fn
    return decorator


def all_providers() -> dict[str, tuple[ProviderConfig, FetcherFn]]:
    return dict(_FETCHERS)


def _import_submodules() -> None:
    for module_info in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{module_info.name}")


_import_submodules()
