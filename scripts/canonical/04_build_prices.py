"""
Phase 2 — Build canonical/prices/{handle}/{YYYY-MM}.parquet

Hourly OHLC per (market, bucket, hour) aggregated from whale_analysis trades.
Includes trade-derived orderbook proxies (no L2 history exists pre-Mar 2026).

Output schema (one row per market+bucket+hour):
  handle                       str
  auction_slug                 str    parent event slug
  bucket                       str    bracket label (e.g. '<40', '40-49')
  condition_id                 str    PER-BUCKET Polymarket conditionId (the
                                      tradeable market for this bracket)
  asset_yes_token_id           str    YES outcome ERC-1155 token id
  asset_no_token_id            str    NO outcome ERC-1155 token id
  hour_utc                     tz
  hour_et                      tz
  open                         float
  high                         float
  low                          float
  close                        float
  n_trades                     int
  vol_usd                      float
  vol_shares                   float
  unique_traders               int
  derived_spread               float   high - low (proxy for bid-ask)
  derived_fill_minutes         int     unique minutes with at least 1 trade (out of 60)
  derived_depth_buy_low        float   shares traded at price <= 0.05 (Spike entry tier)
  derived_depth_sell_high      float   shares traded at price >= 0.30 (Spike exit tier)

Partitioning: handle/YYYY-MM (by hour_utc).
"""
from __future__ import annotations

import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "_DataMetricPulls" / "canonical" / "_raw_imports" / "api_trades_v2"
OUT_DIR = ROOT / "_DataMetricPulls" / "canonical" / "prices"
ET = ZoneInfo("America/New_York")


def detect_handle(slug: str) -> str:
    s = slug.lower()
    if "elon-musk" in s or "elonmusk" in s:
        return "elonmusk"
    if "trump" in s or "president-trump" in s:
        return "realDonaldTrump"
    return ""


def build_prices_chunk(handle: str) -> pd.DataFrame:
    """Aggregate trades into hourly OHLC per bucket for a handle."""
    files = sorted(RAW_DIR.glob("*.parquet"))
    chunks = []
    for f in files:
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue
        if len(df) == 0:
            continue
        slug = str(df["eventSlug"].iloc[0]) if "eventSlug" in df.columns else f.name
        h = detect_handle(slug)
        if h != handle:
            continue
        df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        df = df.dropna(subset=["ts"]).sort_values("ts")
        if len(df) == 0:
            continue
        # only consider Yes-outcome trades to keep prices on a consistent side
        # (Yes price = probability the bucket wins; mirrored from No trades)
        df["yes_price"] = df.apply(
            lambda r: r["price"] if r["outcome"] == "Yes" else (1.0 - r["price"]),
            axis=1,
        )
        df["hour_utc"] = df["ts"].dt.floor("h")
        df["minute"] = df["ts"].dt.floor("min")

        # PER-BUCKET identifiers (each bracket = its own Polymarket market)
        # condition_id is unique per bucket. asset (token_id) is unique per
        # (bucket, outcome) — i.e. each bracket has a YES token and a NO token.
        bucket_cid = df.groupby("_bucket")["conditionId"].agg(lambda s: s.iloc[0])
        yes_tokens = df[df["outcome"] == "Yes"].groupby("_bucket")["asset"].agg(lambda s: s.iloc[0] if len(s) else "")
        no_tokens = df[df["outcome"] == "No"].groupby("_bucket")["asset"].agg(lambda s: s.iloc[0] if len(s) else "")

        # group by (bucket, hour) for OHLC aggregation
        grp = df.groupby(["_bucket", "hour_utc"])

        agg = grp.agg(
            open=("yes_price", "first"),
            high=("yes_price", "max"),
            low=("yes_price", "min"),
            close=("yes_price", "last"),
            n_trades=("yes_price", "size"),
            vol_usd=("notional", "sum"),
            vol_shares=("size", "sum"),
            unique_traders=("proxyWallet", "nunique"),
            fill_minutes=("minute", "nunique"),
        ).reset_index()

        # derived depth proxies
        depth_low = df[df["yes_price"] <= 0.05].groupby(["_bucket", "hour_utc"])["size"].sum().rename("derived_depth_buy_low")
        depth_high = df[df["yes_price"] >= 0.30].groupby(["_bucket", "hour_utc"])["size"].sum().rename("derived_depth_sell_high")
        agg = agg.merge(depth_low, on=["_bucket", "hour_utc"], how="left")
        agg = agg.merge(depth_high, on=["_bucket", "hour_utc"], how="left")
        agg["derived_depth_buy_low"] = agg["derived_depth_buy_low"].fillna(0.0)
        agg["derived_depth_sell_high"] = agg["derived_depth_sell_high"].fillna(0.0)

        agg["derived_spread"] = agg["high"] - agg["low"]
        agg = agg.rename(columns={"_bucket": "bucket", "fill_minutes": "derived_fill_minutes"})
        agg["hour_et"] = agg["hour_utc"].dt.tz_convert(ET)
        agg["handle"] = handle
        agg["auction_slug"] = slug
        # per-bucket Polymarket identifiers
        agg["condition_id"] = agg["bucket"].map(bucket_cid).astype(str)
        agg["asset_yes_token_id"] = agg["bucket"].map(yes_tokens).fillna("").astype(str)
        agg["asset_no_token_id"] = agg["bucket"].map(no_tokens).fillna("").astype(str)
        chunks.append(agg)
    if not chunks:
        return pd.DataFrame()
    out = pd.concat(chunks, ignore_index=True)
    # reorder columns
    cols = [
        "handle", "auction_slug", "bucket",
        "condition_id", "asset_yes_token_id", "asset_no_token_id",
        "hour_utc", "hour_et",
        "open", "high", "low", "close",
        "n_trades", "vol_usd", "vol_shares", "unique_traders",
        "derived_spread", "derived_fill_minutes",
        "derived_depth_buy_low", "derived_depth_sell_high",
    ]
    return out[cols]


def write_partitions(df: pd.DataFrame, handle: str):
    if not len(df):
        print(f"  no rows for {handle}, skipping")
        return
    out_base = OUT_DIR / handle
    if out_base.exists():
        for p in out_base.rglob("*.parquet"):
            p.unlink()
    df["_part"] = df["hour_utc"].dt.strftime("%Y-%m")
    for part, sub in df.groupby("_part"):
        out = out_base / f"{part}.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        sub.drop(columns=["_part"]).to_parquet(out, index=False)
        print(f"  wrote {out.relative_to(ROOT)}: {len(sub):,} hourly rows")


def main() -> int:
    for handle in ["elonmusk", "realDonaldTrump"]:
        print(f"[prices] building hourly OHLC for {handle}...")
        df = build_prices_chunk(handle)
        print(f"  total rows: {len(df):,}")
        if len(df):
            print(f"  date range: {df['hour_utc'].min()} -> {df['hour_utc'].max()}")
            print(f"  unique auctions: {df['auction_slug'].nunique()}")
            print(f"  unique buckets: {df['bucket'].nunique()}")
        write_partitions(df, handle)
    print(f"\n[prices] DONE. Output: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
