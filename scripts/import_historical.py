"""
Import historical post count data into the bot's historical pipeline.

Usage:
  python scripts/import_historical.py --file data/trump_history.csv --handle realDonaldTrump
  python scripts/import_historical.py --file data/elon_history.json --handle elonmusk

Supported formats:
  CSV: date,count (daily totals) or date,hour,count (hourly)
  JSON: [{"date": "2025-01-01", "count": 42}, ...] or [{"date": "...", "hour": 14, "count": 5}, ...]

Data is saved to data/historical/{handle}/ as parquet for fast loading by pacing models.
"""
import argparse
import json
import csv
import os
from pathlib import Path
from datetime import datetime
from collections import defaultdict

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

DATA_DIR = Path(__file__).parent.parent / "_DataMetricPulls" / "historical"


def load_csv(filepath: str) -> list[dict]:
    rows = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entry = {"date": row.get("date", ""), "count": int(row.get("count", 0))}
            if "hour" in row:
                entry["hour"] = int(row["hour"])
            rows.append(entry)
    return rows


def load_json(filepath: str) -> list[dict]:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return []


def compute_weekly_totals(daily_data: list[dict]) -> list[dict]:
    by_week = defaultdict(int)
    for entry in daily_data:
        dt = datetime.fromisoformat(entry["date"][:10])
        week_start = dt - __import__("datetime").timedelta(days=dt.weekday())
        week_key = week_start.strftime("%Y-%m-%d")
        by_week[week_key] += entry["count"]

    return [{"week_start": k, "total": v} for k, v in sorted(by_week.items())]


def compute_dow_hourly_stats(data: list[dict]) -> dict:
    dow_totals = defaultdict(list)
    hourly_totals = defaultdict(list)

    for entry in data:
        dt = datetime.fromisoformat(entry["date"][:10])
        dow_totals[dt.weekday()].append(entry["count"])
        if "hour" in entry:
            hourly_totals[entry["hour"]].append(entry["count"])

    dow_avgs = {d: sum(v) / len(v) for d, v in dow_totals.items()}
    hourly_avgs = {h: sum(v) / len(v) for h, v in hourly_totals.items()}

    return {"dow_averages": dow_avgs, "hourly_averages": hourly_avgs}


def save_data(handle: str, daily_data: list[dict], weekly_totals: list[dict], stats: dict):
    out_dir = DATA_DIR / handle
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "daily.json", "w") as f:
        json.dump(daily_data, f, indent=2)

    with open(out_dir / "weekly_totals.json", "w") as f:
        json.dump(weekly_totals, f, indent=2)

    with open(out_dir / "dow_hourly_stats.json", "w") as f:
        json.dump(stats, f, indent=2)

    if HAS_PANDAS:
        df = pd.DataFrame(daily_data)
        df.to_parquet(out_dir / "daily.parquet", index=False)
        print(f"  Saved parquet: {out_dir / 'daily.parquet'}")

    print(f"  Saved to: {out_dir}")
    print(f"  Daily records: {len(daily_data)}")
    print(f"  Weekly totals: {len(weekly_totals)}")
    if weekly_totals:
        totals = [w["total"] for w in weekly_totals]
        print(f"  Avg weekly: {sum(totals)/len(totals):.1f}, Min: {min(totals)}, Max: {max(totals)}")


def main():
    parser = argparse.ArgumentParser(description="Import historical post data")
    parser.add_argument("--file", required=True, help="Path to CSV or JSON file")
    parser.add_argument("--handle", required=True, help="Handle (realDonaldTrump or elonmusk)")
    args = parser.parse_args()

    filepath = args.file
    if filepath.endswith(".csv"):
        data = load_csv(filepath)
    elif filepath.endswith(".json"):
        data = load_json(filepath)
    else:
        print(f"Unsupported format: {filepath}")
        return

    if not data:
        print("No data found in file")
        return

    print(f"Loaded {len(data)} records from {filepath}")

    weekly = compute_weekly_totals(data)
    stats = compute_dow_hourly_stats(data)
    save_data(args.handle, data, weekly, stats)
    print("Done.")


if __name__ == "__main__":
    main()
