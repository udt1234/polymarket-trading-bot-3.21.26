import asyncio
import logging
from datetime import datetime, timezone, date
from apscheduler.schedulers.background import BackgroundScheduler
from api.dependencies import get_supabase

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def take_price_snapshot():
    try:
        _take_price_snapshot_sync()
    except Exception as e:
        log.error(f"Price snapshot failed: {e}")


def _take_price_snapshot_sync():
    import json as _json
    import httpx as _httpx
    from api.modules.truth_social.data import normalize_bracket, extract_slug_from_tracking

    GAMMA = "https://gamma-api.polymarket.com"
    XTRACKER = "https://xtracker.polymarket.com/api"

    sb = get_supabase()
    modules = sb.table("modules").select("id,name,market_slug,status").in_("status", ["active", "paper", "scaffold"]).execute()
    if not modules.data:
        return

    now = datetime.now(timezone.utc)
    snapshot_hour = now.replace(minute=0, second=0, microsecond=0)
    dow = now.weekday()
    hour_of_day = now.hour

    client = _httpx.Client(timeout=15)

    for mod in modules.data:
        module_id = mod["id"]
        handle = "realDonaldTrump" if "truth" in mod["name"].lower() or "trump" in mod["name"].lower() else "elonmusk"
        slug = None
        active_tracking = None

        try:
            platform = "x" if handle == "elonmusk" else "truthsocial"
            res = client.get(f"{XTRACKER}/users/{handle}/trackings", params={"platform": platform})
            data = res.json()
            trackings = data.get("data", data) if isinstance(data, dict) else data
            if isinstance(trackings, dict):
                trackings = trackings.get("trackings", [])
            active = [t for t in trackings if t.get("isActive")]
            if active:
                active_tracking = active[0]
                slug = extract_slug_from_tracking(active_tracking)
        except Exception:
            pass

        if not slug:
            slug = mod.get("market_slug")

        if not slug:
            continue

        try:
            res = client.get(f"{GAMMA}/events", params={"slug": slug})
            events = res.json()
            if not isinstance(events, list) or not events:
                continue
            prices = {}
            for m in events[0].get("markets", []):
                raw = m.get("groupItemTitle", m.get("question", ""))
                bracket = normalize_bracket(raw)
                op = m.get("outcomePrices", "[]")
                if isinstance(op, str):
                    op = _json.loads(op)
                if op:
                    p = float(op[0])
                    if 0 < p < 1:
                        prices[bracket] = p
        except Exception as e:
            log.warning(f"Price fetch failed for {mod['name']}: {e}")
            continue

        if not prices:
            continue

        elapsed_days = None
        tracking_id = None
        if active_tracking:
            tracking_id = str(active_tracking.get("id") or active_tracking.get("trackingId") or "")
            start = active_tracking.get("startDate", "")[:10]
            if start:
                try:
                    start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    elapsed_days = round((now - start_dt).total_seconds() / 86400, 2)
                except Exception:
                    pass

        rows = []
        for bracket, price in prices.items():
            rows.append({
                "module_id": module_id,
                "bracket": bracket,
                "price": round(price, 6),
                "snapshot_hour": snapshot_hour.isoformat(),
                "dow": dow,
                "hour_of_day": hour_of_day,
                "elapsed_days": elapsed_days,
                "tracking_id": tracking_id,
            })

        if rows:
            sb.table("price_snapshots").upsert(
                rows, on_conflict="module_id,bracket,snapshot_hour"
            ).execute()
            log.info(f"Price snapshot: {mod['name']} -- {len(rows)} brackets at {snapshot_hour}")

    client.close()


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
    _scheduler.add_job(take_price_snapshot, "interval", minutes=60, max_instances=1)
    _scheduler.start()
    take_daily_snapshot()
    take_price_snapshot()
    log.info("Snapshot scheduler started (daily + hourly price)")


def stop_snapshot_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
