"""
Fetch the CNN Truth Social archive and convert to hourly historical data
for the Trump module's pacing models.

Usage:
  python scripts/import_cnn_archive.py

Output: data/historical/realDonaldTrump/
  - hourly.json         (hour-level post counts)
  - daily.json          (daily totals)
  - weekly_totals.json  (weekly aggregates)
  - dow_hourly_stats.json (DOW + hourly averages for pacing models)
  - hourly.parquet      (if pandas installed)
"""
import asyncio
import json
import httpx
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

CNN_ARCHIVE_URL = "https://ix.cnn.io/data/truth-social/truth_archive.json"
CNN_ARCHIVE_PARQUET = "https://ix.cnn.io/data/truth-social/truth_archive.parquet"
CNN_ARCHIVE_CSV = "https://ix.cnn.io/data/truth-social/truth_archive.csv"
DATA_DIR = Path(__file__).parent.parent / "_DataMetricPulls" / "historical" / "realDonaldTrump"


async def fetch_archive() -> list[dict]:
    # Try Parquet first (much faster for large archives, ~10x smaller than JSON)
    try:
        import pandas as pd
        import io
        async with httpx.AsyncClient(timeout=120) as client:
            res = await client.get(CNN_ARCHIVE_PARQUET, headers={"User-Agent": "Mozilla/5.0"})
            if res.status_code == 200:
                df = pd.read_parquet(io.BytesIO(res.content))
                print(f"  Loaded Parquet: {len(df)} rows, columns: {list(df.columns)}")
                return df.to_dict("records")
    except Exception as e:
        print(f"  Parquet fetch failed ({e}), falling back to JSON...")

    # Fall back to JSON
    async with httpx.AsyncClient(timeout=120) as client:
        res = await client.get(CNN_ARCHIVE_URL, headers={"User-Agent": "Mozilla/5.0"})
        res.raise_for_status()
        return res.json()


def parse_posts(posts: list[dict]) -> list[dict]:
    hourly = []
    for post in posts:
        created = post.get("created_at", post.get("date", post.get("timestamp", "")))
        if not created:
            continue
        try:
            if isinstance(created, (int, float)):
                dt = datetime.fromtimestamp(created, tz=timezone.utc)
            else:
                dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        except (ValueError, TypeError, OSError):
            continue

        hourly.append({
            "datetime": dt.isoformat(),
            "date": dt.strftime("%Y-%m-%d"),
            "hour": dt.hour,
            "dow": dt.weekday(),
            "post_id": post.get("id", ""),
        })

    hourly.sort(key=lambda x: x["datetime"])
    return hourly


def aggregate_hourly(parsed: list[dict]) -> list[dict]:
    counts = defaultdict(int)
    for p in parsed:
        key = f"{p['date']}T{p['hour']:02d}"
        counts[key] += 1

    result = []
    for key in sorted(counts.keys()):
        date, hour = key.split("T")
        dt = datetime.fromisoformat(f"{date}T{hour}:00:00+00:00")
        result.append({
            "date": date,
            "hour": int(hour),
            "dow": dt.weekday(),
            "count": counts[key],
        })
    return result


def aggregate_daily(hourly: list[dict]) -> list[dict]:
    by_date = defaultdict(int)
    for h in hourly:
        by_date[h["date"]] += h["count"]
    return [{"date": d, "count": c} for d, c in sorted(by_date.items())]


def aggregate_weekly(daily: list[dict]) -> list[dict]:
    from datetime import timedelta
    by_week = defaultdict(int)
    for d in daily:
        dt = datetime.fromisoformat(d["date"])
        week_start = dt - timedelta(days=dt.weekday())
        by_week[week_start.strftime("%Y-%m-%d")] += d["count"]
    return [{"week_start": w, "total": t} for w, t in sorted(by_week.items())]


def compute_stats(hourly: list[dict]) -> dict:
    dow_counts = defaultdict(list)
    hour_counts = defaultdict(list)

    # Group by DOW and hour
    by_date_dow = defaultdict(lambda: defaultdict(int))
    by_date_hour = defaultdict(lambda: defaultdict(int))

    for h in hourly:
        by_date_dow[h["date"]][h["dow"]] = by_date_dow[h["date"]].get(h["dow"], 0) + h["count"]
        by_date_hour[h["date"]][h["hour"]] = by_date_hour[h["date"]].get(h["hour"], 0) + h["count"]

    # Daily totals by DOW
    daily_by_dow = defaultdict(list)
    for date_data in by_date_dow.values():
        for dow, count in date_data.items():
            daily_by_dow[dow].append(count)

    # Hourly averages
    hourly_by_hour = defaultdict(list)
    for h in hourly:
        hourly_by_hour[h["hour"]].append(h["count"])

    dow_averages = {str(d): round(sum(v) / len(v), 2) for d, v in daily_by_dow.items()}
    hourly_averages = {str(h): round(sum(v) / len(v), 2) for h, v in hourly_by_hour.items()}

    return {
        "dow_averages": dow_averages,
        "hourly_averages": hourly_averages,
        "total_posts": sum(h["count"] for h in hourly),
        "total_days": len(set(h["date"] for h in hourly)),
        "date_range": {
            "start": hourly[0]["date"] if hourly else "",
            "end": hourly[-1]["date"] if hourly else "",
        },
    }


async def main():
    print("Fetching CNN Truth Social archive...")
    posts = await fetch_archive()
    print(f"  Raw posts: {len(posts)}")

    parsed = parse_posts(posts)
    print(f"  Parsed with timestamps: {len(parsed)}")

    if not parsed:
        print("No parseable posts found. Check the JSON structure.")
        return

    hourly = aggregate_hourly(parsed)
    daily = aggregate_daily(hourly)
    weekly = aggregate_weekly(daily)
    stats = compute_stats(hourly)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with open(DATA_DIR / "hourly.json", "w") as f:
        json.dump(hourly, f, indent=2)

    with open(DATA_DIR / "daily.json", "w") as f:
        json.dump(daily, f, indent=2)

    with open(DATA_DIR / "weekly_totals.json", "w") as f:
        json.dump(weekly, f, indent=2)

    with open(DATA_DIR / "dow_hourly_stats.json", "w") as f:
        json.dump(stats, f, indent=2)

    try:
        import pandas as pd
        df = pd.DataFrame(hourly)
        df.to_parquet(DATA_DIR / "hourly.parquet", index=False)
        print(f"  Saved parquet: {DATA_DIR / 'hourly.parquet'}")
    except ImportError:
        pass

    print(f"\nSaved to: {DATA_DIR}")
    print(f"  Hourly records: {len(hourly)}")
    print(f"  Daily records: {len(daily)}")
    print(f"  Weekly records: {len(weekly)}")
    print(f"  Date range: {stats['date_range']['start']} to {stats['date_range']['end']}")
    print(f"  Total posts: {stats['total_posts']}")
    print(f"  DOW averages: {stats['dow_averages']}")
    print(f"  Peak hour: {max(stats['hourly_averages'], key=lambda k: stats['hourly_averages'][k])}")


if __name__ == "__main__":
    asyncio.run(main())
