"""Data layer for Spike Rider.

Resolves the module's auction_series row to find handle/title_filter, then
fetches the active xTracker tracking + market prices via shared.polymarket.
One Spike Rider module per series shares the same Polymarket data layer.
"""
from api.dependencies import get_supabase
from api.modules.shared.polymarket import (
    fetch_active_tracking as _fetch_active_tracking,
    extract_slug_from_tracking,
    fetch_market_prices,
    fetch_market_brackets,
)


def get_series_for_module(module_id: str) -> dict | None:
    sb = get_supabase()
    res = (
        sb.table("auction_series")
        .select("*")
        .eq("module_id", module_id)
        .eq("enabled", True)
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]
    return None


async def fetch_active_tracking_for_series(series: dict) -> dict | None:
    handle = series.get("handle")
    title_filter = (series.get("title_filter") or "").lower()
    tracking = await _fetch_active_tracking(handle)
    if not tracking:
        return None
    title = (tracking.get("title") or "").lower()
    if title_filter and title_filter not in title:
        return None
    return tracking


__all__ = [
    "get_series_for_module",
    "fetch_active_tracking_for_series",
    "extract_slug_from_tracking",
    "fetch_market_prices",
    "fetch_market_brackets",
]
