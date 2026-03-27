import logging
import os
import httpx

log = logging.getLogger(__name__)

POLYMARKET_DATA_BASE = "https://data.polymarket.com"

try:
    import pyarrow.parquet as pq
    HAS_PYARROW = True
except ImportError:
    HAS_PYARROW = False
    log.warning("pyarrow not installed, parquet loading unavailable — falling back to Gamma API")


async def search_available_data(query: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(
                f"{POLYMARKET_DATA_BASE}/markets",
                params={"query": query, "limit": 20},
            )
            res.raise_for_status()
            data = res.json()
        return [
            {
                "slug": m.get("slug", ""),
                "title": m.get("title", m.get("question", "")),
                "has_parquet": True,
            }
            for m in (data if isinstance(data, list) else data.get("markets", data.get("data", [])))
        ]
    except Exception as e:
        log.warning(f"Parquet search error: {e}")
        return []


async def download_parquet(market_slug: str, dest_dir: str = "data/") -> str:
    if not HAS_PYARROW:
        raise RuntimeError("pyarrow is not installed")

    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, f"{market_slug}.parquet")

    url = f"{POLYMARKET_DATA_BASE}/trades/{market_slug}.parquet"
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            res = await client.get(url)
            res.raise_for_status()
            with open(dest_path, "wb") as f:
                f.write(res.content)
        log.info(f"Downloaded parquet: {dest_path} ({len(res.content)} bytes)")
        return dest_path
    except Exception as e:
        log.warning(f"Parquet download failed: {e}")
        raise


def load_parquet(file_path: str) -> list[dict]:
    if not HAS_PYARROW:
        raise RuntimeError("pyarrow is not installed")

    table = pq.read_table(file_path)
    return table.to_pydict()  # column-oriented dict


def parquet_to_price_series(data: dict | list) -> list[dict]:
    if isinstance(data, list):
        return [
            {
                "timestamp": row.get("timestamp", row.get("time", "")),
                "price": float(row.get("price", 0)),
                "volume": float(row.get("volume", row.get("size", 0))),
            }
            for row in data
        ]

    timestamps = data.get("timestamp", data.get("time", []))
    prices = data.get("price", [])
    volumes = data.get("volume", data.get("size", [0] * len(prices)))

    series = []
    for i in range(len(prices)):
        series.append({
            "timestamp": str(timestamps[i]) if i < len(timestamps) else "",
            "price": float(prices[i]),
            "volume": float(volumes[i]) if i < len(volumes) else 0,
        })

    series.sort(key=lambda x: x["timestamp"])
    return series
