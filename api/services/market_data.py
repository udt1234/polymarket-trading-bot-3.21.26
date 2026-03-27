import httpx
import asyncio
import logging

log = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
XTRACKER_BASE = "https://xtracker.polymarket.com/api"

RATE_LIMITS = {"xtracker": 0.3, "gamma": 0.5, "clob": 1.0}


async def get_event_markets(slug: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        res = await client.get(f"{GAMMA_BASE}/events", params={"slug": slug})
        res.raise_for_status()
        data = res.json()
        if isinstance(data, list) and data:
            return data[0].get("markets", [])
        return []


async def get_clob_midpoint(token_id: str) -> float | None:
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(f"{CLOB_BASE}/midpoint", params={"token_id": token_id})
            res.raise_for_status()
            return float(res.json().get("mid", 0))
        except Exception:
            return None


async def get_market_prices(slug: str) -> dict[str, float]:
    markets = await get_event_markets(slug)
    prices = {}
    for m in markets:
        bracket = m.get("groupItemTitle", "")
        clob_ids = m.get("clobTokenIds", [])
        if clob_ids:
            mid = await get_clob_midpoint(clob_ids[0])
            await asyncio.sleep(RATE_LIMITS["clob"])
            if mid is not None:
                prices[bracket] = mid
                continue
        outcome_prices = m.get("outcomePrices", "[]")
        if isinstance(outcome_prices, str):
            import json
            outcome_prices = json.loads(outcome_prices)
        if outcome_prices:
            prices[bracket] = float(outcome_prices[0])
    return prices


async def get_xtracker_trackings(handle: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{XTRACKER_BASE}/users/{handle}/trackings",
            params={"platform": "truthsocial"},
        )
        res.raise_for_status()
        return res.json().get("data", [])


async def get_xtracker_stats(tracking_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{XTRACKER_BASE}/trackings/{tracking_id}",
            params={"includeStats": "true"},
        )
        res.raise_for_status()
        return res.json().get("data", {})
