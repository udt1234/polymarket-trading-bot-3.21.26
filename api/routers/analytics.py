import math
import random
from datetime import datetime, timedelta
from fastapi import APIRouter, Query
from api.dependencies import get_supabase
from api.modules.truth_social.regime import detect_regime
from api.services.walk_forward import run_walk_forward_check

router = APIRouter()


@router.get("/summary")
async def get_analytics_summary():
    sb = get_supabase()
    pnl_rows = sb.table("daily_pnl").select("*").order("date").execute()

    if not pnl_rows.data:
        return {"sharpe": 0, "sortino": 0, "max_drawdown": 0, "calmar": 0, "profit_factor": 0, "brier_score": None}

    returns = [r.get("daily_return", 0) for r in pnl_rows.data]
    mean_ret = sum(returns) / len(returns) if returns else 0
    std_ret = math.sqrt(sum((r - mean_ret) ** 2 for r in returns) / max(len(returns) - 1, 1))
    downside = [r for r in returns if r < 0]
    downside_std = math.sqrt(sum(r ** 2 for r in downside) / max(len(downside) - 1, 1)) if downside else 0.001

    sharpe = (mean_ret / std_ret * math.sqrt(252)) if std_ret > 0 else 0
    sortino = (mean_ret / downside_std * math.sqrt(252)) if downside_std > 0 else 0

    cumulative = []
    running = 0
    peak = 0
    max_dd = 0
    for r in returns:
        running += r
        cumulative.append(running)
        peak = max(peak, running)
        dd = peak - running
        max_dd = max(max_dd, dd)

    annual_return = mean_ret * 252
    calmar = (annual_return / max_dd) if max_dd > 0 else 0

    gross_profit = sum(r for r in returns if r > 0)
    gross_loss = abs(sum(r for r in returns if r < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    return {
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "max_drawdown": round(max_dd, 4),
        "calmar": round(calmar, 3),
        "profit_factor": round(profit_factor, 3),
        "total_days": len(returns),
        "annual_return": round(annual_return, 4),
    }


@router.get("/calibration")
async def get_calibration():
    sb = get_supabase()
    res = sb.table("calibration_log").select("*").order("resolved_at", desc=True).limit(100).execute()
    return res.data


@router.get("/roi")
async def get_roi():
    sb = get_supabase()
    rows = sb.table("daily_pnl").select("date,daily_return,portfolio_value").order("date").execute()

    if not rows.data:
        return {"daily": 0, "weekly": 0, "monthly": 0, "all_time": 0}

    returns = [r.get("daily_return", 0) for r in rows.data]
    all_time = sum(returns)

    daily = returns[-1] if returns else 0
    weekly = sum(returns[-7:]) if len(returns) >= 7 else sum(returns)
    monthly = sum(returns[-30:]) if len(returns) >= 30 else sum(returns)

    first_val = rows.data[0].get("portfolio_value", 1)
    last_val = rows.data[-1].get("portfolio_value", 1)
    all_time_pct = ((last_val - first_val) / first_val) if first_val else 0

    return {
        "daily": round(daily, 6),
        "weekly": round(weekly, 6),
        "monthly": round(monthly, 6),
        "all_time": round(all_time, 6),
        "all_time_pct": round(all_time_pct, 4),
        "total_days": len(returns),
    }


@router.get("/drawdown")
async def get_drawdown():
    sb = get_supabase()
    rows = sb.table("daily_pnl").select("date,portfolio_value,daily_return").order("date").execute()

    if not rows.data:
        return {"series": [], "max_drawdown": 0, "max_drawdown_duration": 0, "current_drawdown": 0}

    series = []
    peak = 0
    max_dd = 0
    max_dd_duration = 0
    current_dd_start = None
    trough_date = None
    peak_date = None

    for row in rows.data:
        val = row.get("portfolio_value", 0)
        dt = row.get("date")

        if val > peak:
            peak = val
            peak_date = dt
            current_dd_start = None

        dd = (peak - val) / peak if peak > 0 else 0

        if dd > 0 and current_dd_start is None:
            current_dd_start = dt

        if dd > max_dd:
            max_dd = dd
            trough_date = dt

        series.append({"date": dt, "drawdown": round(dd, 6), "portfolio_value": val, "peak": peak})

    current_dd = series[-1]["drawdown"] if series else 0

    dd_duration = 0
    if current_dd > 0 and current_dd_start:
        for i, s in enumerate(series):
            if s["drawdown"] > 0:
                dd_duration += 1

    return {
        "series": series[-90:],
        "max_drawdown": round(max_dd, 6),
        "max_drawdown_duration": dd_duration,
        "current_drawdown": round(current_dd, 6),
        "peak_date": peak_date,
        "trough_date": trough_date,
    }


@router.get("/edge-decay")
async def get_edge_decay():
    sb = get_supabase()
    rows = sb.table("signals").select("created_at,edge").order("created_at").execute()

    if not rows.data:
        return {"series": [], "trend": "insufficient_data"}

    daily = {}
    for row in rows.data:
        dt = row.get("created_at", "")[:10]
        edge = row.get("edge", 0) or 0
        if dt not in daily:
            daily[dt] = {"total": 0, "count": 0}
        daily[dt]["total"] += edge
        daily[dt]["count"] += 1

    series = [
        {"date": dt, "avg_edge": round(v["total"] / v["count"], 6), "signal_count": v["count"]}
        for dt, v in sorted(daily.items())
    ]

    if len(series) >= 2:
        first_half = series[:len(series) // 2]
        second_half = series[len(series) // 2:]
        avg_first = sum(s["avg_edge"] for s in first_half) / len(first_half)
        avg_second = sum(s["avg_edge"] for s in second_half) / len(second_half)
        trend = "decaying" if avg_second < avg_first * 0.85 else ("improving" if avg_second > avg_first * 1.15 else "stable")
    else:
        trend = "insufficient_data"

    return {"series": series[-60:], "trend": trend}


@router.get("/fill-rate")
async def get_fill_rate():
    sb = get_supabase()
    rows = sb.table("orders").select("status,price,size,created_at").execute()

    if not rows.data:
        return {"total": 0, "filled": 0, "rejected": 0, "fill_rate": 0, "avg_slippage": 0}

    total = len(rows.data)
    filled = sum(1 for r in rows.data if r.get("status") == "filled")
    rejected = sum(1 for r in rows.data if r.get("status") == "rejected")

    fill_rate = (filled / total * 100) if total > 0 else 0

    signal_rows = sb.table("signals").select("market_id,market_price,created_at").order("created_at", desc=True).limit(500).execute()
    signal_prices = {}
    for s in (signal_rows.data or []):
        mid = s.get("market_id")
        if mid and mid not in signal_prices:
            signal_prices[mid] = s.get("market_price", 0)

    order_rows = sb.table("orders").select("market_id,price,status").eq("status", "filled").execute()
    slippages = []
    for o in (order_rows.data or []):
        mid = o.get("market_id")
        if mid in signal_prices and signal_prices[mid]:
            slippage = abs(o.get("price", 0) - signal_prices[mid]) / signal_prices[mid]
            slippages.append(slippage)

    avg_slippage = sum(slippages) / len(slippages) if slippages else 0

    return {
        "total": total,
        "filled": filled,
        "rejected": rejected,
        "fill_rate": round(fill_rate, 2),
        "avg_slippage": round(avg_slippage, 6),
    }


@router.get("/bracket-heatmap")
async def get_bracket_heatmap():
    sb = get_supabase()
    signals = sb.table("signals").select("bracket,edge,approved").execute()
    trades = sb.table("trades").select("bracket,side,size,price").execute()
    positions = sb.table("positions").select("bracket,realized_pnl,status").execute()

    brackets = {}

    for s in (signals.data or []):
        b = s.get("bracket", "unknown")
        if b not in brackets:
            brackets[b] = {"signals": 0, "approved": 0, "total_pnl": 0, "edges": [], "wins": 0, "losses": 0}
        brackets[b]["signals"] += 1
        if s.get("approved"):
            brackets[b]["approved"] += 1
        edge = s.get("edge", 0)
        if edge is not None:
            brackets[b]["edges"].append(edge)

    for p in (positions.data or []):
        b = p.get("bracket", "unknown")
        if b not in brackets:
            brackets[b] = {"signals": 0, "approved": 0, "total_pnl": 0, "edges": [], "wins": 0, "losses": 0}
        pnl = p.get("realized_pnl", 0) or 0
        brackets[b]["total_pnl"] += pnl
        if pnl > 0:
            brackets[b]["wins"] += 1
        elif pnl < 0:
            brackets[b]["losses"] += 1

    result = []
    for b, v in sorted(brackets.items()):
        total_trades = v["wins"] + v["losses"]
        result.append({
            "bracket": b,
            "total_signals": v["signals"],
            "approved": v["approved"],
            "approval_rate": round(v["approved"] / v["signals"] * 100, 1) if v["signals"] else 0,
            "total_pnl": round(v["total_pnl"], 4),
            "avg_edge": round(sum(v["edges"]) / len(v["edges"]), 6) if v["edges"] else 0,
            "win_rate": round(v["wins"] / total_trades * 100, 1) if total_trades else 0,
            "trade_count": total_trades,
        })

    return result


@router.get("/regime")
async def get_regime():
    sb = get_supabase()
    rows = sb.table("daily_pnl").select("date,portfolio_value").order("date", desc=True).limit(56).execute()

    if not rows.data or len(rows.data) < 7:
        return {"label": "NORMAL", "zscore": 0, "trend": "STABLE", "volatility": 0, "note": "insufficient data"}

    data = list(reversed(rows.data))

    weekly_totals = []
    for i in range(0, len(data) - 6, 7):
        chunk = data[i:i + 7]
        week_sum = sum(r.get("portfolio_value", 0) for r in chunk)
        weekly_totals.append(week_sum)

    if not weekly_totals:
        return {"label": "NORMAL", "zscore": 0, "trend": "STABLE", "volatility": 0}

    regime = detect_regime(weekly_totals)
    return regime


@router.get("/correlation")
async def get_correlation():
    sb = get_supabase()
    rows = sb.table("positions").select("market_id,module_id,side,size,status").eq("status", "open").execute()

    if not rows.data:
        return {"concentration": [], "overlap_pairs": [], "hhi": 0}

    by_market = {}
    total_size = 0
    for r in rows.data:
        mid = r.get("market_id")
        size = abs(r.get("size", 0) or 0)
        total_size += size
        if mid not in by_market:
            by_market[mid] = {"market_id": mid, "modules": set(), "total_size": 0, "sides": set()}
        by_market[mid]["total_size"] += size
        by_market[mid]["modules"].add(r.get("module_id"))
        by_market[mid]["sides"].add(r.get("side"))

    concentration = []
    for mid, v in sorted(by_market.items(), key=lambda x: -x[1]["total_size"]):
        pct = (v["total_size"] / total_size * 100) if total_size else 0
        concentration.append({
            "market_id": mid,
            "total_size": round(v["total_size"], 4),
            "pct_of_portfolio": round(pct, 2),
            "module_count": len(v["modules"]),
            "sides": list(v["sides"]),
        })

    overlap_pairs = []
    markets = list(by_market.keys())
    for i in range(len(markets)):
        for j in range(i + 1, len(markets)):
            m1_mods = by_market[markets[i]]["modules"]
            m2_mods = by_market[markets[j]]["modules"]
            shared = m1_mods & m2_mods
            if shared:
                overlap_pairs.append({
                    "market_a": markets[i],
                    "market_b": markets[j],
                    "shared_modules": list(shared),
                })

    shares = [(v["total_size"] / total_size) for v in by_market.values()] if total_size else []
    hhi = sum(s ** 2 for s in shares) * 10000

    return {
        "concentration": concentration[:20],
        "overlap_pairs": overlap_pairs[:20],
        "hhi": round(hhi, 1),
        "open_positions": len(rows.data),
        "unique_markets": len(by_market),
    }


@router.get("/walk-forward")
async def get_walk_forward(module_id: str = Query(default=None)):
    sb = get_supabase()

    if module_id:
        result = run_walk_forward_check(module_id)
        return result

    modules = sb.table("modules").select("id,name").execute()
    if not modules.data:
        return []

    results = []
    for m in modules.data:
        mid = m.get("id")
        try:
            r = run_walk_forward_check(mid)
            r["module_id"] = mid
            r["module_name"] = m.get("name")
            results.append(r)
        except Exception:
            results.append({"module_id": mid, "module_name": m.get("name"), "valid": None, "reason": "check failed"})

    return results


@router.get("/pnl-attribution")
async def get_pnl_attribution():
    sb = get_supabase()
    positions = sb.table("positions").select("module_id,bracket,realized_pnl,unrealized_pnl,status").execute()
    modules = sb.table("modules").select("id,name,strategy").execute()

    module_map = {m["id"]: m for m in (modules.data or [])}

    by_module = {}
    by_bracket = {}
    by_strategy = {}

    for p in (positions.data or []):
        pnl = (p.get("realized_pnl", 0) or 0) + (p.get("unrealized_pnl", 0) or 0)
        mid = p.get("module_id", "unknown")
        bracket = p.get("bracket", "unknown")

        if mid not in by_module:
            by_module[mid] = {"pnl": 0, "count": 0}
        by_module[mid]["pnl"] += pnl
        by_module[mid]["count"] += 1

        if bracket not in by_bracket:
            by_bracket[bracket] = {"pnl": 0, "count": 0}
        by_bracket[bracket]["pnl"] += pnl
        by_bracket[bracket]["count"] += 1

        mod_info = module_map.get(mid, {})
        strat = mod_info.get("strategy", "unknown")
        if strat not in by_strategy:
            by_strategy[strat] = {"pnl": 0, "count": 0}
        by_strategy[strat]["pnl"] += pnl
        by_strategy[strat]["count"] += 1

    return {
        "by_module": [
            {
                "module_id": k,
                "module_name": module_map.get(k, {}).get("name", k),
                "pnl": round(v["pnl"], 4),
                "positions": v["count"],
            }
            for k, v in sorted(by_module.items(), key=lambda x: -x[1]["pnl"])
        ],
        "by_bracket": [
            {"bracket": k, "pnl": round(v["pnl"], 4), "positions": v["count"]}
            for k, v in sorted(by_bracket.items(), key=lambda x: -x[1]["pnl"])
        ],
        "by_strategy": [
            {"strategy": k, "pnl": round(v["pnl"], 4), "positions": v["count"]}
            for k, v in sorted(by_strategy.items(), key=lambda x: -x[1]["pnl"])
        ],
    }


@router.get("/monte-carlo")
async def get_monte_carlo(simulations: int = Query(default=1000, le=5000), days: int = Query(default=90, le=365)):
    sb = get_supabase()
    rows = sb.table("daily_pnl").select("daily_return").order("date").execute()

    if not rows.data or len(rows.data) < 5:
        return {"percentiles": {}, "note": "insufficient historical data"}

    returns = [r.get("daily_return", 0) for r in rows.data]
    mu = sum(returns) / len(returns)
    var = sum((r - mu) ** 2 for r in returns) / max(len(returns) - 1, 1)
    sigma = math.sqrt(var)

    paths = []
    for _ in range(simulations):
        cumulative = 0
        path = []
        for d in range(days):
            cumulative += random.gauss(mu, sigma)
            path.append(cumulative)
        paths.append(path)

    percentiles = {}
    for pct in [5, 25, 50, 75, 95]:
        curve = []
        for d in range(days):
            day_vals = sorted(p[d] for p in paths)
            idx = int(len(day_vals) * pct / 100)
            idx = min(idx, len(day_vals) - 1)
            curve.append(round(day_vals[idx], 6))
        percentiles[f"p{pct}"] = curve[::max(1, days // 30)]

    return {
        "percentiles": percentiles,
        "simulations": simulations,
        "days": days,
        "historical_mean": round(mu, 6),
        "historical_std": round(sigma, 6),
        "sample_size": len(returns),
    }


@router.get("/alert-history")
async def get_alert_history():
    sb = get_supabase()
    rows = (
        sb.table("logs")
        .select("log_type,severity,module_id,message,metadata,created_at")
        .or_("log_type.eq.risk,severity.in.(warning,error,critical)")
        .order("created_at", desc=True)
        .limit(50)
        .execute()
    )
    return rows.data or []


@router.get("/accuracy")
async def get_accuracy(module_id: str = Query(default=None)):
    from api.services.accuracy_tracker import compute_accuracy_report
    return compute_accuracy_report(module_id)


@router.get("/accuracy/trend")
async def get_accuracy_trend(module_id: str = Query(default=None), weeks: int = Query(default=12, le=52)):
    from api.services.accuracy_tracker import get_accuracy_trend as _get_trend
    return _get_trend(module_id, weeks)


@router.get("/accuracy/calibration-curve")
async def get_calibration_curve(module_id: str = Query(default=None)):
    from api.services.accuracy_tracker import compute_accuracy_report
    report = compute_accuracy_report(module_id)
    return {
        "calibration_curve": report["calibration_curve"],
        "confidence_score": report["confidence_score"],
        "sample_size": report["count"],
    }
