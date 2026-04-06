import logging
from pathlib import Path
from collections import defaultdict

import httpx
import pandas as pd

log = logging.getLogger(__name__)

POLYMARKET_S3_BASE = "https://data.polymarket.com"
PARQUET_CACHE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "parquet"


def _ensure_cache_dir():
    PARQUET_CACHE_DIR.mkdir(parents=True, exist_ok=True)


async def search_parquet_markets(query: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.get(
            f"{POLYMARKET_S3_BASE}/markets",
            params={"query": query, "format": "parquet"},
        )
        if res.status_code != 200:
            log.warning(f"Parquet search failed: {res.status_code}")
            return []
        data = res.json()
        results = data if isinstance(data, list) else data.get("data", [])
        return [
            {
                "market_slug": m.get("slug", m.get("market_slug", "")),
                "title": m.get("title", m.get("question", "")),
                "resolved": m.get("resolved", False),
                "start_date": m.get("start_date", m.get("startDate", "")),
                "end_date": m.get("end_date", m.get("endDate", "")),
                "brackets": m.get("brackets", m.get("outcomes", [])),
            }
            for m in results
        ]


async def download_and_cache_parquet(market_slug: str) -> pd.DataFrame:
    _ensure_cache_dir()
    cache_path = PARQUET_CACHE_DIR / f"{market_slug}.parquet"

    if cache_path.exists():
        return pd.read_parquet(cache_path)

    url = f"{POLYMARKET_S3_BASE}/parquet/{market_slug}.parquet"
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        res = await client.get(url)
        res.raise_for_status()
        cache_path.write_bytes(res.content)

    df = pd.read_parquet(cache_path)
    expected_cols = {"timestamp", "bracket", "price", "volume"}
    existing = set(df.columns)
    col_map = {}
    if "outcome" in existing and "bracket" not in existing:
        col_map["outcome"] = "bracket"
    if "t" in existing and "timestamp" not in existing:
        col_map["t"] = "timestamp"
    if "p" in existing and "price" not in existing:
        col_map["p"] = "price"
    if "v" in existing and "volume" not in existing:
        col_map["v"] = "volume"
    if col_map:
        df = df.rename(columns=col_map)

    return df


def preview_parquet_data(market_slug: str) -> dict:
    cache_path = PARQUET_CACHE_DIR / f"{market_slug}.parquet"
    if not cache_path.exists():
        return {"error": "No cached data. Download first."}
    df = pd.read_parquet(cache_path)
    return {
        "market_slug": market_slug,
        "rows": len(df),
        "columns": list(df.columns),
        "brackets": sorted(df["bracket"].unique().tolist()) if "bracket" in df.columns else [],
        "date_range": {
            "start": str(df["timestamp"].min()) if "timestamp" in df.columns else None,
            "end": str(df["timestamp"].max()) if "timestamp" in df.columns else None,
        },
        "sample": df.head(5).to_dict(orient="records"),
    }


def historical_price_pattern(
    running_total: int, elapsed_days: float,
    cached_data: pd.DataFrame, brackets: list[str],
) -> dict[str, float] | None:
    if cached_data.empty or "bracket" not in cached_data.columns:
        return None

    total_lo = running_total * 0.85
    total_hi = running_total * 1.15
    elapsed_lo = elapsed_days - 0.5
    elapsed_hi = elapsed_days + 0.5

    if "running_total" not in cached_data.columns or "elapsed_days" not in cached_data.columns:
        return None

    matches = cached_data[
        (cached_data["running_total"] >= total_lo)
        & (cached_data["running_total"] <= total_hi)
        & (cached_data["elapsed_days"] >= elapsed_lo)
        & (cached_data["elapsed_days"] <= elapsed_hi)
    ]

    if len(matches) < 3:
        return None

    if "actual_bracket" not in matches.columns:
        return None

    counts = matches["actual_bracket"].value_counts()
    total = counts.sum()
    probs = {}
    for b in brackets:
        probs[b] = round(counts.get(b, 0) / total, 4)
    return probs


def build_historical_lookup(parquet_df: pd.DataFrame) -> dict:
    if parquet_df.empty:
        return {}
    required = {"running_total", "elapsed_days", "actual_bracket"}
    if not required.issubset(set(parquet_df.columns)):
        return {}

    lookup = defaultdict(lambda: defaultdict(int))
    for _, row in parquet_df.iterrows():
        rt_bucket = int(row["running_total"] // 10) * 10
        ed_bucket = round(row["elapsed_days"] * 2) / 2
        bracket = row["actual_bracket"]
        lookup[(rt_bucket, ed_bucket)][bracket] += 1

    return {k: dict(v) for k, v in lookup.items()}
