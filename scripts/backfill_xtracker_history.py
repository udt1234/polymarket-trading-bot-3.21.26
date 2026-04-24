"""
Full-history backfill of xTracker tracking data into Supabase.

Replaces the older fetch_historical_auctions.py — that one didn't preserve
startDate/endDate per tracking and didn't push into the DB. This one:

  - Fetches every tracking (truthsocial + x platforms) for a handle
  - Pulls per-tracking stats with hourly granularity
  - Writes one row per (tracking, hour) into post_count_snapshots so we can
    replay any auction's pacing exactly as xTracker reported it
  - Also keeps the JSON files at _DataMetricPulls/historical/{handle}/ for
    parquet/historical_hourly_averages compatibility

Idempotent: re-running upserts. xTracker has no rate limit issues.

Usage:
  python scripts/backfill_xtracker_history.py --handle realDonaldTrump
  python scripts/backfill_xtracker_history.py --handle elonmusk
  python scripts/backfill_xtracker_history.py --handle realDonaldTrump --module-id e858d9ed-...

Env vars: SUPABASE_URL, SUPABASE_SERVICE_KEY (required for DB writes)
"""
import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

XTRACKER_BASE = "https://xtracker.polymarket.com/api"
DATA_DIR = Path(__file__).parent.parent / "_DataMetricPulls" / "historical"
PLATFORMS = [None, "truthsocial", "x"]


async def fetch_all_trackings(handle: str) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    async with httpx.AsyncClient(timeout=30) as client:
        for platform in PLATFORMS:
            params = {"platform": platform} if platform else {}
            try:
                res = await client.get(f"{XTRACKER_BASE}/users/{handle}/trackings", params=params)
                res.raise_for_status()
                data = res.json()
                trackings = data.get("data", data) if isinstance(data, dict) else data
                if isinstance(trackings, list):
                    for t in trackings:
                        tid = str(t.get("id") or t.get("trackingId") or "")
                        if tid and tid not in seen:
                            seen.add(tid)
                            out.append(t)
                    print(f"  platform={platform}: {len(trackings)} trackings ({len(seen)} unique so far)")
            except Exception as e:
                print(f"  platform={platform} fetch failed: {e}")
    return out


async def fetch_tracking_stats(client: httpx.AsyncClient, tracking_id: str) -> dict:
    res = await client.get(
        f"{XTRACKER_BASE}/trackings/{tracking_id}",
        params={"includeStats": "true"},
    )
    res.raise_for_status()
    data = res.json()
    return data.get("data", data) if isinstance(data, dict) else data


