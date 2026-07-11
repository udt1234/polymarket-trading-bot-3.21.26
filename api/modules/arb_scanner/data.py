"""Arb scanner data: fetch events with all their outcome legs + best asks.

A 'complete set' = every outcome of ONE event. For binary game markets the two
sides are the set; for a tweet event the set is all brackets. We read best asks
from Gamma (bestAsk), which is the price a TAKER pays to buy that leg now."""
import json
import logging

import httpx

log = logging.getLogger(__name__)

GAMMA = "https://gamma-api.polymarket.com"


def _legs_from_event(e: dict) -> list[dict]:
    legs = []
    for mk in (e.get("markets") or []):
        if mk.get("closed") or mk.get("acceptingOrders") is False:
            return []  # incomplete set - skip the whole event
        try:
            toks = json.loads(mk.get("clobTokenIds") or "[]")
        except (TypeError, ValueError):
            return []
        ask = mk.get("bestAsk")
        if ask is None or not toks:
            return []  # can't price the full set - skip
        legs.append({"token": toks[0], "ask": float(ask),
                     "tick": float(mk.get("orderPriceMinTickSize") or 0.01),
                     "condition_id": mk.get("conditionId"),
                     "label": mk.get("groupItemTitle") or mk.get("question") or ""})
    return legs


def scan_tag_events(tag_id: int) -> list[dict]:
    """Multi-market events under a Gamma tag (e.g. tweet brackets). Each event
    returns its full leg set (or empty if not fully priceable)."""
    try:
        r = httpx.get(f"{GAMMA}/events", params={"tag_id": tag_id, "closed": "false",
                      "limit": 100}, timeout=30)
        r.raise_for_status()
    except Exception:
        log.exception("tag scan failed")
        return []
    out = []
    for e in r.json():
        legs = _legs_from_event(e)
        if len(legs) >= 2:
            out.append({"slug": e.get("slug"), "title": e.get("title"), "legs": legs})
    return out


# NOTE: a single BINARY market (sports/crypto) cannot be complete-set arbed -
# its YES_ask + NO_ask = 1 + spread >= 1 always (the market-maker spread). Real
# complete-set arb lives on MULTI-MARKET events where each outcome is a separate
# market (tweet brackets, neg-risk events), so buying every leg's ask can sum
# below $1 when the set is fragmented/mispriced. Those come from scan_tag_events.
