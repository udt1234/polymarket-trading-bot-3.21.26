import httpx
import asyncio
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

log = logging.getLogger(__name__)

XTRACKER_BASE = "https://xtracker.polymarket.com/api"
GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"

RATE_LIMITS = {"xtracker": 0.3, "gamma": 0.5, "clob": 1.0}

# xTracker resilience: retry transient 5xx/timeouts and serve last good payload
# from a 60s cache when retries also fail. xTracker returns intermittent 500s
# and one bad call should not flag the whole bot as "Paused — Degraded".
_XTRACKER_RETRY_STATUSES = {500, 502, 503, 504}
_XTRACKER_CACHE_TTL_S = 60.0
_XTRACKER_CACHE: dict[str, tuple[float, object]] = {}


async def _xtracker_get(client: httpx.AsyncClient, url: str, params: dict | None, cache_key: str):
    """GET with 3 attempts on 5xx/timeout, exponential backoff, and stale-cache fallback.

    Raises only when both retries AND cache miss — i.e. the call is unrecoverable.
    On success, refreshes the cache. The caller still receives parsed JSON.
    """
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            res = await client.get(url, params=params)
            if res.status_code in _XTRACKER_RETRY_STATUSES:
                raise httpx.HTTPStatusError(f"xtracker {res.status_code}", request=res.request, response=res)
            res.raise_for_status()
            data = res.json()
            _XTRACKER_CACHE[cache_key] = (time.time(), data)
            return data
        except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError) as e:
            last_exc = e
            if attempt < 2:
                await asyncio.sleep(0.5 * (2 ** attempt))
    cached = _XTRACKER_CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < _XTRACKER_CACHE_TTL_S:
        log.warning(f"xtracker {cache_key} failed after retries — serving {time.time() - cached[0]:.1f}s-old cache")
        return cached[1]
    assert last_exc is not None
    raise last_exc

BRACKET_ALIASES = {
    "<20": "0-19", "20-39": "20-39", "40-59": "40-59", "60-79": "60-79",
    "80-99": "80-99", "100-119": "100-119", "120-139": "120-139",
    "140-159": "140-159", "160-179": "160-179", "180-199": "180-199",
    "200+": "200+", "≥200": "200+",
}


def normalize_bracket(raw: str) -> str:
    raw = raw.strip()
    return BRACKET_ALIASES.get(raw, raw)


async def _fetch_trackings_raw(handle: str = "realDonaldTrump", platform: str = "truthsocial") -> list:
    async with httpx.AsyncClient(timeout=15) as client:
        data = await _xtracker_get(
            client,
            f"{XTRACKER_BASE}/users/{handle}/trackings",
            {"platform": platform},
            cache_key=f"trackings:{platform}:{handle}",
        )
        trackings = data.get("data", []) if isinstance(data, dict) else data
        return trackings if isinstance(trackings, list) else []


async def fetch_active_tracking(
    handle: str = "realDonaldTrump",
    platform: str = "truthsocial",
    preferred_window_days: float | None = None,
) -> dict | None:
    """Return the currently-active tracking for `handle`.

    When multiple trackings are concurrently active (e.g. Elon has
    monthly + 7d + 2d running at once), `preferred_window_days` lets a
    module narrow to its target window length. Without it, the function
    falls back to the legacy "earliest startDate" tiebreaker — which
    incorrectly picks the monthly auction for modules that only care
    about shorter windows.
    """
    trackings = await _fetch_trackings_raw(handle, platform)
    if not trackings:
        return None

    now = datetime.now(timezone.utc)
    active = []
    for t in trackings:
        start = t.get("startDate", "")
        end = t.get("endDate", "")
        if start and end:
            s = datetime.fromisoformat(start.replace("Z", "+00:00"))
            e = datetime.fromisoformat(end.replace("Z", "+00:00"))
            if s <= now <= e:
                active.append((t, s, e))

    if not active:
        return trackings[0] if trackings else None

    # Window-preference filter: if the caller specified a target window
    # length, restrict to trackings matching it (within ±0.15 day).
    if preferred_window_days is not None:
        matched = [
            (t, s, e) for (t, s, e) in active
            if abs((e - s).total_seconds() / 86400.0 - preferred_window_days) <= 0.15
        ]
        if matched:
            active = matched

    # Tiebreaker: earliest startDate (most elapsed = most data to work with).
    active.sort(key=lambda x: x[1])
    return active[0][0]


