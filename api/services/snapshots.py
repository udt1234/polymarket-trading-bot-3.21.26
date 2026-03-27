import logging
from datetime import datetime, timezone, date
from apscheduler.schedulers.background import BackgroundScheduler
from api.dependencies import get_supabase

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def take_daily_snapshot():
    sb = get_supabase()
    today = date.today().isoformat()

    existing = sb.table("daily_pnl").select("id").eq("date", today).execute()
    if existing.data:
        return

    positions = sb.table("positions").select("*").execute()
    realized = sum(p.get("realized_pnl", 0) for p in positions.data)
    unrealized = sum(p.get("unrealized_pnl", 0) for p in positions.data)
    total_pnl = realized + unrealized

    yesterday = sb.table("daily_pnl").select("portfolio_value").order("date", desc=True).limit(1).execute()
    prev_value = yesterday.data[0]["portfolio_value"] if yesterday.data else 1000.0
    portfolio_value = prev_value + total_pnl
    daily_return = (portfolio_value - prev_value) / prev_value if prev_value > 0 else 0

    sb.table("daily_pnl").insert({
        "date": today,
        "portfolio_value": portfolio_value,
        "daily_return": daily_return,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "total_pnl": total_pnl,
    }).execute()

    log.info(f"Daily snapshot: date={today}, value={portfolio_value:.2f}, return={daily_return:.4f}")


def start_snapshot_scheduler():
    global _scheduler
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(take_daily_snapshot, "cron", hour=23, minute=55, timezone="UTC")
    _scheduler.add_job(take_daily_snapshot, "interval", minutes=60, max_instances=1)
    _scheduler.start()
    take_daily_snapshot()
    log.info("Snapshot scheduler started")


def stop_snapshot_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
