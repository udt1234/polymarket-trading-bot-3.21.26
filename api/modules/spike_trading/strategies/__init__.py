"""Strategy plugin registry.

Auto-discovers every Strategy subclass in this package. Adding a new strategy
= drop a file in strategies/ that subclasses Strategy. The module dispatches
based on the `name` class attribute (looked up via REGISTRY).
"""
from __future__ import annotations
import importlib
import pkgutil
from .base import Strategy  # noqa: F401

REGISTRY: dict[str, type[Strategy]] = {}


def _discover():
    """Import every sibling module so each Strategy subclass registers itself."""
    pkg_path = __path__  # type: ignore[name-defined]
    for _, name, _ in pkgutil.iter_modules(pkg_path):
        if name in ("base", "__init__"):
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
