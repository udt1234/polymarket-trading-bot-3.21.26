"""Strategy plugin registry.

Auto-discovers every Strategy subclass in this package. Adding a new strategy
= drop a file in strategies/ that subclasses Strategy. The module dispatches
based on the `name` class attribute (looked up via REGISTRY).

REGISTRY itself is defined in base.py so __init_subclass__ can populate it
without an import-order race.
"""
from __future__ import annotations
import importlib
import pkgutil
from .base import Strategy, REGISTRY  # noqa: F401  (re-exported for callers)


def _discover():
    """Import every sibling module so each Strategy subclass registers itself."""
    for _, name, _ in pkgutil.iter_modules(__path__):  # type: ignore[name-defined]
        if name == "base":
            continue
        importlib.import_module(f"{__name__}.{name}")


def get_strategy(name: str) -> type[Strategy] | None:
    if not REGISTRY:
        _discover()
    return REGISTRY.get(name)


def all_strategy_names() -> list[str]:
    if not REGISTRY:
        _discover()
    return sorted(REGISTRY.keys())
