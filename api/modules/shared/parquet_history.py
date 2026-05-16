"""Generic Polymarket parquet helpers — re-exported from a shared facade
so non-module callers (routers, services) don't have to import from a
specific trading module.

The implementation still lives in truth_social/parquet_history.py for
inertia; this file is a thin re-export to keep import direction correct
per CLAUDE.md (routers → services → modules → shared/, never reverse).

Audit P1 fix 2026-05-16: previously api/routers/modules.py imported these
symbols directly from truth_social/, violating the layering rule.
"""
from __future__ import annotations

from api.modules.truth_social.parquet_history import (  # noqa: F401
    search_parquet_markets,
    download_and_cache_parquet,
    preview_parquet_data,
    historical_price_pattern,
    PARQUET_CACHE_DIR,
)
