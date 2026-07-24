"""Arb scanner data: per-market YES+NO best bid/ask across scanned events.

For a binary market the NO book is the mirror of the YES book: NO_bid = 1 - YES_ask,
NO_ask = 1 - YES_bid. So we can price BOTH sides from Gamma's YES bestBid/bestAsk with
ZERO extra CLOB calls - which makes scanning hundreds of markets per cycle feasible.
"""
import json
import logging

import httpx

log = logging.getLogger(__name__)

GAMMA = "https://gamma-api.polymarket.com"


def _markets_from_event(e: dict) -> list[dict]:
    out = []
    for mk in (e.get("markets") or []):
        if mk.get("closed") or mk.get("acceptingOrders") is False:
            continue
        try:
            toks = json.loads(mk.get("clobTokenIds") or "[]")
        except (TypeError, ValueError):
            continue
        if len(toks) < 2:
            continue
        yb, ya = mk.get("bestBid"), mk.get("bestAsk")
        out.append({
            "yes_token": toks[0], "no_token": toks[1],
            "yes_bid": float(yb) if yb is not None else None,
            "yes_ask": float(ya) if ya is not None else None,
            "tick": float(mk.get("orderPriceMinTickSize") or 0.01),
            "condition_id": mk.get("conditionId"),
            "label": mk.get("groupItemTitle") or mk.get("question") or ""})
    return out


def scan_tag_events(tag_id: int, limit: int = 100) -> list[dict]:
    """Multi-market events under a Gamma tag. Each returns {slug, title, markets:[...]}
    with per-market YES best bid/ask (complete-set legs come from these too)."""
    try:
        r = httpx.get(f"{GAMMA}/events", params={"tag_id": tag_id, "closed": "false",
                      "limit": limit}, timeout=30)
        r.raise_for_status()
    except Exception:
        log.exception("tag %s scan failed", tag_id)
        return []
    out = []
    for e in r.json() or []:
        mkts = _markets_from_event(e)
        if mkts:
            out.append({"slug": e.get("slug"), "title": e.get("title"), "markets": mkts})
    return out
