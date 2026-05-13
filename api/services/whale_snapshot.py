"""Whale snapshot orchestrator — fetches per-market trade history and builds
one row in whale_snapshots per resolved auction.

Spec: _ImportantConfigFiles/WHALE_BRACKET_CARDS_SPEC.md Phase 2.

Called from scripts/refresh_whale_snapshots.py (nightly cron + manual
backfill). Does not import frontend code or routers. All Supabase writes
are idempotent (upsert on (handle, auction_slug)).
"""
from __future__ import annotations
import asyncio
import logging
from collections import defaultdict
from datetime import datetime
from typing import Iterable

import httpx

from api.dependencies import get_supabase
from api.modules.shared.polymarket import fetch_condition_ids
from api.services.whale_classifier import (
    ARCHETYPES,
    classify_wallet,
    compute_archetype_breakdown,
    compute_grid_metrics,
    compute_modal_bucket,
    compute_top_wallets,
    derive_price_momentum_spike_windows,
)

log = logging.getLogger(__name__)

DATA_API = "https://data-api.polymarket.com"

# Page size + max pages per market (cap = 1000 trades). Markets with more
# trades log a truncation warning. 1000 fills captures whale patterns
# reliably; only loses the long tail of small retail trades.
TRADES_PAGE_LIMIT = 500
TRADES_MAX_PAGES = 2

# Spacing between data-api calls to stay polite at scale.
INTER_CALL_DELAY_S = 0.5

# Retry config mirrors polymarket._xtracker_get.
_RETRY_STATUSES = {500, 502, 503, 504}


async def _data_api_get(client: httpx.AsyncClient, url: str, params: dict) -> list[dict]:
    """3 attempts on 5xx/timeout, 0.5s × 2^n backoff. Returns JSON or raises."""
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            res = await client.get(url, params=params)
            if res.status_code in _RETRY_STATUSES:
                raise httpx.HTTPStatusError(
                    f"data-api {res.status_code}", request=res.request, response=res
                )
            res.raise_for_status()
            return res.json() or []
        except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError) as e:
            last_exc = e
            if attempt < 2:
                await asyncio.sleep(0.5 * (2 ** attempt))
    assert last_exc is not None
    raise last_exc


async def fetch_market_trades(
    condition_id: str, max_pages: int = TRADES_MAX_PAGES
) -> list[dict]:
    """All trades for one Polymarket market (conditionId), paginated.

    Returns trade dicts with proxyWallet, side, size, price, timestamp,
    outcome, slug, name, pseudonym. Caps at max_pages × TRADES_PAGE_LIMIT
    trades and logs a warning on truncation."""
    out: list[dict] = []
    async with httpx.AsyncClient(timeout=20) as client:
        for page in range(max_pages):
            offset = page * TRADES_PAGE_LIMIT
            try:
                batch = await _data_api_get(
                    client,
                    f"{DATA_API}/trades",
                    {"market": condition_id, "limit": TRADES_PAGE_LIMIT, "offset": offset},
                )
            except Exception as e:
                log.warning(f"data-api trades failed for {condition_id[:10]}... offset={offset}: {e}")
                break
            if not batch:
                break
            out.extend(batch)
            if len(batch) < TRADES_PAGE_LIMIT:
                break
            await asyncio.sleep(INTER_CALL_DELAY_S)
        else:
            # Hit the page cap with full last page — likely truncated.
            log.warning(
                f"fetch_market_trades({condition_id[:10]}...) hit page cap "
                f"({max_pages * TRADES_PAGE_LIMIT} trades); tail truncated"
            )
    return out


def _epoch(dt: datetime | str) -> int:
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    return int(dt.timestamp())