async def fetch_active_or_upcoming_tracking(
    handle: str = "realDonaldTrump", allow_upcoming: bool = False,
    platform: str = "truthsocial",
) -> dict | None:
    """Prefer the currently active tracking; if none and allow_upcoming, return
    the nearest future tracking. Used by modules with pre_auction_buying_enabled.
    """
    trackings = await _fetch_trackings_raw(handle, platform)
    if not trackings:
        return None

    now = datetime.now(timezone.utc)
    active = []
    upcoming = []
    for t in trackings:
        start = t.get("startDate", "")
        end = t.get("endDate", "")
        if not (start and end):
            continue
        try:
            s = datetime.fromisoformat(start.replace("Z", "+00:00"))
            e = datetime.fromisoformat(end.replace("Z", "+00:00"))
        except Exception:
            continue
        if s <= now <= e:
            active.append((t, s, e))
        elif s > now:
            upcoming.append((t, s, e))

    if active:
        active.sort(key=lambda x: x[1])
        return active[0][0]
    if allow_upcoming and upcoming:
        upcoming.sort(key=lambda x: x[1])
        return upcoming[0][0]
    return None


async def fetch_recent_daily_post_counts(
    handle: str, platform: str = "x", days: int = 7,
) -> list[int]:
    """Return per-day post counts for the last `days` days (most recent last).

    Used by the pacing endpoint to compute a recent-activity prior — much
    more accurate than historical 2-day auction means for projecting fresh
    auctions. Past 2-day auction data is months old and reflects different
    activity regimes; the user's actual last-week rate predicts the next
    2 days much better.
    """
    from collections import Counter
    by_day: Counter = Counter()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"https://xtracker.polymarket.com/api/users/{handle}/posts",
                params={"platform": platform},
            )
            r.raise_for_status()
            d = r.json()
            items = d if isinstance(d, list) else (
                d.get("data") or d.get("posts") or d.get("items") or []
            )
    except Exception as e:
        log.warning(f"fetch_recent_daily_post_counts({handle}): {e}")
        return []

    for p in items:
        ca = p.get("createdAt", "") if isinstance(p, dict) else ""
        if not ca:
            continue
        try:
            dt = datetime.fromisoformat(ca.replace("Z", "+00:00"))
            by_day[dt.strftime("%Y-%m-%d")] += 1
        except (ValueError, TypeError):
            continue

    now = datetime.now(timezone.utc)
    out = []
    # Skip today (incomplete) — start from yesterday backwards
    for i in range(1, days + 1):
        day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        out.append(int(by_day.get(day, 0)))
    return list(reversed(out))  # oldest first


async def fetch_all_active_trackings(handle: str = "realDonaldTrump", platform: str = "truthsocial") -> list[dict]:
    trackings = await _fetch_trackings_raw(handle, platform)
    now = datetime.now(timezone.utc)
    active = []
    for t in trackings:
        start = t.get("startDate", "")
        end = t.get("endDate", "")
        if start and end:
            s = datetime.fromisoformat(start.replace("Z", "+00:00"))
            e = datetime.fromisoformat(end.replace("Z", "+00:00"))
            if s <= now <= e:
                elapsed = (now - s).total_seconds() / 86400
                t["_elapsed_days"] = round(elapsed, 2)
                t["_remaining_days"] = round((e - now).total_seconds() / 86400, 2)
                active.append(t)
    active.sort(key=lambda x: x.get("startDate", ""))
    return active


async def fetch_tracking_by_id(handle: str, tracking_id: str, platform: str = "truthsocial") -> dict | None:
    trackings = await _fetch_trackings_raw(handle, platform)
    for t in trackings:
        tid = t.get("id") or t.get("trackingId")
        if str(tid) == str(tracking_id):
            return t
    return None


