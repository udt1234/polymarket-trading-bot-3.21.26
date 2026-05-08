"""Live writer for auction_archive.

Called by the resolution tracker when an auction's markets close. Writes
one row per (handle, auction_slug) — UPSERT, so re-resolution is safe.

Module-driven: each BaseModule subclass implements
`archive_resolved_auction(tracking_id_or_slug)` returning the row dict.
This service handles the Supabase write + dedupe.
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone

import httpx

from api.dependencies import get_supabase

log = logging.getLogger(__name__)
GAMMA_BASE = "https://gamma-api.polymarket.com"


def _fetch_event(slug: str) -> dict | None:
    """Pull a Gamma event payload for a given slug. Returns None on failure."""
    try:
        with httpx.Client(timeout=15) as client:
            res = client.get(f"{GAMMA_BASE}/events", params={"slug": slug})
            res.raise_for_status()
            events = res.json()
            if not isinstance(events, list) or not events:
                return None
            return events[0]
    except Exception as e:
        log.warning(f"auction_archiver: Gamma fetch failed for {slug}: {e}")
        return None


def build_archive_row_from_event(event: dict, module=None, module_id: str | None = None) -> dict | None:
    """Generic builder: works for any tweet-style auction. Modules can
    override by implementing their own archive_resolved_auction(); this
    function is the safe default.
    """
    from api.modules.shared.polymarket import normalize_bracket

    if not event:
        return None
    markets = event.get("markets", [])
    if not markets:
        return None

    bracket_outcomes: dict[str, bool] = {}
    bracket_end_prices: dict[str, float] = {}
    winning_bracket: str | None = None
    best_price = -1.0

    for m in markets:
        raw = m.get("groupItemTitle", m.get("question", ""))
        bracket = normalize_bracket(raw) if raw else None
        if not bracket:
            continue
        op = m.get("outcomePrices", "[]")
        if isinstance(op, str):
            try:
                op = json.loads(op)
            except Exception:
                op = []
        try:
            yes_price = float(op[0]) if op else 0.0
        except Exception:
            yes_price = 0.0
        bracket_end_prices[bracket] = yes_price
        won = yes_price > 0.5
        bracket_outcomes[bracket] = won
        if won and yes_price > best_price:
            best_price = yes_price
            winning_bracket = bracket

    # Aggregate volume from all markets
    total_volume = 0.0
    for m in markets:
        try:
            v = float(m.get("volume") or m.get("volumeNum") or 0)
            total_volume += v
        except Exception:
            pass

    # Derive start/end from event payload
    start_str = event.get("startDate") or event.get("startTime") or markets[0].get("startDate", "")
    end_str = event.get("endDate") or event.get("endTime") or markets[0].get("endDate", "")
    try:
        start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        window_days = round((end_dt - start_dt).total_seconds() / 86400, 1)
    except Exception:
        return None

    handle = ""
    platform = None
    if module is not None:
        try:
            handle = module.get_handle()
            platform = module.get_platform()
        except Exception:
            pass

    return {
        "module_id": module_id,
        "handle": handle,
        "platform": platform,
        "auction_slug": event.get("slug", ""),
        "tracking_id": None,
        "window_days": window_days,
        "start_date": start_dt.isoformat(),
        "end_date": end_dt.isoformat(),
        "winning_bracket": winning_bracket,
        "bracket_outcomes": bracket_outcomes,
        "bracket_end_prices": bracket_end_prices,
        "total_volume": total_volume,
        "market_count": len(markets),
        "source": "live_resolution",
        "metrics": {"event_title": event.get("title", "")},
    }


def archive_auction(module, module_id: str, auction_slug: str) -> bool:
    """Build + UPSERT one archive row for a freshly-resolved auction.

    Returns True if a row was written, False otherwise. Idempotent.
    """
    if not auction_slug:
        return False

    # Module hook: lets a module supply richer data (custom metrics, bot PnL)
    row = None
    if hasattr(module, "archive_resolved_auction"):
        try:
            row = module.archive_resolved_auction(module_id, auction_slug)
        except Exception as e:
            log.warning(f"module.archive_resolved_auction failed for {auction_slug}: {e}")
            row = None

    if row is None:
        event = _fetch_event(auction_slug)
        row = build_archive_row_from_event(event, module=module, module_id=module_id)

    if row is None:
        log.info(f"auction_archiver: no row built for {auction_slug}")
        return False

    # Backfill bot performance fields from positions / signals.
    sb = get_supabase()
    try:
        if module_id:
            pos = sb.table("positions").select(
                "bracket,realized_pnl,status,market_id"
            ).eq("module_id", module_id).execute().data or []
            sigs = sb.table("signals").select(
                "id,bracket,market_id"
            ).eq("module_id", module_id).execute().data or []
            # Filter positions/signals to those for this auction. Best-effort:
            # match against any of the event's market ids if available.
            event = _fetch_event(auction_slug) if "market_count" in row else None
            event_market_ids = set()
            if event:
                for m in event.get("markets", []):
                    if m.get("id"):
                        event_market_ids.add(str(m["id"]))
            relevant_pos = [p for p in pos if str(p.get("market_id") or "") in event_market_ids]
            relevant_sigs = [s for s in sigs if str(s.get("market_id") or "") in event_market_ids]

            traded_brackets = sorted({p["bracket"] for p in relevant_pos if p.get("bracket")})
            won_brackets = []
            bot_pnl = 0.0
            outcomes = row.get("bracket_outcomes") or {}
            for p in relevant_pos:
                b = p.get("bracket")
                if not b:
                    continue
                bot_pnl += float(p.get("realized_pnl") or 0)
                if outcomes.get(b):
                    won_brackets.append(b)
            row["bot_traded"] = bool(traded_brackets)
            row["bot_brackets"] = traded_brackets or None
            row["bot_pnl"] = round(bot_pnl, 4) if traded_brackets else None
            row["bot_signals_count"] = len(relevant_sigs)
            row["bot_won_brackets"] = sorted(set(won_brackets)) or None
    except Exception as e:
        log.warning(f"auction_archiver: bot-perf join failed for {auction_slug}: {e}")

    try:
        sb.table("auction_archive").upsert(row, on_conflict="handle,auction_slug").execute()
        log.info(f"auction_archiver: archived {row['handle']}/{auction_slug} winner={row.get('winning_bracket')}")
        return True
    except Exception as e:
        log.error(f"auction_archiver: upsert failed for {auction_slug}: {e}")
        return False