def get_spike_series_for_handle(
    handle: str, auction_start: datetime, auction_end: datetime
) -> list[tuple[int, float]] | None:
    """Per-hour Δpost-count series for the handle, from post_count_snapshots.

    Returns list of (epoch_timestamp_at_hour_end, delta_count_since_prev)
    sorted ascending. None if insufficient data (need ≥3 hours).
    """
    sb = get_supabase()
    start_iso = auction_start.isoformat() if isinstance(auction_start, datetime) else auction_start
    end_iso = auction_end.isoformat() if isinstance(auction_end, datetime) else auction_end
    res = (
        sb.table("post_count_snapshots")
        .select("captured_at, count")
        .gte("captured_at", start_iso)
        .lte("captured_at", end_iso)
        .order("captured_at", desc=False)
        .limit(2000)
        .execute()
    )
    rows = res.data or []
    if len(rows) < 3:
        return None
    # Bucket into hour cells, take last count per hour
    by_hour: dict[int, int] = {}
    for r in rows:
        c = r.get("count")
        if c is None:
            continue
        ts = r.get("captured_at")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            continue
        h = int(dt.timestamp() // 3600)
        # Keep the LAST count seen in this hour
        by_hour[h] = int(c)
    if len(by_hour) < 3:
        return None
    sorted_hours = sorted(by_hour.keys())
    series: list[tuple[int, float]] = []
    for i in range(1, len(sorted_hours)):
        prev = by_hour[sorted_hours[i - 1]]
        cur = by_hour[sorted_hours[i]]
        delta = float(cur - prev)
        series.append((sorted_hours[i] * 3600, delta))
    return series


def _spike_windows_from_series(
    series: list[tuple[int, float]] | None
) -> list[tuple[int, int]] | None:
    """Convert a (epoch, delta) series into ±2hr windows around top-decile
    delta values. None propagates."""
    if not series or len(series) < 3:
        return None
    deltas = sorted(d for _, d in series)
    cutoff_idx = int(len(deltas) * 0.9)
    cutoff = deltas[cutoff_idx] if deltas else 0.0
    if cutoff <= 0:
        return None
    windows = []
    for ts, d in series:
        if d >= cutoff:
            windows.append((ts - 2 * 3600, ts + 2 * 3600))
    return windows or None


def _tag_fills_with_bucket(
    fills_by_market: dict[str, list[dict]],
    cid_to_bracket: dict[str, str],
    bracket_lo: dict[str, int],
    modal_bucket: str | None,
) -> None:
    """In-place: attach `bracket` and `bracket_distance` to every fill.

    `bracket_lo` maps each bracket label to a sortable integer (lower edge).
    `bracket_distance` = # of brackets between fill's bucket and modal,
    when both have a known lo. Tail Punter rule uses this."""
    if modal_bucket is not None and modal_bucket not in bracket_lo:
        modal_bucket = None
    # Build an ordered list of brackets by lo, so distance = index difference
    ordered = sorted(bracket_lo.keys(), key=lambda b: bracket_lo[b])
    idx_of = {b: i for i, b in enumerate(ordered)}
    modal_idx = idx_of.get(modal_bucket) if modal_bucket else None
    for cid, fills in fills_by_market.items():
        bracket = cid_to_bracket.get(cid, "?")
        for f in fills:
            f["bracket"] = bracket
            if modal_idx is not None and bracket in idx_of:
                f["bracket_distance"] = abs(idx_of[bracket] - modal_idx)
            else:
                f["bracket_distance"] = None


def _bracket_lo(b: str) -> int:
    if b.startswith("<"):
        return 0
    if b.endswith("+"):
        try:
            return int(b[:-1])
        except ValueError:
            return 99999
    if "-" in b:
        try:
            return int(b.split("-", 1)[0])
        except ValueError:
            return 0
    try:
        return int(b)
    except ValueError:
        return 0


async def build_snapshot(
    handle: str,
    auction_slug: str,
    auction_start: datetime,
    auction_end: datetime,
    bot_wallet: str | None,
    final_value: float | None = None,
    winning_bracket: str | None = None,
) -> dict | None:
    """Build one whale_snapshots row for this (handle, auction_slug).

    Returns the row ready for upsert, or None if no markets / no trades.
    """
    cid_map = await fetch_condition_ids(auction_slug)
    if not cid_map:
        log.warning(f"build_snapshot({handle}, {auction_slug}): no condition ids")
        return None

    # Fetch trades for every market in parallel-ish (sequential with small
    # delay to be polite). At ~11 markets per Trump auction this is ~5s.
    fills_by_market: dict[str, list[dict]] = {}
    for bracket, cid in cid_map.items():
        trades = await fetch_market_trades(cid)
        fills_by_market[cid] = trades
        await asyncio.sleep(INTER_CALL_DELAY_S)

    # Filter fills to the auction window (Polymarket sometimes has post-close
    # cleanup trades — exclude).
    start_epoch = _epoch(auction_start)
    end_epoch = _epoch(auction_end)
    for cid, fills in fills_by_market.items():
        fills_by_market[cid] = [
            f for f in fills if start_epoch <= int(f.get("timestamp", 0) or 0) <= end_epoch
        ]

    # Build bracket_lo map and modal bucket
    cid_to_bracket = {cid: b for b, cid in cid_map.items()}
    bracket_lo = {b: _bracket_lo(b) for b in cid_map.keys()}
    fills_by_bucket: dict[str, list[dict]] = defaultdict(list)
    for cid, fills in fills_by_market.items():
        fills_by_bucket[cid_to_bracket[cid]].extend(fills)
    modal_bucket = compute_modal_bucket(fills_by_bucket)

    # Tag every fill with bracket + distance
    _tag_fills_with_bucket(fills_by_market, cid_to_bracket, bracket_lo, modal_bucket)

    # Per-wallet aggregation
    wallet_fills: dict[str, list[dict]] = defaultdict(list)
    for fills in fills_by_market.values():
        for f in fills:
            w = (f.get("proxyWallet") or "").lower()
            if not w:
                continue
            wallet_fills[w].append(f)

    if not wallet_fills:
        log.info(f"build_snapshot({handle}, {auction_slug}): no fills, skipping")
        return None

    # Spike windows: try post_count series first, fall back to fill-price
    # momentum (handles non-tweet markets and tweet markets with sparse
    # post_count_snapshots coverage).
    pace_series = get_spike_series_for_handle(handle, auction_start, auction_end)
    spike_windows = _spike_windows_from_series(pace_series)
    if not spike_windows:
        all_fills_flat: list[dict] = []
        for fills in fills_by_market.values():
            all_fills_flat.extend(fills)
        spike_windows = derive_price_momentum_spike_windows(
            all_fills_flat, start_epoch, end_epoch
        )

    # Classify every wallet
    classifications = {
        w: classify_wallet(fills, start_epoch, end_epoch, spike_windows, modal_bucket)
        for w, fills in wallet_fills.items()
    }

    # Load wallet meta from whale_wallet_profiles if available (best-effort)
    wallet_meta = _load_wallet_meta(list(wallet_fills.keys()))

    breakdown, dollar_volume = compute_archetype_breakdown(
        wallet_fills, classifications, bot_wallet
    )
    top_wallets = compute_top_wallets(wallet_fills, classifications, wallet_meta, bot_wallet)
    grid_metrics = compute_grid_metrics(
        wallet_fills, classifications, start_epoch, end_epoch
    )

    row = {
        "handle": handle,
        "market_universe": list(cid_map.values()),
        "auction_slug": auction_slug,
        "auction_start": auction_start.isoformat() if isinstance(auction_start, datetime) else auction_start,
        "auction_end": auction_end.isoformat() if isinstance(auction_end, datetime) else auction_end,
        "final_outcome": {
            "winning_bucket": winning_bracket,
            "final_value": final_value,
        } if (winning_bracket or final_value is not None) else None,
        "archetype_breakdown": breakdown,
        "archetype_dollar_volume": dollar_volume,
        "top_wallets": top_wallets,
        "grid_metrics": grid_metrics,
    }
    return row


def _load_wallet_meta(wallets: list[str]) -> dict[str, dict]:
    """Best-effort lookup of profile rows for the given wallets. Batches
    IN(...) queries at 50 wallets per request to stay under URL-length
    limits. Empty dict on any error."""
    if not wallets:
        return {}
    out: dict[str, dict] = {}
    batch_size = 50
    sb = get_supabase()
    for i in range(0, len(wallets), batch_size):
        batch = wallets[i:i + batch_size]
        try:
            res = (
                sb.table("whale_wallet_profiles")
                .select("wallet,name_or_pseudonym,roi_pct,portfolio_value,win_rate_pct,auctions_seen")
                .in_("wallet", batch)
                .execute()
            )
            for r in (res.data or []):
                out[r["wallet"]] = r
        except Exception as e:
            log.warning(f"whale_wallet_profiles lookup batch {i} failed: {e}")
    return out


def upsert_snapshot(row: dict) -> None:
    """Idempotent upsert on (handle, auction_slug)."""
    sb = get_supabase()
    sb.table("whale_snapshots").upsert(
        row, on_conflict="handle,auction_slug"
    ).execute()


def list_not_yet_snapshotted(
    handle: str | None = None, limit: int = 20
) -> list[dict]:
    """Auction_archive rows with end_date in the past whose (handle, auction_slug)
    is not in whale_snapshots yet. Oldest-first so backfill converges forward."""
    sb = get_supabase()
    # Step 1: get already-snapshotted (handle, slug) pairs
    snap_q = sb.table("whale_snapshots").select("handle,auction_slug")
    if handle:
        snap_q = snap_q.eq("handle", handle)
    snapped = {(r["handle"], r["auction_slug"]) for r in (snap_q.execute().data or [])}

    # Step 2: get auction_archive rows ordered by end_date asc
    arch_q = (
        sb.table("auction_archive")
        .select(
            "handle, auction_slug, start_date, end_date, final_value, winning_bracket"
        )
        .lte("end_date", datetime.utcnow().isoformat())
        .order("end_date", desc=False)
    )
    if handle:
        arch_q = arch_q.eq("handle", handle)
    # Pull enough rows to find `limit` not-yet-snapshotted
    arch_q = arch_q.limit(max(limit * 5, 50))
    archived = arch_q.execute().data or []

    out: list[dict] = []
    for r in archived:
        key = (r["handle"], r["auction_slug"])
        if key in snapped:
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out
