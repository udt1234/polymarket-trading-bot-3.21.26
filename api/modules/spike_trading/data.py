"""Data helpers for spike_trading.

Reuses Truth Social / Elon helpers for xTracker + Gamma API access.
The only spike-specific concern is filtering to 2-day windows of the target
bracket (default <40).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from api.modules.shared.polymarket import (
    GAMMA_BASE,
    fetch_xtracker_posts,
    parse_hourly_counts,
    compute_running_total,
    compute_elapsed_days,
)

log = logging.getLogger(__name__)


async def fetch_active_short_window_trackings(
    handle: str,
    platform: str,
    target_window_days: int = 2,
) -> list[dict]:
    """Return all currently-active trackings for `handle` whose window length
    matches `target_window_days` (within ±0.1 day). Excludes trackings that
    haven't started yet or already ended.

    For Elon 2-day: typically 1-2 active concurrently. For Truth Social 2-day:
    not currently a Polymarket pattern (Trump uses 7-day), but the helper is
    handle-agnostic.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.get(
            f"https://xtracker.polymarket.com/api/users/{handle}/trackings",
            params={"platform": platform},
        )
        res.raise_for_status()
        data = res.json()
        items = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(items, dict):
            items = items.get("trackings", [])

    now = datetime.now(timezone.utc)
    matched = []
    for t in items:
        s, e = t.get("startDate", ""), t.get("endDate", "")
        if not (s and e):
            continue
        try:
            sd = datetime.fromisoformat(s.replace("Z", "+00:00"))
            ed = datetime.fromisoformat(e.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if not (sd <= now <= ed):
            continue
        window_days = (ed - sd).total_seconds() / 86400.0
        if abs(window_days - target_window_days) <= 0.15:
            matched.append(t)
    return matched


async def fetch_market_for_tracking(tracking: dict, target_bracket: str) -> Optional[dict]:
    """For a given tracking, find the Polymarket market matching the bracket.

    Returns the market dict including:
      market_id, condition_id, token1 (YES), best_bid, best_ask, volume_24h,
      outcome_prices.

    Returns None if no matching bracket found or market is too illiquid.
    """
    market_link = tracking.get("marketLink", "")
    if not market_link:
        return None
    # marketLink looks like https://polymarket.com/event/<slug>
    slug = market_link.rstrip("/").split("/")[-1]

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.get(f"{GAMMA_BASE}/events", params={"slug": slug})
            r.raise_for_status()
            events = r.json()
        except Exception as e:
            log.warning(f"fetch_market_for_tracking({slug}) failed: {e}")
            return None

    if not isinstance(events, list) or not events:
        return None
    markets = events[0].get("markets", [])

    target_clean = target_bracket.strip().lower()
    for m in markets:
        raw = m.get("groupItemTitle", m.get("question", "")) or ""
        if raw.strip().lower() != target_clean:
            continue
        return {
            "market_id": str(m.get("id", "")),
            "slug": slug,
            "condition_id": m.get("conditionId") or m.get("condition_id"),
            "token1": (m.get("clobTokenIds") or [None])[0] if isinstance(m.get("clobTokenIds"), list) else None,
            "best_bid": float(m.get("bestBid") or 0.0),
            "best_ask": float(m.get("bestAsk") or 1.0),
            "volume_24h": float(m.get("volume24hr") or m.get("volume24Hr") or 0.0),
            "outcome_prices": m.get("outcomePrices"),
        }
    return None


async def fetch_cumulative_tweets(handle: str, tracking_id: str | None = None) -> int:
    """Best-effort current cumulative tweet count for the active tracking.

    If tracking_id supplied, fetches that specific tracking; else falls back
    to whatever the platform's currently-active tracking is. Returns 0 on
    error (callers should treat 0 with caution since it's also a real value).
    """
    try:
        if tracking_id:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    f"https://xtracker.polymarket.com/api/trackings/{tracking_id}",
                    params={"includeStats": "true"},
                )
                r.raise_for_status()
                d = r.json()
                data = d.get("data", d) if isinstance(d, dict) else d
                stats = (data or {}).get("stats", {}) or {}
                # Prefer 'total' (sum-to-date); fall back to 'cumulative' (last hourly)
                total = stats.get("total")
                if total is not None:
                    return int(total)
                daily = stats.get("daily") or []
                if isinstance(daily, list) and daily:
                    return int(daily[-1].get("cumulative") or 0)
                return 0
        # Fallback: route through truth_social helper
        raw = await fetch_xtracker_posts(handle)
        hourly = parse_hourly_counts(raw)
        if hourly:
            # most recent total
            return compute_running_total(hourly)
        return 0
    except Exception as e:
        log.warning(f"fetch_cumulative_tweets({handle}) failed: {e}")
        return 0


def hours_to_close(end_iso: str) -> float:
    try:
        e = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
        return max((e - datetime.now(timezone.utc)).total_seconds() / 3600.0, 0.0)
    except (ValueError, TypeError):
        return 0.0
