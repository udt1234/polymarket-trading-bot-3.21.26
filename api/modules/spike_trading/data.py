"""Data helpers for spike_trading.

Reuses Truth Social / Elon helpers for xTracker + Gamma API access.
The only spike-specific concern is filtering to 2-day windows of the target
bracket (default <40).
"""
from __future__ import annotations

import json
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
    # Re-exported from shared/polymarket.py 2026-05-16 (audit P1: engine
    # was importing this from a specific module — now lives in shared/).
    # Spike's own callers continue to import via this module for inertia.
    fetch_active_auctions_from_series,  # noqa: F401 re-export
)

log = logging.getLogger(__name__)


async def fetch_active_short_window_trackings(
    handle: str,
    platform: str,
    target_window_days: int = 2,
    series_slug: str | None = None,
) -> list[dict]:
    """Return active auctions for the configured handle/window.

    PRIMARY PATH: if `series_slug` is provided, query Polymarket's Series API
    directly. This sees auctions the moment Polymarket lists them, even if
    xTracker hasn't started counting yet.

    FALLBACK PATH: xTracker trackings filtered to matching window length.
    Kept for backward compatibility, and as a safety net if the Series API
    is ever down or the slug changes.
    """
    if series_slug:
        gamma = await fetch_active_auctions_from_series(series_slug)
        if gamma:
            return gamma
        log.info(f"Series '{series_slug}' returned 0 — falling back to xTracker")

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
        # Skip bracket if Polymarket has resolved it (running total already
        # outside the bracket range). Without this, Spike would post limits
        # against a market that's not accepting orders -> wasted retries +
        # noisy executor rejections. Same fix as fetch_market_prices
        # (Elon monthly debug, 2026-05-22).
        if m.get("closed") is True or m.get("acceptingOrders") is False:
            log.info(f"spike skip: bracket {target_bracket} on {slug} is resolved/closed")
            return None
        # CLOB constraints — needed by the strategy ladder builder so tier
        # prices below min_tick get snapped UP to a valid tick (live API
        # rejects sub-tick limits).
        try:
            min_tick = float(
                m.get("orderPriceMinTickSize")
                or m.get("minimumTickSize")
                or 0.01
            )
        except Exception:
            min_tick = 0.01
        try:
            min_order = float(
                m.get("orderMinSize")
                or m.get("minimumOrderSize")
                or 5
            )
        except Exception:
            min_order = 5.0
        # clobTokenIds can come back as either a list OR a JSON-encoded
        # string depending on the Gamma endpoint variant. The string form
        # is the one that bit us — without json.loads, token1 was silently
        # None and every live order got refused by LiveExecutor.
        raw_token_ids = m.get("clobTokenIds")
        token_ids_list: list = []
        if isinstance(raw_token_ids, str):
            try:
                parsed = json.loads(raw_token_ids)
                if isinstance(parsed, list):
                    token_ids_list = parsed
            except Exception:
                token_ids_list = []
        elif isinstance(raw_token_ids, list):
            token_ids_list = raw_token_ids
        token1 = token_ids_list[0] if token_ids_list else None
        return {
            "market_id": str(m.get("id", "")),
            "slug": slug,
            "condition_id": m.get("conditionId") or m.get("condition_id"),
            "token1": token1,
            "best_bid": float(m.get("bestBid") or 0.0),
            "best_ask": float(m.get("bestAsk") or 1.0),
            "volume_24h": float(m.get("volume24hr") or m.get("volume24Hr") or 0.0),
            "outcome_prices": m.get("outcomePrices"),
            "min_tick_size": min_tick,
            "min_order_size": min_order,
        }
    return None


async def _resolve_xtracker_id_for_window(
    handle: str, platform: str, start_iso: str | None, end_iso: str | None,
) -> str | None:
    """Find the xTracker tracking id whose window matches the given range.

    Used when we discovered an auction via Polymarket Series (no xTracker id)
    and need to look up live tweet counts. Returns None if no match — typical
    for pre-launch auctions where xTracker hasn't activated yet.
    """
    if not (start_iso and end_iso):
        return None
    try:
        target_start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        target_end = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"https://xtracker.polymarket.com/api/users/{handle}/trackings",
                params={"platform": platform},
            )
            r.raise_for_status()
            data = r.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            if isinstance(items, dict):
                items = items.get("trackings", [])
    except Exception:
        return None
    for t in items or []:
        s_iso = t.get("startDate", "")
        e_iso = t.get("endDate", "")
        if not (s_iso and e_iso):
            continue
        try:
            ts = datetime.fromisoformat(s_iso.replace("Z", "+00:00"))
            te = datetime.fromisoformat(e_iso.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        # Match by END date only — Polymarket lists markets ~2 days before
        # xTracker activates, so startDate diverges, but endDate (resolution
        # time) lines up within minutes.
        if abs((te - target_end).total_seconds()) < 3600:  # within 1 hour
            return str(t.get("id") or t.get("trackingId") or "") or None
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


def hours_to_close(end_iso: str) -> float | None:
    """Hours until the auction closes. Returns None when the input is empty
    or unparseable — caller MUST treat that distinct from "0 hours" because
    pacing logic divides by elapsed_hours and would misclassify a parse
    failure as "auction closing right now" (premature SELL-NOW).
    """
    if not end_iso:
        return None
    try:
        e = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
        return max((e - datetime.now(timezone.utc)).total_seconds() / 3600.0, 0.0)
    except (ValueError, TypeError):
        return None
