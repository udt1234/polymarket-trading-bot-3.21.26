import httpx
import io
import logging
from datetime import datetime

log = logging.getLogger(__name__)

POLYMARKET_DATA_BASE = "https://data.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"


async def search_markets(query: str, limit: int = 20, active: bool = True) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        params = {"_q": query, "_limit": limit}
        if active:
            params["active"] = "true"
        res = await client.get(f"{GAMMA_BASE}/markets", params=params)
        res.raise_for_status()
        markets = res.json()
        return [
            {
                "id": m.get("id"),
                "question": m.get("question", ""),
                "slug": m.get("slug", ""),
                "condition_id": m.get("conditionId", ""),
                "clob_token_ids": m.get("clobTokenIds", []),
                "outcome_prices": m.get("outcomePrices", "[]"),
                "volume": m.get("volume", 0),
                "liquidity": m.get("liquidity", 0),
                "end_date": m.get("endDate"),
                "active": m.get("active", False),
                "closed": m.get("closed", False),
                "group_item_title": m.get("groupItemTitle", ""),
            }
            for m in markets
        ]


async def fetch_parquet_urls(condition_id: str) -> dict:
    return {
        "trades": f"{POLYMARKET_DATA_BASE}/trades/{condition_id}.parquet",
        "orderbook_snapshots": f"{POLYMARKET_DATA_BASE}/orderbook-snapshots/{condition_id}.parquet",
        "price_history": f"{POLYMARKET_DATA_BASE}/price-history/{condition_id}.parquet",
    }


async def download_parquet(url: str, save_path: str) -> dict:
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        try:
            res = await client.get(url)
            if res.status_code == 404:
                return {"status": "not_found", "url": url}
            res.raise_for_status()

            with open(save_path, "wb") as f:
                f.write(res.content)

            size_mb = len(res.content) / (1024 * 1024)
            log.info(f"Downloaded {url} -> {save_path} ({size_mb:.1f}MB)")
            return {"status": "ok", "path": save_path, "size_mb": round(size_mb, 2)}
        except httpx.HTTPStatusError as e:
            return {"status": "error", "url": url, "code": e.response.status_code}
        except Exception as e:
            return {"status": "error", "url": url, "error": str(e)}


async def fetch_market_history(condition_id: str, data_dir: str = "data/parquet") -> dict:
    import os
    os.makedirs(data_dir, exist_ok=True)

    urls = await fetch_parquet_urls(condition_id)
    results = {}
    for data_type, url in urls.items():
        save_path = f"{data_dir}/{condition_id}_{data_type}.parquet"
        results[data_type] = await download_parquet(url, save_path)

    return {
        "condition_id": condition_id,
        "results": results,
    }


async def search_and_fetch(query: str, data_dir: str = "data/parquet") -> list[dict]:
    markets = await search_markets(query, limit=10, active=False)
    results = []
    for market in markets:
        cid = market.get("condition_id")
        if not cid:
            continue
        result = await fetch_market_history(cid, data_dir)
        result["question"] = market["question"]
        result["slug"] = market["slug"]
        results.append(result)
    return results
