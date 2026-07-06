"""Tweet counting (BUILD_SPEC C4).

Live count source order: TwitterAPI.io stream (Step 5, hot path) ->
xTracker (fallback/cross-check, used by the slow path today). UMA on-chain
is the true resolver. counts_for_auction() is the LOCKED Elon rule,
validated to within 2-3 tweets of xTracker.
"""

import logging

import httpx

log = logging.getLogger(__name__)

ELON_USER_ID = "44196397"
XTRACKER = "https://xtracker.polymarket.com/api"


def counts_for_auction(tweet: dict, handle_user_id: str = ELON_USER_ID) -> bool:
    """LOCKED counting rule: originals + quotes + reposts + main-feed
    self-replies count. Pure replies to OTHERS do not. (Community reposts
    are excluded by xTracker but indistinguishable in raw fields - the
    xTracker cross-check absorbs that gap.)"""
    reply_to = tweet.get("in_reply_to_user_id")
    if reply_to and str(reply_to) != str(handle_user_id):
        return False
    return True


def fetch_tracking_for_slug(slug: str, handle: str = "elonmusk",
                            platform: str = "x") -> dict | None:
    """Match the xTracker tracking whose marketLink ends with the event slug."""
    r = httpx.get(f"{XTRACKER}/users/{handle}/trackings",
                  params={"platform": platform}, timeout=30)
    r.raise_for_status()
    items = r.json()
    if isinstance(items, dict):
        items = items.get("data", [])
    tail = slug.split("/")[-1]
    for t in items:
        if (t.get("marketLink") or "").rstrip("/").endswith(tail):
            return t
    return None


def current_count(tracking_id: str) -> int | None:
    """In-window count so far per xTracker. None on failure (fail closed
    upstream - a module must not trade on a missing count). Sync httpx so
    it is callable from both sync cycles and asyncio.run contexts."""
    try:
        r = httpx.get(f"{XTRACKER}/trackings/{tracking_id}",
                      params={"includeStats": "true"}, timeout=15)
        r.raise_for_status()
        data = r.json()
        data = data.get("data", data) if isinstance(data, dict) else data
        stats = data.get("stats") or {}
        return int(stats.get("total") or 0)
    except Exception:
        log.exception("xTracker count fetch failed for %s", tracking_id)
        return None
