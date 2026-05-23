"""Parquet archive reader for historical Supabase data.

When the bot needs data older than the live retention window, it falls back
to the parquet archive at _DataMetricPulls/historical/supabase_archive/.

Live windows (matches retention.py + migrations/021):
    price_snapshots:       180 days
    post_count_snapshots:    90 days
    order_book_snapshots:    30 days
    logs:                    14 days (system: 30 days)

If `analyze_older_than_days(table)` is True for the date range, callers can
use `read_table_range(...)` to pull from parquet instead of Supabase.

Read pattern:
    from api.modules.shared.parquet_archive import read_table_range
    df = read_table_range("price_snapshots", since=start, until=end,
                          filters={"module_id": module_id, "bracket": bracket})
    rows = df.to_dict("records") if df is not None else []
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

ARCHIVE_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "_DataMetricPulls" / "historical" / "supabase_archive"

# Canonical retention windows. Both api/services/retention.py and any
# analysis code that needs to know "is this data still live in Supabase"
# must import from here. The SQL migration 021_retention_cleanup.sql
# must be kept in sync manually (SQL migrations are immutable).
LIVE_WINDOW_DAYS = {
    "price_snapshots": 180,
    "post_count_snapshots": 90,
    "order_book_snapshots": 30,
    "logs": 14,
    "pending_signals": 7,
}

# Special-cased: logs has split retention by log_type
LOGS_SYSTEM_DAYS = 30
LOGS_OTHER_DAYS = LIVE_WINDOW_DAYS["logs"]


def is_in_archive_range(table: str, query_since: datetime) -> bool:
    """True iff query reaches into the parquet archive (older than live window)."""
    window = LIVE_WINDOW_DAYS.get(table)
    if not window:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(days=window)
    return query_since < cutoff


def _month_files(table: str, since: datetime, until: datetime) -> list[Path]:
    out_dir = ARCHIVE_ROOT / table
    if not out_dir.exists():
        return []
    cur = datetime(since.year, since.month, 1, tzinfo=timezone.utc)
    files = []
    while cur < until:
        path = out_dir / f"{cur.strftime('%Y-%m')}.parquet"
        if path.exists():
            files.append(path)
        if cur.month == 12:
            cur = datetime(cur.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            cur = datetime(cur.year, cur.month + 1, 1, tzinfo=timezone.utc)
    return files


def read_table_range(
    table: str,
    since: datetime,
    until: datetime,
    ts_col: str | None = None,
    filters: dict | None = None,
):
    """Read rows in [since, until) from parquet archive. Returns DataFrame or None.

    `filters` are applied as DataFrame `.query()`-style equality matches.
    Returns None if pandas/pyarrow is unavailable or no archive files match.
    """
    try:
        import pandas as pd
    except ImportError:
        log.warning("pandas unavailable; cannot read parquet archive")
        return None

    files = _month_files(table, since, until)
    if not files:
        return None

    frames = []
    for fp in files:
        try:
            frames.append(pd.read_parquet(fp))
        except Exception as e:
            log.warning(f"parquet_archive: failed to read {fp}: {e}")
    if not frames:
        return None

    df = pd.concat(frames, ignore_index=True)

    if ts_col and ts_col in df.columns:
        df[ts_col] = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
        df = df[(df[ts_col] >= since) & (df[ts_col] < until)]

    if filters:
        for k, v in filters.items():
            if k in df.columns:
                df = df[df[k] == v]

    return df.reset_index(drop=True) if not df.empty else None
