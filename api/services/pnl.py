"""Daily P&L snapshot.

The tracker dashboard's account panel and equity curve read `daily_pnl`
(`PolyPulse_Web/app/lib/supa.ts`). Nothing in the rebuilt bot ever wrote that
table: its only writer was the rogue JaxBot deploy, which added the FULL
cumulative realized P&L to portfolio_value every single day and walked it to
-$21,652 on a $10k bankroll. Killing that deploy on 2026-09-07 left the table
orphaned, so the bot owns it now.

Open positions are marked to the BID we could actually hit, never the mid
(lessons.md 2026-07-26). A position with no bid is EXCLUDED, never defaulted.
"""
import logging
from datetime import date as _date
from datetime import datetime, timedelta, timezone

from api.config import get_settings
from api.dependencies import get_supabase

log = logging.getLogger(__name__)


def _unrealized_at_touch(sb) -> tuple[float, int]:
    """(unrealized $, positions that could not be marked)."""
    from api.services.engine import Engine
    rows = (sb.table("positions").select("token_id,size,avg_price")
            .eq("status", "open").execute().data) or []
    total, unmarkable = 0.0, 0
    for r in rows:
        top = Engine._clob_top(r.get("token_id") or "")
        bid = (top or {}).get("best_bid")
        if bid is None:
            unmarkable += 1
            continue
        total += (float(bid) - float(r.get("avg_price") or 0)) * float(r.get("size") or 0)
    return total, unmarkable


def snapshot(day: _date | None = None) -> dict:
    """Upsert one honest row for `day`. Idempotent - safe to run hourly."""
    sb = get_supabase()
    today = datetime.now(timezone.utc).date()
    day = day or today
    iso = day.isoformat()

    closed = (sb.table("positions").select("realized_pnl,closed_at")
              .eq("status", "closed").execute().data) or []
    realized_to_date = sum(float(p.get("realized_pnl") or 0) for p in closed
                           if (p.get("closed_at") or "")[:10] <= iso)
    realized_today = sum(float(p.get("realized_pnl") or 0) for p in closed
                         if (p.get("closed_at") or "")[:10] == iso)

    # Only the current day can be marked; historical marks are not recoverable,
    # so backfilled rows are realized-only rather than invented.
    unreal, unmarkable = _unrealized_at_touch(sb) if day == today else (0.0, 0)

    bankroll = get_settings().bankroll
    row = {"date": iso,
           "portfolio_value": round(bankroll + realized_to_date + unreal, 4),
           "realized_pnl": round(realized_to_date, 4),
           "unrealized_pnl": round(unreal, 4),
           "total_pnl": round(realized_to_date + unreal, 4),
           "daily_return": round(realized_today / bankroll, 6) if bankroll else 0}
    sb.table("daily_pnl").upsert(row, on_conflict="date").execute()
    log.info("daily_pnl %s portfolio=%.2f realized=%.2f unrealized=%.2f unmarkable=%d",
             iso, row["portfolio_value"], row["realized_pnl"],
             row["unrealized_pnl"], unmarkable)
    return row


def rebuild_history() -> int:
    """Recompute every day from the first close to today, replacing whatever the
    rogue deploy left behind. Returns the number of days written."""
    sb = get_supabase()
    first = (sb.table("positions").select("closed_at").eq("status", "closed")
             .order("closed_at").limit(1).execute().data) or []
    if not first:
        return 0
    day = datetime.fromisoformat(first[0]["closed_at"].replace("Z", "+00:00")).date()
    today = datetime.now(timezone.utc).date()
    n = 0
    while day <= today:
        snapshot(day)
        n += 1
        day += timedelta(days=1)
    return n
