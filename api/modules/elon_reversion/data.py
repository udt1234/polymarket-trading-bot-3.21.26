"""Data for the Elon last-6h mean-reversion module.

Pulls the live Elon tweet-count auction, its bracket books, and a recent per-bracket
price series (for the OU fit). Read-only Gamma + CLOB; no cross-module imports.
"""
import json
import logging

import httpx

log = logging.getLogger(__name__)

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"


ELON_SLUG = "elon-musk-of-tweets"
TAG_TWEET_MARKETS = 972


def live_elon_event() -> dict | None:
    """The Elon tweet-count auction CLOSEST TO RESOLVING among those live now.

    Gamma has no `slug_contains` filter - passing one was silently ignored and
    this returned whatever 10 events sorted newest-first, i.e. soccer corners and
    crypto up/down markets. Their slugs then failed to parse into a noon-ET
    window, so every late-window scanner returned nothing, forever (2026-09-01).
    Filter by tag 972 and match the slug ourselves; a LATE scanner wants the
    auction nearest its end, not the newest-listed one.
    """
    from datetime import datetime

    from api.modules.shared import windows
    try:
        r = httpx.get(f"{GAMMA}/events", params={
            "tag_id": TAG_TWEET_MARKETS, "closed": "false", "limit": 100},
            timeout=25)
        r.raise_for_status()
        evs = [e for e in (r.json() or [])
               if (e.get("markets") or []) and ELON_SLUG in (e.get("slug") or "")]
    except Exception:
        log.exception("live elon event fetch failed")
        return None
    now = datetime.now(windows.ET)
    live = []
    for e in evs:
        win = windows.parse_slug_window(e.get("slug") or "")
        if win and win[0] <= now < win[1]:
            live.append((win[1], e))
    if not live:
        return None
    live.sort(key=lambda x: x[0])          # soonest end first
    return live[0][1]


def bracket_books(event: dict) -> list[dict]:
    """Per-bracket {label, token, best_bid, best_ask, tick, condition_id, no_token}
    for every open bracket of the event."""
    out = []
    for m in (event.get("markets") or []):
        if m.get("closed") or m.get("acceptingOrders") is False:
            continue
        try:
            toks = json.loads(m.get("clobTokenIds") or "[]")
        except (TypeError, ValueError):
            continue
        if len(toks) < 2:
            continue
        bid = m.get("bestBid"); ask = m.get("bestAsk")
        out.append({
            "label": m.get("groupItemTitle") or m.get("question") or "",
            "token": toks[0], "no_token": toks[1],
            "best_bid": float(bid) if bid is not None else None,
            "best_ask": float(ask) if ask is not None else None,
            "tick": float(m.get("orderPriceMinTickSize") or 0.01),
            "condition_id": m.get("conditionId")})
    return out


def price_series(token_id: str, interval: str = "6h", fidelity: int = 1) -> list[float]:
    """Recent YES price series for a bracket token (for the OU estimate).
    fidelity is the sample resolution in minutes."""
    try:
        r = httpx.get(f"{CLOB}/prices-history", params={
            "market": token_id, "interval": interval, "fidelity": fidelity}, timeout=25)
        r.raise_for_status()
        hist = (r.json() or {}).get("history") or []
        return [float(h["p"]) for h in hist if h.get("p") is not None]
    except Exception:
        log.exception("price-history fetch failed for %s", token_id[:16])
        return []


def no_token_book(condition_id: str, no_token: str) -> dict | None:
    """Best bid/ask for the NO token (we fade a spiked bracket by buying its NO)."""
    try:
        r = httpx.get(f"{CLOB}/book", params={"token_id": no_token}, timeout=15)
        r.raise_for_status()
        b = r.json() or {}
        bids = b.get("bids") or []; asks = b.get("asks") or []
        bb = max((float(x["price"]) for x in bids), default=None)
        ba = min((float(x["price"]) for x in asks), default=None)
        return {"best_bid": bb, "best_ask": ba}
    except Exception:
        log.exception("no-token book fetch failed for %s", (no_token or "")[:16])
        return None
