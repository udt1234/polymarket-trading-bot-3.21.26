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


def live_elon_event() -> dict | None:
    try:
        r = httpx.get(f"{GAMMA}/events", params={
            "slug_contains": "elon-musk-of-tweets", "closed": "false",
            "order": "startDate", "ascending": "false", "limit": 10}, timeout=25)
        r.raise_for_status()
        evs = [e for e in (r.json() or []) if (e.get("markets") or [])]
    except Exception:
        log.exception("live elon event fetch failed")
        return None
    return evs[0] if evs else None


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
