"""Archive high-traffic Supabase tables to local parquet.

Usage:
    python scripts/archive_supabase_to_parquet.py            # archive all
    python scripts/archive_supabase_to_parquet.py --table logs --since 2026-04-01

Tables archived (the four Disk-IO offenders identified 2026-05-22):
    - price_snapshots
    - logs
    - post_count_snapshots
    - order_book_snapshots

Output: _DataMetricPulls/historical/supabase_archive/<table>/<YYYY-MM>.parquet
    One file per (table, month). Idempotent — overwrites the month file each run,
    so monthly archive jobs always produce a clean snapshot of that month.

Reads env vars from project .env:
    SUPABASE_URL
    SUPABASE_SERVICE_KEY
"""
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client

ARCHIVE_ROOT = Path(__file__).resolve().parent.parent / "_DataMetricPulls" / "historical" / "supabase_archive"

TABLES = {
    "price_snapshots": "snapshot_hour",
    "logs": "created_at",
    "post_count_snapshots": "captured_at",
    "order_book_snapshots": "snapshot_at",
}

PAGE = 1000


def fetch_paginated(sb, table: str, since_iso: str | None, until_iso: str | None, ts_col: str):
    rows = []
    start = 0
    while True:
        q = sb.table(table).select("*").order(ts_col).range(start, start + PAGE - 1)
        if since_iso:
            q = q.gte(ts_col, since_iso)
        if until_iso:
            q = q.lt(ts_col, until_iso)
        res = q.execute()
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < PAGE:
            break
        start += PAGE
        if start % 10000 == 0:
            print(f"    fetched {start} rows...", flush=True)
    return rows


def month_iter(start: datetime, end: datetime):
    cur = datetime(start.year, start.month, 1, tzinfo=timezone.utc)
    while cur < end:
        if cur.month == 12:
            nxt = datetime(cur.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            nxt = datetime(cur.year, cur.month + 1, 1, tzinfo=timezone.utc)
        yield cur, nxt
        cur = nxt


def archive_table(sb, table: str, ts_col: str, since: datetime, until: datetime):
    out_dir = ARCHIVE_ROOT / table
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[{table}] archiving {since.date()} to {until.date()} (ts_col={ts_col})")
    total = 0
    for m_start, m_end in month_iter(since, until):
        rows = fetch_paginated(sb, table, m_start.isoformat(), m_end.isoformat(), ts_col)
        if not rows:
            continue
        df = pd.DataFrame(rows)
        out_file = out_dir / f"{m_start.strftime('%Y-%m')}.parquet"
        df.to_parquet(out_file, compression="zstd", index=False)
        print(f"    {m_start.strftime('%Y-%m')}: {len(rows):,} rows -> {out_file.name} ({out_file.stat().st_size / 1024:.1f} KB)")
        total += len(rows)
    print(f"[{table}] DONE — {total:,} rows total")
    return total


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--table", choices=list(TABLES.keys()), help="archive one table only (default: all)")
    p.add_argument("--since", help="ISO date (YYYY-MM-DD), default: earliest row")
    p.add_argument("--until", help="ISO date (YYYY-MM-DD), default: now")
    args = p.parse_args()

    load_dotenv()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        sys.exit("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
    sb = create_client(url, key)

    until = datetime.fromisoformat(args.until).replace(tzinfo=timezone.utc) if args.until else datetime.now(timezone.utc)
    if args.since:
        since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
    else:
        since = datetime(2025, 9, 1, tzinfo=timezone.utc)

    tables = [args.table] if args.table else list(TABLES.keys())
    grand_total = 0
    for t in tables:
        grand_total += archive_table(sb, t, TABLES[t], since, until)
    print(f"\nGrand total: {grand_total:,} rows archived to {ARCHIVE_ROOT}")


if __name__ == "__main__":
    main()
