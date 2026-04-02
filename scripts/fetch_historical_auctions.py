"""
Fetch all historical xTracker auction data for a handle.
Pulls every completed tracking period with stats, saves to data/historical/{handle}/.

Usage:
  python scripts/fetch_historical_auctions.py --handle realDonaldTrump
  python scripts/fetch_historical_auctions.py --handle elonmusk
"""
import argparse
import asyncio
import json
import httpx
from pathlib import Path
from datetime import datetime
from collections import defaultdict

XTRACKER_BASE = "https://xtracker.polymarket.com/api"
DATA_DIR = Path(__file__).parent.parent / "_DataMetricPulls" / "historical"


async def fetch_all_trackings(handle: str, platform: str = None) -> list:
    async with httpx.AsyncClient(timeout=30) as client:
        params = {}
        if platform:
            params["platform"] = platform
        res = await client.get(f"{XTRACKER_BASE}/users/{handle}/trackings", params=params)
        res.raise_for_status()
        data = res.json()
        return data.get("data", data) if isinstance(data, dict) else data


async def fetch_tracking_stats(tracking_id: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.get(
            f"{XTRACKER_BASE}/trackings/{tracking_id}",
            params={"includeStats": "true"},
        )
        res.raise_for_status()
        data = res.json()
        return data.get("data", data) if isinstance(data, dict) else data


async def main(handle: str):
    print(f"Fetching all trackings for {handle}...")

    # Try both platforms
    all_trackings = []
    for platform in [None, "truthsocial", "x"]:
        try:
            trackings = await fetch_all_trackings(handle, platform)
            if trackings:
                all_trackings.extend(trackings)
                print(f"  Found {len(trackings)} trackings (platform={platform})")
        except Exception as e:
            print(f"  Error fetching platform={platform}: {e}")

    # Deduplicate by tracking ID
    seen_ids = set()
    unique = []
    for t in all_trackings:
        tid = str(t.get("id") or t.get("trackingId", ""))
        if tid and tid not in seen_ids:
            seen_ids.add(tid)
            unique.append(t)

    print(f"Total unique trackings: {len(unique)}")

    # Fetch detailed stats for each
    detailed = []
    weekly_totals = []
    daily_all = []

    for i, t in enumerate(unique):
        tid = t.get("id") or t.get("trackingId")
        if not tid:
            continue

        print(f"  [{i+1}/{len(unique)}] Fetching stats for tracking {tid}...")
        try:
            await asyncio.sleep(0.5)
            stats = await fetch_tracking_stats(str(tid))
            stats["_tracking"] = t
            detailed.append(stats)

            # Extract weekly total
            s = stats.get("stats", {})
            if isinstance(s, dict):
                total = s.get("total", 0)
                start = t.get("startDate", "")
                end = t.get("endDate", "")
                weekly_totals.append({
                    "tracking_id": str(tid),
                    "start": start,
                    "end": end,
                    "total": total,
                    "days": s.get("daysTotal", 7),
                })

                # Extract daily data
                daily = s.get("daily", [])
                if isinstance(daily, list):
                    for d in daily:
                        daily_all.append({
                            "date": d.get("date", ""),
                            "count": d.get("count", 0),
                            "tracking_id": str(tid),
                        })

        except Exception as e:
            print(f"    Error: {e}")

    # Save everything
    out_dir = DATA_DIR / handle
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "all_trackings.json", "w") as f:
        json.dump(detailed, f, indent=2, default=str)

    with open(out_dir / "weekly_totals.json", "w") as f:
        json.dump(weekly_totals, f, indent=2)

    with open(out_dir / "daily_from_xtracker.json", "w") as f:
        json.dump(daily_all, f, indent=2)

    # Compute DOW + hourly stats
    dow_counts = defaultdict(list)
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

    # Try parquet
    try:
        import pandas as pd
        if daily_all:
            df = pd.DataFrame(daily_all)
            df.to_parquet(out_dir / "daily.parquet", index=False)
            print(f"  Saved parquet: {out_dir / 'daily.parquet'}")
    except ImportError:
        pass

    print(f"\nSaved to: {out_dir}")
    print(f"  Trackings: {len(detailed)}")
    print(f"  Weekly totals: {len(weekly_totals)}")
    print(f"  Daily records: {len(daily_all)}")
    if weekly_totals:
        totals = [w["total"] for w in weekly_totals if w["total"] > 0]
        if totals:
            print(f"  Avg weekly count: {sum(totals)/len(totals):.1f}")
            print(f"  Range: {min(totals)} - {max(totals)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--handle", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.handle))
