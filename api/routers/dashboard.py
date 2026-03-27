from fastapi import APIRouter
from api.dependencies import get_supabase
from api.config import get_settings
from api.services.wallet import (
    fetch_wallet_summary, fetch_wallet_positions, fetch_wallet_trades,
    fetch_wallet_auctions, fetch_wallet_activity, build_performance_series,
)

router = APIRouter()


def _get_active_wallet() -> str | None:
    sb = get_supabase()
    res = sb.table("settings").select("value").eq("key", "profiles").single().execute()
    if not res.data:
        return None
    profiles_data = res.data.get("value", {})
    active_name = profiles_data.get("active")
    for p in profiles_data.get("profiles", []):
        if p.get("name") == active_name:
            return p.get("wallet_address")
    return None


@router.get("/metrics")
async def get_metrics():
    sb = get_supabase()
    settings = get_settings()

    # Try to get real wallet data first
    wallet = _get_active_wallet()
    if wallet:
        summary = await fetch_wallet_summary(wallet)
        active_mods = sb.table("modules").select("id", count="exact").eq("status", "active").execute().count
        return {
            "portfolio_value": summary["portfolio_value"],
            "total_invested": summary["total_invested"],
            "total_pnl": summary["total_pnl"],
            "win_rate": summary["win_rate"],
            "wins": summary.get("wins", 0),
            "losses": summary.get("losses", 0),
            "active_modules": active_mods,
            "open_positions": summary["open_count"],
            "closed_positions": summary["closed_count"],
            "wallet_address": wallet,
            "source": "live",
        }

    # Fallback to paper trading data
    positions = sb.table("positions").select("*").eq("status", "open").execute()
    all_positions = sb.table("positions").select("realized_pnl,status").execute()
    daily_pnl = sb.table("daily_pnl").select("*").order("date", desc=True).limit(1).execute()

    total_pnl = 0.0
    wins = 0
    total_closed = 0
    for p in all_positions.data:
        rpnl = p.get("realized_pnl", 0) or 0
        if p.get("status") == "closed":
            total_pnl += rpnl
            total_closed += 1
            if rpnl > 0:
                wins += 1
    for p in positions.data:
        total_pnl += p.get("unrealized_pnl", 0) or 0

    portfolio_value = daily_pnl.data[0]["portfolio_value"] if daily_pnl.data else settings.bankroll + total_pnl

    return {
        "portfolio_value": portfolio_value,
        "total_pnl": total_pnl,
        "win_rate": (wins / total_closed * 100) if total_closed > 0 else 0,
        "active_modules": sb.table("modules").select("id", count="exact").eq("status", "active").execute().count,
        "open_positions": len(positions.data),
        "source": "paper",
    }


@router.get("/performance")
async def get_performance(range: str = "7d"):
    wallet = _get_active_wallet()
    if wallet:
        activities = await fetch_wallet_activity(wallet)
        positions = await fetch_wallet_positions(wallet)
        series = build_performance_series(activities, positions)
        limit_map = {"24h": 1, "7d": 7, "30d": 30, "90d": 90, "all": 9999}
        limit = limit_map.get(range, 7)
        if limit < len(series):
            series = series[-limit:]
        return {"data": series, "source": "live"}

    sb = get_supabase()
    limit_map = {"24h": 1, "7d": 7, "30d": 30, "90d": 90, "all": 9999}
    limit = limit_map.get(range, 7)
    rows = sb.table("daily_pnl").select("*").order("date", desc=True).limit(limit).execute()
    return {"data": list(reversed(rows.data)), "source": "paper"}


@router.get("/recent-trades")
async def get_recent_trades(limit: int = 10):
    sb = get_supabase()
    # Try live wallet trades first
    wallet = _get_active_wallet()
    if wallet:
        live_trades = await fetch_wallet_trades(wallet, limit)
        return live_trades

    trades = sb.table("trades").select("*").order("executed_at", desc=True).limit(limit).execute()
    return trades.data


@router.get("/wallet/positions")
async def get_wallet_positions(limit: int = 50):
    wallet = _get_active_wallet()
    if not wallet:
        return []
    return await fetch_wallet_positions(wallet, limit)


@router.get("/wallet/trades")
async def get_wallet_trades(limit: int = 50):
    wallet = _get_active_wallet()
    if not wallet:
        return []
    return await fetch_wallet_trades(wallet, limit)


@router.get("/auctions")
async def get_auctions():
    wallet = _get_active_wallet()
    if not wallet:
        return []
    return await fetch_wallet_auctions(wallet)


@router.get("/recent-signals")
async def get_recent_signals(limit: int = 10):
    sb = get_supabase()
    signals = sb.table("signals").select("*").order("created_at", desc=True).limit(limit).execute()
    return signals.data
