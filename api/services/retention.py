"""Data retention + parquet archival for high-traffic tables.

Two scheduled jobs run inside the FastAPI process:

1. Daily cleanup (03:30 UTC) — DELETE rows older than the retention window
   per table. Keeps Supabase free tier under Disk IO budget.

2. Weekly archive (Sunday 03:00 UTC) — dump the last 7 days of rows to
   parquet under _DataMetricPulls/historical/supabase_archive/<table>/<YYYY-MM>.parquet
   so historical analysis still works.

Retention windows match supabase/migrations/021_retention_cleanup.sql.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

from api.dependencies import get_supabase
from api.modules.shared.parquet_archive import (
    ARCHIVE_ROOT,
    LIVE_WINDOW_DAYS,
    LOGS_OTHER_DAYS,
    LOGS_SYSTEM_DAYS,
)

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

# (table, ts_column) — retention days come from parquet_archive.LIVE_WINDOW_DAYS
RETENTION = [
    ("price_snapshots", "snapshot_hour"),
    ("post_count_snapshots", "captured_at"),
    ("order_book_snapshots", "snapshot_at"),
    ("pending_signals", "created_at"),
]

# Tables we archive to parquet weekly
ARCHIVE_TABLES = {
    "price_snapshots": "snapshot_hour",
    "logs": "created_at",
    "post_count_snapshots": "captured_at",
    "order_book_snapshots": "snapshot_at",
}


def _run_daily_cleanup() -> None:
    """Daily DELETE per table. Idempotent + safe to retry."""
    sb = get_supabase()
    deleted = {}
    now = datetime.now(timezone.utc)

    for table, ts_col in RETENTION:
        days = LIVE_WINDOW_DAYS[table]
        cutoff = (now - timedelta(days=days)).isoformat()
        try:
            q = sb.table(table).delete().lt(ts_col, cutoff)
            # pending_signals: never delete a row that's still actively
            # waiting in the queue, even if it's older than the window.
            # See QA finding 4 (2026-05-22) — comment-vs-code contract bug.
            if table == "pending_signals":
                q = q.neq("status", "waiting")
            res = q.execute()
            deleted[table] = len(res.data or [])
        except Exception as e:
            log.warning(f"retention: {table} delete failed: {e}")
            deleted[table] = -1

    # logs — split policy
    try:
        cutoff_sys = (now - timedelta(days=LOGS_SYSTEM_DAYS)).isoformat()
        cutoff_other = (now - timedelta(days=LOGS_OTHER_DAYS)).isoformat()
        r1 = sb.table("logs").delete().eq("log_type", "system").lt("created_at", cutoff_sys).execute()
        r2 = sb.table("logs").delete().neq("log_type", "system").lt("created_at", cutoff_other).execute()
        deleted["logs"] = len(r1.data or []) + len(r2.data or [])
    except Exception as e:
        log.warning(f"retention: logs delete failed: {e}")
        deleted["logs"] = -1

    total = sum(v for v in deleted.values() if v > 0)
    log.info(f"retention: daily cleanup deleted {total} rows total: {deleted}")


def _archive_table_to_parquet(sb, table: str, ts_col: str, since: datetime, until: datetime) -> int:
    """Pull rows in [since, until) and write to monthly parquet file.

    Idempotent — overwrites the month's file each run.
    """
    import pandas as pd

    out_dir = ARCHIVE_ROOT / table
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    start = 0
    page = 1000
    while True:
        q = (
            sb.table(table)
            .select("*")
            .gte(ts_col, since.isoformat())
            .lt(ts_col, until.isoformat())
            .order(ts_col)
            .range(start, start + page - 1)
        )
        res = q.execute()
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < page:
            break
        start += page

    if not rows:
        return 0

    df = pd.DataFrame(rows)
    out_file = out_dir / f"{since.strftime('%Y-%m')}.parquet"
    if out_file.exists():
        try:
            existing = pd.read_parquet(out_file)
            df = pd.concat([existing, df]).drop_duplicates(subset=["id"] if "id" in df.columns else None).reset_index(drop=True)
        except Exception as e:
            log.warning(f"retention: failed to merge existing {out_file}: {e} — overwriting")
    df.to_parquet(out_file, compression="zstd", index=False)
    return len(rows)


def _run_weekly_archive() -> None:
    """Dump last 7 days to parquet (per-table, per-month files)."""
    sb = get_supabase()
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=7)
    total = 0
    for table, ts_col in ARCHIVE_TABLES.items():
        try:
            n = _archive_table_to_parquet(sb, table, ts_col, since, now)
            total += n
            log.info(f"retention: archived {n} rows from {table} -> parquet")
        except Exception as e:
            log.warning(f"retention: archive {table} failed: {e}")
    log.info(f"retention: weekly archive done — {total} rows archived to {ARCHIVE_ROOT}")


def start_retention_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()
    # Daily cleanup at 03:30 UTC (off-peak — most modules idle, US night)
    _scheduler.add_job(_run_daily_cleanup, "cron", hour=3, minute=30, timezone="UTC", max_instances=1)
    # Weekly archive Sundays 03:00 UTC, runs BEFORE the daily cleanup so the
    # week's data is captured before it gets near the deletion window
    _scheduler.add_job(_run_weekly_archive, "cron", day_of_week="sun", hour=3, minute=0, timezone="UTC", max_instances=1)
    _scheduler.start()
    log.info("retention scheduler started (daily cleanup 03:30 UTC, weekly archive Sun 03:00 UTC)")


def stop_retention_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
