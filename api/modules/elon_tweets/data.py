import logging
from api.modules.truth_social.data import (
    fetch_active_tracking as _fetch_active_tracking,
    extract_slug_from_tracking,
    fetch_xtracker_posts as _fetch_xtracker_posts,
    fetch_market_prices,
    fetch_historical_weekly_totals as _fetch_historical_weekly_totals,
    parse_hourly_counts,
    compute_running_total,
    compute_elapsed_days,
    GAMMA_BASE,
)

log = logging.getLogger(__name__)

HANDLE = "elonmusk"
PLATFORM = "x"


async def fetch_active_tracking(handle: str = HANDLE) -> dict | None:
    return await _fetch_active_tracking(handle)


async def fetch_xtracker_posts(handle: str = HANDLE) -> dict:
    return await _fetch_xtracker_posts(handle)


async def fetch_historical_weekly_totals(handle: str = HANDLE, weeks: int = 12) -> list[float]:
    return await _fetch_historical_weekly_totals(handle, weeks)


async def fetch_market_brackets(slug: str) -> list[str]:
    import httpx
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.get(f"{GAMMA_BASE}/events", params={"slug": slug})
        res.raise_for_status()
        events = res.json()
        if not isinstance(events, list) or not events:
            return []

        markets = events[0].get("markets", [])
        brackets = []
        for m in markets:
            raw = m.get("groupItemTitle", m.get("question", ""))
            if raw:
                brackets.append(raw.strip())
        return sorted(brackets, key=_bracket_sort_key)


def _bracket_sort_key(bracket: str) -> int:
    cleaned = bracket.replace("+", "").replace("<", "").replace("≥", "")
    first = cleaned.split("-")[0]
    try:
        return int(first)
    except ValueError:
        return 9999
