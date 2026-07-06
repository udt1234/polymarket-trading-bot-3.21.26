"""Supabase retention (BUILD_SPEC H3). Daily 03:30 UTC. Free tier choked
on Disk IO 2026-05-22; these windows keep the live DB small. Weekly parquet
archiving stays a local-scripts concern (the VPS box has no OneDrive)."""
import logging
from datetime import datetime, timedelta, timezone

from api.dependencies import get_supabase

log = logging.getLogger(__name__)

# table -> (timestamp column, days to keep)
WINDOWS = {
    "price_snapshots": ("created_at", 180),
    "post_count_snapshots": ("created_at", 90),
    "order_book_snapshots": ("created_at", 30),
    "logs": ("created_at", 14),
    "pending_signals": ("created_at", 7),
    "signals": ("created_at", 90),
}


def run_retention_cleanup() -> dict[str, int]:
    sb = get_supabase()
    out: dict[str, int] = {}
    now = datetime.now(timezone.utc)
    for table, (col, days) in WINDOWS.items():
        cutoff = (now - timedelta(days=days)).isoformat()
        try:
            res = sb.table(table).delete().lt(col, cutoff).execute()
            out[table] = len(res.data or [])
        except Exception:
            log.exception("retention delete failed for %s", table)
            out[table] = -1
    log.info("retention cleanup: %s", out)
    return out
