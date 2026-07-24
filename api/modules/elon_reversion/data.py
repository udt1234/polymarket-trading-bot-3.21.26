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


def live_elon_event() -> dict | None:
    """The freshest OPEN Elon tweet-count event with its bracket markets."""
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
