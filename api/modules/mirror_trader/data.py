"""Mirror-trader data: resolve each whale-bought token to its CURRENT book so we
can rest a maker bid at/below the whale's entry. Whale fetchers live in
api/modules/shared/whales.py (no cross-module import)."""
import json
import logging

import httpx

log = logging.getLogger(__name__)

GAMMA = "https://gamma-api.polymarket.com"


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def token_book(condition_id: str, asset: str) -> dict | None:
    """Current {best_bid, best_ask, tick, outcome} for the whale-bought token
    (asset), or None if the market isn't live/quotable. Gamma bestBid/bestAsk are
    the YES side; the NO leg is inverted (bid=1-ask, ask=1-bid)."""
    try:
        r = httpx.get(f"{GAMMA}/markets", params={"condition_ids": condition_id},
                      timeout=20)
        r.raise_for_status()
        mk = r.json() or []
    except Exception:
        log.exception("token_book fetch failed for %s", (condition_id or "")[:12])
        return None
    if not mk:
        return None
    m = mk[0]
    if m.get("closed") or m.get("acceptingOrders") is False:
        return None
    try:
        toks = json.loads(m.get("clobTokenIds") or "[]")
        outs = json.loads(m.get("outcomes") or "[]")
    except (TypeError, ValueError):
        return None
    if asset not in toks:
        return None
    idx = toks.index(asset)
    bb = _f(m.get("bestBid"))
    ba = _f(m.get("bestAsk"))
    if bb is None or ba is None:
        return None
    tick = float(m.get("orderPriceMinTickSize") or 0.01)
    if idx == 0:
        return {"best_bid": bb, "best_ask": ba, "tick": tick,
                "outcome": outs[0] if outs else "YES"}
    return {"best_bid": round(1 - ba, 4), "best_ask": round(1 - bb, 4), "tick": tick,
            "outcome": outs[1] if len(outs) > 1 else "NO"}
