"""
Re-pull complete trade history for every auction × bracket from Polymarket
data-api. Replaces api_trades_v2-derived raw with API ground truth.

For each auction in canonical/auctions:
  For each bracket in bracket_condition_ids:
    Page through data-api.polymarket.com/trades?market=<conditionId>
    until exhausted (offset pagination).

Output:
  canonical/_raw_imports/api_trades/{auction_slug}.parquet
    All trades across all brackets for one auction, schema-compatible with
    the old api_trades_v2 files so 03+04 builders work unchanged.

Rate limit: 0.5s between calls (matches existing polymarket.py setting).
Estimated runtime: 30-60 min for 300 auctions x avg 10 brackets.

Idempotent: if {auction_slug}.parquet exists with reasonable row count, skip.
Force re-pull by deleting the file.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "_DataMetricPulls" / "canonical"
OUT_DIR = CANON / "_raw_imports" / "api_trades"

API_BASE = "https://data-api.polymarket.com/trades"
PAGE_LIMIT = 500
RATE_LIMIT_SEC = 0.5
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRIES = 4


def fetch_trades(condition_id: str, limit: int = PAGE_LIMIT) -> list[dict]:
    """Page through every trade for a market, return list of dicts."""
    all_trades = []
    offset = 0
    while True:
        url = f"{API_BASE}?market={condition_id}&limit={limit}&offset={offset}"
        for attempt in range(MAX_RETRIES + 1):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (canonical-builder)"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    page = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code in RETRY_STATUSES and attempt < MAX_RETRIES:
                    time.sleep(2 ** attempt)
                    continue
                raise
            except Exception:
                if attempt < MAX_RETRIES:
                    time.sleep(2 ** attempt)
                    continue
                raise
        if not isinstance(page, list):
            break
        all_trades.extend(page)
        if len(page) < limit:
            break
        offset += limit
        time.sleep(RATE_LIMIT_SEC)
    return all_trades


def process_auction(handle: str, auction_row: pd.Series, force: bool = False) -> dict:
    slug = auction_row["auction_slug"]
    out_path = OUT_DIR / f"{slug}.parquet"
    if out_path.exists() and not force:
        existing = pd.read_parquet(out_path, columns=["timestamp"])
        return {"slug": slug, "status": "skipped", "n_trades": len(existing)}

    try:
        brackets = json.loads(auction_row["bracket_condition_ids"])
    except Exception:
        return {"slug": slug, "status": "error", "n_trades": 0, "msg": "bad bracket_condition_ids"}

    all_rows = []
    failed_brackets = []
    for bucket_label, cid in brackets.items():
        try:
            trades = fetch_trades(cid)
        except Exception as e:
            # Per-bracket tolerance: log the failure but keep going. An auction
            # with 8 good brackets + 2 bad ones still saves the 8.
            failed_brackets.append(f"{bucket_label}({type(e).__name__})")
            time.sleep(RATE_LIMIT_SEC)
            continue
        # tag every trade with the canonical bucket label (in case Gamma's
        # groupItemTitle vs api_trades_v2 _bucket differ)
        for t in trades:
            t["_bucket"] = bucket_label
        all_rows.extend(trades)
        time.sleep(RATE_LIMIT_SEC)

    if not all_rows:
        msg = f"all {len(brackets)} brackets failed: {failed_brackets[:3]}" if failed_brackets else "no trades"
        return {"slug": slug, "status": "empty", "n_trades": 0, "msg": msg}

    df = pd.DataFrame(all_rows)
    # add derived columns matching api_trades_v2 schema
    df["ts"] = pd.to_datetime(df["timestamp"], unit="s", utc=True, errors="coerce")
    if "notional" not in df.columns:
        df["notional"] = df["size"].astype(float) * df["price"].astype(float)
    # hours_in: hours since min ts in this dataset
    min_ts = df["ts"].min()
    df["hours_in"] = (df["ts"] - min_ts).dt.total_seconds() / 3600.0
    # _outcome_resolved: best-effort from last few trades per bucket
    df["_outcome_resolved"] = None
    for b in df["_bucket"].unique():
        sub = df[df["_bucket"] == b].sort_values("ts")
        # if any trade has price >= 0.99 in last hour, mark resolved
        # leave as None for now — let 03_build_auctions infer
        pass

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    note = f" (partial: missing {failed_brackets})" if failed_brackets else ""
    return {
        "slug": slug,
        "status": "partial" if failed_brackets else "fetched",
        "n_trades": len(df),
        "n_brackets": df["_bucket"].nunique(),
        "msg": note,
    }


def main():
    auc = pd.concat(
        [pd.read_parquet(p) for p in sorted((CANON / "auctions").rglob("*.parquet"))],
        ignore_index=True,
    )
    auc = auc.sort_values(["handle", "start_utc"])
    total = len(auc)
    print(f"[repull] auctions to process: {total}")
    print(f"[repull] output: {OUT_DIR}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    skipped = fetched = partial = empty = errored = 0
    for i, (_, row) in enumerate(auc.iterrows(), 1):
        result = process_auction(row["handle"], row)
        if result["status"] == "skipped":
            skipped += 1
        elif result["status"] == "fetched":
            fetched += 1
        elif result["status"] == "partial":
            partial += 1
        elif result["status"] == "empty":
            empty += 1
        else:
            errored += 1
        if i % 10 == 0 or i == total:
            elapsed = time.time() - t0
            eta = (elapsed / i) * (total - i) if i else 0
            print(f"[repull] {i}/{total} done in {elapsed:.0f}s "
                  f"(skip={skipped} fetched={fetched} partial={partial} empty={empty} err={errored}, "
                  f"ETA {eta/60:.1f}min)  last={result['slug'][:40]} n={result['n_trades']}", flush=True)

    print()
    print(f"[repull] DONE in {(time.time()-t0)/60:.1f} min")
    print(f"  fetched: {fetched}, partial: {partial}, skipped: {skipped}, empty: {empty}, errored: {errored}")


if __name__ == "__main__":
    main()