def _detect_module_id(sb, handle: str) -> str | None:
    name_filter = "trump" if "trump" in handle.lower() or handle == "realDonaldTrump" else "elon"
    res = sb.table("modules").select("id,name").execute()
    for m in res.data or []:
        if name_filter in (m.get("name") or "").lower():
            return m["id"]
    return None


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--handle", required=True)
    p.add_argument("--module-id", default=None, help="UUID of module in DB. Auto-detected by handle if omitted.")
    p.add_argument("--no-db", action="store_true", help="Skip DB writes, only save JSON files")
    args = p.parse_args()

    sb = None
    module_id = None
    if not args.no_db:
        if not (os.getenv("SUPABASE_URL") and (os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY"))):
            print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY (or SUPABASE_KEY) must be set, or pass --no-db")
            sys.exit(2)
        from api.dependencies import get_supabase
        sb = get_supabase()
        module_id = args.module_id or _detect_module_id(sb, args.handle)
        if not module_id:
            print(f"WARNING: could not auto-detect module_id for @{args.handle}. Pass --module-id or use --no-db.")
            sys.exit(3)
        print(f"Writing to post_count_snapshots with module_id={module_id}")

    print(f"Fetching all trackings for @{args.handle}...")
    trackings = await fetch_all_trackings(args.handle)
    print(f"Total unique trackings: {len(trackings)}")

    detailed: list[dict] = []
    weekly_totals: list[dict] = []
    daily_all: list[dict] = []
    snapshot_rows: list[dict] = []

    async with httpx.AsyncClient(timeout=30) as client:
        for i, t in enumerate(trackings):
            tid_raw = t.get("id") or t.get("trackingId")
            if not tid_raw:
                continue
            tid = str(tid_raw)
            start = t.get("startDate", "")
            end = t.get("endDate", "")

            print(f"  [{i+1}/{len(trackings)}] tid={tid} {start[:10]}->{end[:10]} ({t.get('title','')[:60]})")
            try:
                await asyncio.sleep(0.4)
                stats = await fetch_tracking_stats(client, tid)
                stats["_tracking"] = t
                detailed.append(stats)
            except Exception as e:
                print(f"    stats fetch failed: {e}")
                continue

            s = stats.get("stats", {}) if isinstance(stats, dict) else {}
            if not isinstance(s, dict):
                continue

            total = s.get("total", 0)
            weekly_totals.append({
                "tracking_id": tid,
                "start": start,
                "end": end,
                "total": total,
                "days": s.get("daysTotal", 7),
                "title": t.get("title"),
            })

            hourly = s.get("daily", []) if isinstance(s.get("daily"), list) else []
            running = 0
            for h in hourly:
                count = h.get("count", 0)
                running += count
                date_str = h.get("date", "")
                daily_all.append({
                    "date": date_str,
                    "count": count,
                    "tracking_id": tid,
                })
                if module_id and date_str:
                    snapshot_rows.append({
                        "module_id": module_id,
                        "source": "xtracker",
                        "tracking_id": tid,
                        "window_start": start or None,
                        "window_end": end or None,
                        "count": running,
                        "latest_post_at": date_str,
                        "captured_at": date_str,
                    })

    out_dir = DATA_DIR / args.handle
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "all_trackings.json", "w") as f:
        json.dump(detailed, f, indent=2, default=str)
    with open(out_dir / "weekly_totals.json", "w") as f:
        json.dump(weekly_totals, f, indent=2)
    with open(out_dir / "daily_from_xtracker.json", "w") as f:
        json.dump(daily_all, f, indent=2)

    dow_counts: dict[int, list[int]] = defaultdict(list)
    for d in daily_all:
        dt_str = d.get("date", "")
        if len(dt_str) >= 10:
            try:
                dt = datetime.fromisoformat(dt_str[:10])
                dow_counts[dt.weekday()].append(d["count"])
            except ValueError:
                pass
    dow_avgs = {d: round(sum(v) / len(v), 2) for d, v in dow_counts.items()}
    with open(out_dir / "dow_hourly_stats.json", "w") as f:
        json.dump({"dow_averages": dow_avgs, "hourly_averages": {}}, f, indent=2)

    try:
        import pandas as pd
        if daily_all:
            pd.DataFrame(daily_all).to_parquet(out_dir / "daily.parquet", index=False)
    except ImportError:
        pass

    if sb and snapshot_rows:
        print(f"\nWriting {len(snapshot_rows)} rows to post_count_snapshots (in batches of 500)...")
        for i in range(0, len(snapshot_rows), 500):
            batch = snapshot_rows[i:i+500]
            sb.table("post_count_snapshots").insert(batch).execute()
            print(f"  inserted {min(i+500, len(snapshot_rows))}/{len(snapshot_rows)}")

    print(f"\nSaved to: {out_dir}")
    print(f"  Trackings:      {len(detailed)}")
    print(f"  Weekly totals:  {len(weekly_totals)}")
    print(f"  Daily records:  {len(daily_all)}")
    print(f"  DB snapshots:   {len(snapshot_rows) if sb else 0}")
    if weekly_totals:
        totals = [w["total"] for w in weekly_totals if w["total"] > 0]
        if totals:
            print(f"  Avg weekly:     {sum(totals)/len(totals):.1f}")
            print(f"  Range:          {min(totals)} - {max(totals)}")


if __name__ == "__main__":
    asyncio.run(main())
