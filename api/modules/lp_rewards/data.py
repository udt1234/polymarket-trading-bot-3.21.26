"""LP-reward data: reward-eligible markets with an active daily pool + book.

Gamma exposes per market: rewardsMinSize (min qualifying order, shares),
rewardsMaxSpread (max distance from mid to qualify, CENTS), and clobRewards[] with
rewardsDailyRate (the daily reward pool). We rest inside that band on both legs."""
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


def reward_markets(cfg: dict) -> list[dict]:
    """Active markets with an affordable min-size and a non-trivial reward pool."""
    try:
        r = httpx.get(f"{GAMMA}/markets", params={
            "active": "true", "closed": "false", "limit": 100,
            "order": "volume24hr", "ascending": "false"}, timeout=30)
        r.raise_for_status()
        markets = r.json() or []
    except Exception:
        log.exception("reward_markets fetch failed")
        return []
    out = []
    for m in markets:
        if m.get("closed") or m.get("acceptingOrders") is False:
            continue
        rmin = _f(m.get("rewardsMinSize"))
        rmax = _f(m.get("rewardsMaxSpread"))
        if not rmin or not rmax:
            continue
        if rmin > cfg["max_min_size"]:
            continue
        rate = sum(_f(cr.get("rewardsDailyRate")) or 0.0
                   for cr in (m.get("clobRewards") or []))
        if rate < cfg["min_daily_rate"]:
            continue
        try:
            toks = json.loads(m.get("clobTokenIds") or "[]")
            outs = json.loads(m.get("outcomes") or "[]")
        except (TypeError, ValueError):
            continue
        if len(toks) != 2:
            continue
        bid = _f(m.get("bestBid"))
        ask = _f(m.get("bestAsk"))
        if bid is None or ask is None:
            continue
        out.append({
            "condition_id": m.get("conditionId"), "question": m.get("question"),
            "yes_token": toks[0], "no_token": toks[1], "outcomes": outs,
            "best_bid": bid, "best_ask": ask, "mid": round((bid + ask) / 2, 4),
            "tick": float(m.get("orderPriceMinTickSize") or 0.01),
            "rewards_min_size": rmin, "rewards_max_spread": rmax, "daily_rate": rate,
        })
    return out
