"""Data for the Elon last-6h arb scanner: full YES+NO book per bracket.

Reads live L2 from the CLOB (real fillable prices, both sides), not just Gamma's
top-of-book bestBid/bestAsk, so the complement-pair maker arb can be priced honestly.
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


def _book(token_id: str) -> dict:
    try:
        r = httpx.get(f"{CLOB}/book", params={"token_id": token_id}, timeout=15)
        r.raise_for_status()
        b = r.json() or {}
        bids = b.get("bids") or []; asks = b.get("asks") or []
        return {"best_bid": max((float(x["price"]) for x in bids), default=None),
                "best_ask": min((float(x["price"]) for x in asks), default=None)}
    except Exception:
        return {"best_bid": None, "best_ask": None}


def bracket_full_books(event: dict) -> list[dict]:
    """Per bracket: YES + NO best bid/ask (real CLOB L2), token ids, tick, cid."""
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
        yes_tok, no_tok = toks[0], toks[1]
        yb = _book(yes_tok); nb = _book(no_tok)
        out.append({
            "label": m.get("groupItemTitle") or m.get("question") or "",
            "condition_id": m.get("conditionId"),
            "tick": float(m.get("orderPriceMinTickSize") or 0.01),
            "yes_token": yes_tok, "no_token": no_tok,
            "yes_bid": yb["best_bid"], "yes_ask": yb["best_ask"],
            "no_bid": nb["best_bid"], "no_ask": nb["best_ask"]})
    return out
