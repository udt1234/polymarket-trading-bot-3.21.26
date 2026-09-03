"""Market-maker universe discovery: tokens to two-sided-quote, with live top-of-book.

Three families: elon tweet brackets, White House tweet brackets, and weather reward
markets. Each token comes back with mid + best_bid/ask (from Gamma, one call per
event) plus reward params where present. Read-only; no cross-module imports.
"""
import json
import logging

import httpx

log = logging.getLogger(__name__)

GAMMA = "https://gamma-api.polymarket.com"


def _mid(bb, ba):
    if bb is not None and ba is not None:
        return (float(bb) + float(ba)) / 2.0
    if bb is not None:
        return float(bb)
    if ba is not None:
        return float(ba)
    return None


def _tweet_tokens(slug_allow: list[str] | None) -> list[dict]:
    """All live tag-972 tweet-count auctions (elon, white-house, khamenei, cz,
    zelenskyy, cruz, nyc-mayor, trump-truth-social - every tweet market we have L2
    for). Uses the shared discovery helper (tag_id 972 + client-side slug filter),
    NOT a Gamma slug_contains param, which the API silently IGNORES."""
    from api.modules.shared import discovery
    try:
        auctions = discovery.fetch_tweet_auctions()
    except Exception:
        log.exception("tweet universe fetch failed")
        return []
    out = []
    for a in auctions:
        slug = a.get("slug") or ""
        if slug_allow and not any(s in slug for s in slug_allow):
            continue
        fam = slug.split("-of-")[0].split("-of")[0][:16] or "tweet"
        for b in a.get("brackets", []):
            mid = _mid(b.get("best_bid"), b.get("best_ask"))
            if mid is None:
                continue
            out.append({"family": fam, "token": b["yes_token"],
                        "condition_id": b.get("condition_id"),
                        "tick": float(b.get("tick") or 0.01),
                        "best_bid": b.get("best_bid"), "best_ask": b.get("best_ask"),
                        "mid": mid, "label": b.get("label") or "",
                        "rewards_max_spread": None})
    return out


def _weather_tokens(min_daily_rate: float) -> list[dict]:
    """Reward-eligible weather/temperature markets (wide spreads + real reward pool)."""
    try:
        r = httpx.get(f"{GAMMA}/markets", params={
            "closed": "false", "active": "true", "limit": 500,
            "order": "volume24hr", "ascending": "false"}, timeout=30)
        r.raise_for_status()
        mks = r.json() or []
    except Exception:
        log.exception("weather reward universe fetch failed")
        return []
    out = []
    for m in mks:
        title = (m.get("question") or m.get("groupItemTitle") or "").lower()
        if not any(k in title for k in ("temperature", "weather", "highest temp", "high temp")):
            continue
        rate = 0.0
        for cr in (m.get("clobRewards") or []):
            try:
                rate = max(rate, float(cr.get("rewardsDailyRate") or 0))
            except (TypeError, ValueError):
                pass
        if rate < min_daily_rate:
            continue
        try:
            toks = json.loads(m.get("clobTokenIds") or "[]")
        except (TypeError, ValueError):
            continue
        if len(toks) < 2:
            continue
        bb, ba = m.get("bestBid"), m.get("bestAsk")
        mid = _mid(bb, ba)
        if mid is None:
            continue
        try:
            rmax = float(m.get("rewardsMaxSpread")) if m.get("rewardsMaxSpread") else None
        except (TypeError, ValueError):
            rmax = None
        out.append({"family": "weather", "token": toks[0], "condition_id": m.get("conditionId"),
                    "tick": float(m.get("orderPriceMinTickSize") or 0.01),
                    "best_bid": float(bb) if bb is not None else None,
                    "best_ask": float(ba) if ba is not None else None,
                    "mid": mid, "label": (m.get("question") or "")[:40],
                    "rewards_max_spread": rmax, "daily_rate": rate})
    return out


def get_universe(cfg: dict) -> list[dict]:
    fams = set(cfg.get("markets", []))
    uni: list[dict] = []
    # "tweets" = every tag-972 tweet market we have L2 for; optional slug allowlist
    # narrows it (e.g. ["elon-musk", "white-house"]).
    if "tweets" in fams or "elon" in fams or "whitehouse" in fams:
        allow = cfg.get("tweet_slug_allow") or None
        uni += _tweet_tokens(allow)
    if "weather" in fams:
        uni += _weather_tokens(cfg.get("weather_min_daily_rate", 50.0))
    # dedupe by token
    seen, out = set(), []
    for t in uni:
        if t["token"] in seen:
            continue
        seen.add(t["token"]); out.append(t)
    return out[: int(cfg.get("max_tokens", 40))]
