"""
One-time dump of all realDonaldTrump posts from Supabase -> parquet.

Reads truth_social_posts in pages of 1000 (Supabase row limit) and writes
to _DataMetricPulls/trump_posts_raw.parquet with the same schema as
elon_posts_raw.parquet so the canonical builder can treat them uniformly.

Idempotent: overwrites the file every run. ~5-10 min for 32k rows.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

OUT_PARQUET = ROOT / "_DataMetricPulls" / "trump_posts_raw.parquet"
HANDLE = "realDonaldTrump"
PAGE_SIZE = 1000


def main() -> int:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    sb = create_client(url, key)

    print(f"[dump] handle={HANDLE} -> {OUT_PARQUET}")
    rows: list[dict] = []
    offset = 0
    t0 = time.time()
    while True:
        end = offset + PAGE_SIZE - 1
        res = (
            sb.table("truth_social_posts")
            .select("id,account_id,handle,created_at,is_reply,is_reblog,in_reply_to_id,reblog_of_id,raw")
            .eq("handle", HANDLE)
            .order("created_at", desc=False)
            .range(offset, end)
            .execute()
        )
        batch = res.data or []
        if not batch:
            break
        rows.extend(batch)
        print(f"[dump] page offset={offset} got={len(batch)} total={len(rows)} elapsed={time.time()-t0:.1f}s")
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    if not rows:
        print("[dump] no rows returned, aborting")
        return 1

    df = pd.DataFrame(rows)
    # mirror elon_posts_raw schema: id, userId, platformId, content, createdAt, importedAt, metrics, dt_utc
    # Trump raw lives in `raw` jsonb — extract content + metrics from it
    def _extract_content(r):
        try:
            if isinstance(r, str):
                r = json.loads(r)
            return r.get("content") or r.get("text") or ""
        except Exception:
            return ""

    def _extract_metrics(r):
        try:
            if isinstance(r, str):
                r = json.loads(r)
            return {
                "favourites_count": r.get("favourites_count"),
                "reblogs_count": r.get("reblogs_count"),
                "replies_count": r.get("replies_count"),
            }
        except Exception:
            return {}

    df["content"] = df["raw"].apply(_extract_content)
    df["metrics"] = df["raw"].apply(_extract_metrics)
    df["dt_utc"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
    # rename for parity with elon_posts_raw
    df_out = pd.DataFrame({
        "id": df["id"],
        "userId": df["account_id"],
        "platformId": "truth_social",
        "content": df["content"],
        "createdAt": df["created_at"],
        "importedAt": None,
        "metrics": df["metrics"],
        "dt_utc": df["dt_utc"],
        "handle": df["handle"],
        "is_reply": df["is_reply"],
        "is_reblog": df["is_reblog"],
        "in_reply_to_id": df["in_reply_to_id"],
        "reblog_of_id": df["reblog_of_id"],
    })
    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_parquet(OUT_PARQUET, index=False)
    print(f"[dump] wrote {len(df_out):,} rows to {OUT_PARQUET}")
    print(f"[dump] date range: {df_out['dt_utc'].min()} -> {df_out['dt_utc'].max()}")
    print(f"[dump] elapsed: {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
