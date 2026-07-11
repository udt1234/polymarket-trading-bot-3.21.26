"""Sports-sweep data: discover live game moneyline markets + read their books.

Generic across sports series (MLB/NBA/NHL/NFL). Live book prices come from
Gamma bestBid/bestAsk (C2). A game is 'decided' when the favorite's best_bid
>= the configured threshold."""
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger(__name__)

GAMMA = "https://gamma-api.polymarket.com"
# base moneyline slug, e.g. mlb-col-lad-2026-07-08 (game date in the slug, NOT
# startDate which is the listing date)
BASE_GAME_RE = re.compile(r"^[a-z]+-[a-z0-9]+-[a-z0-9]+-(\d{4}-\d{2}-\d{2})$")


def live_games(series_ids: list[int]) -> list[dict]:
    """Open moneyline game markets whose game date is today (+/-1 day).
    Returns one dict per game with both sides' live bid/ask/tokens."""
    out = []
    today = datetime.now(timezone.utc).date()
    with httpx.Client(timeout=30) as c:
        for sid in series_ids:
            try:
                r = c.get(f"{GAMMA}/events", params={
                    "series_id": str(sid), "limit": 300, "closed": "false",
                    "order": "startDate", "ascending": "true"})
                evs = r.json() if r.status_code == 200 else []
            except Exception:
                log.exception("live_games fetch failed for series %s", sid)
                continue
            for e in evs:
                slug = e.get("slug") or ""
                m = BASE_GAME_RE.match(slug)
                if not m:
                    continue
                try:
                    gdate = datetime.strptime(m.group(1), "%Y-%m-%d").date()
                except ValueError:
                    continue
                if not (today - timedelta(days=1) <= gdate <= today + timedelta(days=1)):
                    continue
                # first market of the base event = the moneyline (team wins)
                mk = (e.get("markets") or [None])[0]
                if not mk or mk.get("closed") or mk.get("acceptingOrders") is False:
                    continue
                try:
                    toks = json.loads(mk.get("clobTokenIds") or "[]")
                    outs = json.loads(mk.get("outcomes") or "[]")
                except (TypeError, ValueError):
                    continue
                if len(toks) != 2:
                    continue
                sides = []
                for i, tok in enumerate(toks):
                    sides.append({
                        "token": tok, "outcome": outs[i] if i < len(outs) else "",
                        "best_bid": _f(mk.get("bestBid")),
                        "best_ask": _f(mk.get("bestAsk")),
                        "spread": _f(mk.get("spread")),
                        "tick": float(mk.get("orderPriceMinTickSize") or 0.01)})
                out.append({"slug": slug, "condition_id": mk.get("conditionId"),
                            "sides": sides})
    return out


def _f(v):
    return float(v) if v is not None else None


def decided_favorite(game: dict, threshold: float) -> dict | None:
    """The side that is the decided favorite (best_bid >= threshold), or None."""
    fav = max(game["sides"], key=lambda s: s["best_bid"] or 0)
    if (fav["best_bid"] or 0) >= threshold:
        return fav
    return None