def extract_slug_from_tracking(tracking: dict) -> str | None:
    link = tracking.get("marketLink", "")
    if not link:
        return None
    path = urlparse(link).path
    parts = path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "event":
        return parts[1]
    return parts[-1] if parts else None


async def fetch_xtracker_stats(tracking_id: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        data = await _xtracker_get(
            client,
            f"{XTRACKER_BASE}/trackings/{tracking_id}",
            {"includeStats": "true"},
            cache_key=f"stats:{tracking_id}",
        )
        return data.get("data", data) if isinstance(data, dict) else data


async def fetch_xtracker_posts(handle: str = "realDonaldTrump", platform: str = "truthsocial") -> dict:
    tracking = await fetch_active_tracking(handle, platform)
    if not tracking:
        return {}
    tracking_id = tracking.get("id") or tracking.get("trackingId")
    if not tracking_id:
        return tracking
    await asyncio.sleep(RATE_LIMITS["xtracker"])
    stats = await fetch_xtracker_stats(tracking_id)
    stats["_tracking"] = tracking
    return stats


def parse_hourly_counts(raw_data: dict) -> list[dict]:
    # xTracker returns stats.daily as list of {date, count, cumulative}
    stats = raw_data.get("stats", {})
    if isinstance(stats, dict):
        daily = stats.get("daily", [])
        if isinstance(daily, list) and daily:
            result = []
            for entry in daily:
                dt = entry.get("date", "")
                hour = int(dt[11:13]) if len(dt) > 13 else 0
                result.append({"hour": hour, "date": dt, "count": entry.get("count", 0)})
            return result

    # Fallback: check other keys
    for key in ["hourlyStats", "hourly", "data"]:
        val = raw_data.get(key)
        if isinstance(val, list) and val:
            return [{"hour": s.get("hour", 0), "date": s.get("date", ""), "count": s.get("count", 0)} for s in val]

    return []


def get_xtracker_summary(raw_data: dict) -> dict:
    stats = raw_data.get("stats", {})
    if not isinstance(stats, dict):
        return {}
    return {
        "total": stats.get("total", 0),
        "pace": stats.get("pace", 0),
        "days_elapsed": stats.get("daysElapsed", 0),
        "days_remaining": stats.get("daysRemaining", 0),
        "days_total": stats.get("daysTotal", 7),
        "percent_complete": stats.get("percentComplete", 0),
        "is_complete": stats.get("isComplete", False),
    }


def parse_daily_totals(raw_data: dict) -> list[dict]:
    hourly = parse_hourly_counts(raw_data)
    by_date: dict[str, int] = {}
    for h in hourly:
        dt = h["date"][:10]
        by_date.setdefault(dt, 0)
        by_date[dt] += h["count"]
    return [{"date": dt, "count": count} for dt, count in sorted(by_date.items())]


def compute_running_total(hourly_counts: list[dict], week_start: str | None = None) -> int:
    if week_start:
        return sum(h["count"] for h in hourly_counts if h.get("date", "") >= week_start)
    return sum(h["count"] for h in hourly_counts)


def compute_elapsed_days(week_start: str, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    start = datetime.fromisoformat(week_start.replace("Z", "+00:00")) if isinstance(week_start, str) else week_start
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return max((now - start).total_seconds() / 86400, 0.01)


async def fetch_market_prices(slug: str) -> dict[str, float]:
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.get(f"{GAMMA_BASE}/events", params={"slug": slug})
        res.raise_for_status()
        events = res.json()
        if not isinstance(events, list) or not events:
            return {}

        markets = events[0].get("markets", [])
        prices = {}
        for m in markets:
            raw_bracket = m.get("groupItemTitle", m.get("question", ""))
            bracket = normalize_bracket(raw_bracket)

            outcome_prices = m.get("outcomePrices", "[]")
            if isinstance(outcome_prices, str):
                outcome_prices = json.loads(outcome_prices)
            if outcome_prices:
                price = float(outcome_prices[0])
                if 0 < price < 1:
                    prices[bracket] = price

        return prices


async def fetch_bracket_token_ids(slug: str) -> dict[str, str]:
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.get(f"{GAMMA_BASE}/events", params={"slug": slug})
        res.raise_for_status()
        events = res.json()
        if not isinstance(events, list) or not events:
            return {}

        markets = events[0].get("markets", [])
        token_map = {}
        for m in markets:
            raw_bracket = m.get("groupItemTitle", m.get("question", ""))
            bracket = normalize_bracket(raw_bracket)
            token_ids = m.get("clobTokenIds", "[]")
            if isinstance(token_ids, str):
                token_ids = json.loads(token_ids)
            if token_ids:
                token_map[bracket] = token_ids[0]
        return token_map


async def fetch_order_books_for_brackets(slug: str, brackets: list[str]) -> dict[str, dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            res = await client.get(f"{GAMMA_BASE}/events", params={"slug": slug})
            res.raise_for_status()
            events = res.json()
            if not isinstance(events, list) or not events:
                return {}
        except Exception as e:
            log.warning(f"Gamma fetch failed for order books: {e}")
            return {}

    markets = events[0].get("markets", [])
    books = {}
    for m in markets:
        raw_bracket = m.get("groupItemTitle", m.get("question", ""))
        bracket = normalize_bracket(raw_bracket)
        if bracket not in brackets:
            continue

        best_bid = float(m.get("bestBid") or 0)
        best_ask = float(m.get("bestAsk") or 1)
        spread = float(m.get("spread") or (best_ask - best_bid))

        outcome_prices = m.get("outcomePrices", "[]")
        if isinstance(outcome_prices, str):
            outcome_prices = json.loads(outcome_prices)
        volume = float(m.get("volume", m.get("volumeNum", 0)) or 0)

        books[bracket] = {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": spread,
            "bid_depth_5": volume * 0.1,
            "ask_depth_5": volume * 0.1,
            "midpoint": (best_bid + best_ask) / 2 if best_bid and best_ask else float(outcome_prices[0]) if outcome_prices else 0,
        }
    return books


async def fetch_market_volumes(slug: str) -> dict[str, float]:
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.get(f"{GAMMA_BASE}/events", params={"slug": slug})
        res.raise_for_status()
        events = res.json()
        if not isinstance(events, list) or not events:
            return {}

        markets = events[0].get("markets", [])
        volumes = {}
        for m in markets:
            raw_bracket = m.get("groupItemTitle", m.get("question", ""))
            bracket = normalize_bracket(raw_bracket)
            vol = m.get("volume", m.get("volumeNum", 0))
            if vol:
                volumes[bracket] = float(vol)
        return volumes


async def fetch_market_prices_auto(handle: str = "realDonaldTrump", platform: str = "truthsocial") -> tuple[dict[str, float], str]:
    tracking = await fetch_active_tracking(handle, platform)
    if not tracking:
        return {}, ""
    slug = extract_slug_from_tracking(tracking)
    if not slug:
        return {}, ""
    prices = await fetch_market_prices(slug)
    return prices, slug


async def fetch_historical_weekly_totals(
    handle: str = "realDonaldTrump",
    weeks: int = 12,
    platform: str = "truthsocial",
    target_window_days: float | None = None,
) -> list[float]:
    """Return per-period totals for the most recent N completed periods.

    `target_window_days`: when set, ONLY include past trackings whose
    window length matches (within ±0.5 days). This prevents the pacing
    model from blending Elon's 7-day/monthly auctions into the prior
    for a 2-day auction (which produced absurdly high projections —
    e.g. 200+ at 74% confidence on a fresh 2-day market).
    Without this filter, callers get a mixed-window mean that's only
    valid for whatever the dominant series in the recent history is.
    """
    # Try local historical data first (from import scripts — more complete)
    local = _load_local_weekly_totals(handle, weeks, target_window_days=target_window_days)
    if local:
        return local

    trackings = await _fetch_trackings_raw(handle, platform)

    if target_window_days is not None:
        filtered = []
        for t in trackings:
            s, e = t.get("startDate", ""), t.get("endDate", "")
            if not (s and e):
                continue
            try:
                sd = datetime.fromisoformat(s.replace("Z", "+00:00"))
                ed = datetime.fromisoformat(e.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            wd = (ed - sd).total_seconds() / 86400.0
            if abs(wd - target_window_days) <= 0.5:
                filtered.append(t)
        trackings = filtered

    weekly_totals = []
    for t in trackings[:weeks]:
        metrics = t.get("metrics", {})
        if isinstance(metrics, dict) and metrics:
            total = sum(v for v in metrics.values() if isinstance(v, (int, float)))
            weekly_totals.append(float(total))
        else:
            title = t.get("title", "")
            target = t.get("target")
            if target and isinstance(target, (int, float)):
                weekly_totals.append(float(target))

    if weekly_totals:
        return list(reversed(weekly_totals))

    # No matching-window samples. If a target window was specified but no
    # samples exist for it (e.g. only 1-2 monthly auctions in the local
    # cache), scale from the unfiltered mean by window ratio. Conservative
    # fallback: use 7-day-equivalent default (100/week) and scale.
    if target_window_days is not None and target_window_days > 0:
        scaled = 100.0 * (target_window_days / 7.0)
        return [scaled] * 4
    return [100.0] * 4


def _load_local_weekly_totals(
    handle: str, weeks: int, target_window_days: float | None = None,
) -> list[float] | None:
    import json as _json
    from pathlib import Path as _Path

    path = _Path(__file__).parent.parent.parent.parent / "_DataMetricPulls" / "historical" / handle / "weekly_totals.json"
    if not path.exists():
        return None

    try:
        with open(path) as f:
            data = _json.load(f)
        if not data:
            return None

        # Window filter: if a specific auction window is requested, only
        # include past trackings of matching window length. Without this,
        # Elon's mixed-window history (2d/7d/monthly) corrupts the prior
        # for any specific-window pacing model.
        if target_window_days is not None:
            data = [
                e for e in data
                if isinstance(e.get("days"), (int, float))
                and abs(e["days"] - target_window_days) <= 0.5
            ]

        totals = [entry.get("total", 0) for entry in data if entry.get("total", 0) > 0]
        if len(totals) < 4:
            # Not enough matching-window samples — caller falls back to live xTracker
            # (which now also applies the window filter).
            return None

        return totals[-weeks:]
    except Exception:
        return None


async def fetch_order_book(token_id: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            res = await client.get(f"{CLOB_BASE}/book", params={"token_id": token_id})
            res.raise_for_status()
            book = res.json()
            bids = book.get("bids", [])
            asks = book.get("asks", [])
            best_bid = float(bids[0]["price"]) if bids else 0
            best_ask = float(asks[0]["price"]) if asks else 1
            return {
                "best_bid": best_bid, "best_ask": best_ask,
                "spread": best_ask - best_bid,
                "bid_depth_5": sum(float(b.get("size", 0)) for b in bids[:5]),
                "ask_depth_5": sum(float(a.get("size", 0)) for a in asks[:5]),
                "midpoint": (best_bid + best_ask) / 2 if best_bid and best_ask else 0,
            }
        except Exception as e:
            log.warning(f"Order book fetch failed for {token_id}: {e}")
            return {"best_bid": 0, "best_ask": 1, "spread": 1, "bid_depth_5": 0, "ask_depth_5": 0, "midpoint": 0}


async def fetch_wallet_history(address: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            res = await client.get(f"{CLOB_BASE}/trades", params={"maker_address": address, "limit": 100})
            res.raise_for_status()
            return res.json().get("data", [])
        except Exception as e:
            log.warning(f"Wallet history fetch failed: {e}")
            return []


def _bracket_sort_key(bracket: str) -> int:
    cleaned = bracket.replace("+", "").replace("<", "").replace("≥", "")
    first = cleaned.split("-")[0]
    try:
        return int(first)
    except ValueError:
        return 9999


async def fetch_market_brackets(slug: str) -> list[str]:
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
