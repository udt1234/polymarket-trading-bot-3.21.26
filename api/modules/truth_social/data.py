import httpx
import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

log = logging.getLogger(__name__)

XTRACKER_BASE = "https://xtracker.polymarket.com/api"
GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"

RATE_LIMITS = {"xtracker": 0.3, "gamma": 0.5, "clob": 1.0}

BRACKET_ALIASES = {
    "<20": "0-19", "20-39": "20-39", "40-59": "40-59", "60-79": "60-79",
    "80-99": "80-99", "100-119": "100-119", "120-139": "120-139",
    "140-159": "140-159", "160-179": "160-179", "180-199": "180-199",
    "200+": "200+", "≥200": "200+",
}


def normalize_bracket(raw: str) -> str:
    raw = raw.strip()
    return BRACKET_ALIASES.get(raw, raw)


async def _fetch_trackings_raw(handle: str = "realDonaldTrump") -> list:
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.get(
            f"{XTRACKER_BASE}/users/{handle}/trackings",
            params={"platform": "truthsocial"},
        )
        res.raise_for_status()
        data = res.json()
        trackings = data.get("data", []) if isinstance(data, dict) else data
        return trackings if isinstance(trackings, list) else []


async def fetch_active_tracking(handle: str = "realDonaldTrump") -> dict | None:
    trackings = await _fetch_trackings_raw(handle)
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

    # Prefer the tracking with the earliest startDate (most elapsed time)
    active.sort(key=lambda x: x[1])
    return active[0][0]


async def fetch_all_active_trackings(handle: str = "realDonaldTrump") -> list[dict]:
    trackings = await _fetch_trackings_raw(handle)
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


async def fetch_tracking_by_id(handle: str, tracking_id: str) -> dict | None:
    trackings = await _fetch_trackings_raw(handle)
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
        res = await client.get(
            f"{XTRACKER_BASE}/trackings/{tracking_id}",
            params={"includeStats": "true"},
        )
        res.raise_for_status()
        data = res.json()
        return data.get("data", data) if isinstance(data, dict) else data


async def fetch_xtracker_posts(handle: str = "realDonaldTrump") -> dict:
    tracking = await fetch_active_tracking(handle)
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


async def fetch_market_prices_auto(handle: str = "realDonaldTrump") -> tuple[dict[str, float], str]:
    tracking = await fetch_active_tracking(handle)
    if not tracking:
        return {}, ""
    slug = extract_slug_from_tracking(tracking)
    if not slug:
        return {}, ""
    prices = await fetch_market_prices(slug)
    return prices, slug


async def fetch_historical_weekly_totals(handle: str = "realDonaldTrump", weeks: int = 12) -> list[float]:
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.get(
            f"{XTRACKER_BASE}/users/{handle}/trackings",
            params={"platform": "truthsocial"},
        )
        res.raise_for_status()
        data = res.json()
        trackings = data.get("data", []) if isinstance(data, dict) else data

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

    return list(reversed(weekly_totals)) if weekly_totals else [100.0] * 4


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
