"""Market discovery via Gamma (BUILD_SPEC C2). Gamma is primary.

fetch_tweet_auctions() returns every live tweet-count auction (tag 972)
as one dict per event with its brackets normalized, resolved/closed
brackets dropped, and the noon-ET window parsed from the slug.
"""
import json
import logging

import httpx

from api.modules.shared import windows

log = logging.getLogger(__name__)

GAMMA = "https://gamma-api.polymarket.com"
TAG_TWEET_MARKETS = 972


def _norm_bracket(m: dict) -> dict | None:
    try:
        token_ids = json.loads(m.get("clobTokenIds") or "[]")
    except (TypeError, ValueError):
        token_ids = []
    if not token_ids:
        return None
    return {
        "label": m.get("groupItemTitle") or m.get("question") or "",
        "question": m.get("question") or "",
        "condition_id": m.get("conditionId") or "",
        "yes_token": token_ids[0],
        "no_token": token_ids[1] if len(token_ids) > 1 else "",
        "best_bid": float(m["bestBid"]) if m.get("bestBid") is not None else None,
        "best_ask": float(m["bestAsk"]) if m.get("bestAsk") is not None else None,
        "spread": float(m["spread"]) if m.get("spread") is not None else None,
        "tick": float(m.get("orderPriceMinTickSize") or 0.01),
        "neg_risk": bool(m.get("negRisk")),
    }


def fetch_tweet_auctions(slug_contains: str = "", limit: int = 100) -> list[dict]:
    """All live tweet-count auctions from Gamma tag 972. ALWAYS filters out
    resolved/closed brackets (closed=true OR acceptingOrders=false) before
    anything models on them (C2). Live prices come from Gamma bestBid /
    bestAsk, NOT the raw CLOB /book (fake near-empty on-chain books)."""
    r = httpx.get(f"{GAMMA}/events",
                  params={"tag_id": TAG_TWEET_MARKETS, "closed": "false", "limit": limit},
                  timeout=30)
    r.raise_for_status()
    auctions = []
    for ev in r.json():
        slug = ev.get("slug") or ""
        if slug_contains and slug_contains not in slug:
            continue
        brackets = []
        for m in ev.get("markets", []):
            if m.get("closed") or m.get("acceptingOrders") is False:
                continue
            b = _norm_bracket(m)
            if b:
                brackets.append(b)
        if not brackets:
            continue
        win = windows.parse_slug_window(slug)
        auctions.append({
            "slug": slug,
            "title": ev.get("title") or "",
            "window_start": win[0] if win else None,
            "window_end": win[1] if win else None,
            "duration_type": windows.duration_type(*win) if win else "unknown",
            "brackets": brackets,
        })
    return auctions


def freshest_auction(auctions: list[dict], duration: str | None = None) -> dict | None:
    """Least-elapsed live auction (entry strategies want the FRESHEST, not
    the earliest-start - the old fetch_active_tracking sort bug)."""
    from datetime import datetime
    now = datetime.now(windows.ET)
    live = [a for a in auctions
            if a["window_start"] and a["window_end"]
            and a["window_start"] <= now < a["window_end"]
            and (duration is None or a["duration_type"] == duration)]
    live.sort(key=lambda a: a["window_start"], reverse=True)
    return live[0] if live else None
