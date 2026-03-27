from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from api.dependencies import get_supabase
from api.modules.truth_social.module_config import get_module_config, save_module_config
from api.modules.truth_social.enhanced_pacing import (
    recency_weighted_averages, dow_variance, pace_acceleration,
    dow_deviation, ensemble_confidence_bands,
)
from api.modules.truth_social.parquet_history import (
    search_parquet_markets, download_and_cache_parquet, preview_parquet_data,
)

router = APIRouter()


class ModuleCreate(BaseModel):
    name: str
    market_slug: str
    strategy: str
    budget: float = 100.0
    max_position_pct: float = 0.15
    data_sources: dict = {}
    resolution_date: str | None = None
    auto_pause: bool = False


class ModuleUpdate(BaseModel):
    name: str | None = None
    strategy: str | None = None
    budget: float | None = None
    max_position_pct: float | None = None
    status: str | None = None
    auto_pause: bool | None = None


@router.get("/")
async def list_modules():
    sb = get_supabase()
    res = sb.table("modules").select("*").order("created_at", desc=True).execute()
    return res.data


@router.get("/{module_id}")
async def get_module(module_id: str):
    sb = get_supabase()
    res = sb.table("modules").select("*").eq("id", module_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Module not found")
    return res.data


@router.post("/")
async def create_module(module: ModuleCreate):
    sb = get_supabase()
    res = sb.table("modules").insert(module.model_dump()).execute()
    return res.data[0]


@router.put("/{module_id}")
async def update_module(module_id: str, update: ModuleUpdate):
    sb = get_supabase()
    data = {k: v for k, v in update.model_dump().items() if v is not None}
    res = sb.table("modules").update(data).eq("id", module_id).execute()
    return res.data[0] if res.data else {}


@router.delete("/{module_id}")
async def delete_module(module_id: str):
    sb = get_supabase()
    sb.table("modules").delete().eq("id", module_id).execute()
    return {"ok": True}


@router.post("/{module_id}/pause")
async def pause_module(module_id: str):
    sb = get_supabase()
    sb.table("modules").update({"status": "paused"}).eq("id", module_id).execute()
    return {"ok": True}


@router.post("/{module_id}/resume")
async def resume_module(module_id: str):
    sb = get_supabase()
    sb.table("modules").update({"status": "active"}).eq("id", module_id).execute()
    return {"ok": True}


@router.post("/{module_id}/kill")
async def kill_module(module_id: str):
    sb = get_supabase()

    module = sb.table("modules").select("id,name,status").eq("id", module_id).single().execute()
    if not module.data:
        raise HTTPException(status_code=404, detail="Module not found")

    sb.table("modules").update({"status": "killed"}).eq("id", module_id).execute()

    open_positions = (
        sb.table("positions")
        .select("id,bracket,size,avg_price")
        .eq("module_id", module_id)
        .eq("status", "open")
        .execute()
    )
    closed_count = 0
    for pos in open_positions.data:
        sb.table("positions").update({
            "status": "closed",
            "exit_price": pos["avg_price"],
            "realized_pnl": 0,
        }).eq("id", pos["id"]).execute()
        closed_count += 1

    sb.table("logs").insert({
        "log_type": "system",
        "severity": "warning",
        "module_id": module_id,
        "message": f"KILL SWITCH: module '{module.data.get('name', module_id)}' killed, {closed_count} positions closed",
        "metadata": {"action": "kill", "positions_closed": closed_count},
    }).execute()

    return {"ok": True, "positions_closed": closed_count}


@router.get("/{module_id}/config")
async def get_config(module_id: str):
    return get_module_config(module_id)


@router.put("/{module_id}/config")
async def update_config(module_id: str, config: dict):
    save_module_config(module_id, config)
    return get_module_config(module_id)


@router.get("/{module_id}/pacing")
async def get_pacing(module_id: str):
    sb = get_supabase()
    module = sb.table("modules").select("*").eq("id", module_id).single().execute()
    if not module.data:
        raise HTTPException(status_code=404, detail="Module not found")

    from datetime import datetime, timezone, timedelta
    from api.modules.truth_social.data import (
        fetch_active_tracking, fetch_xtracker_posts, parse_hourly_counts,
        parse_daily_totals, get_xtracker_summary, compute_elapsed_days,
        fetch_historical_weekly_totals, fetch_market_prices, extract_slug_from_tracking,
    )
    from api.modules.truth_social.regime import detect_regime
    from api.modules.truth_social.pacing import regular_pace, bayesian_pace, dow_hourly_bayesian_pace
    from api.modules.truth_social.projection import ensemble_weights as ew, ensemble_projection
    import math

    cfg = get_module_config(module_id)
    handle = "realDonaldTrump"
    now = datetime.now(timezone.utc)

    # Fetch live data from xTracker
    tracking = await fetch_active_tracking(handle)
    raw_data = await fetch_xtracker_posts(handle) if tracking else {}
    summary = get_xtracker_summary(raw_data)
    hourly_counts = parse_hourly_counts(raw_data)
    daily_totals = parse_daily_totals(raw_data)
    weekly_history = await fetch_historical_weekly_totals(handle, weeks=cfg.get("historical_periods", 9))

    week_start_str = (tracking or {}).get("startDate", "")[:10]
    week_end_str = (tracking or {}).get("endDate", "")[:10]

    running_total = summary.get("total", 0) or (sum(d["count"] for d in daily_totals) if daily_totals else 0)
    elapsed_days = summary.get("days_elapsed", 0) or compute_elapsed_days(week_start_str, now) if week_start_str else 0
    remaining_days = summary.get("days_remaining", 0) or max(7.0 - elapsed_days, 0.01)
    total_days = summary.get("days_total", 7)

    # Recency-weighted stats
    rw = recency_weighted_averages(weekly_history, half_life=cfg.get("recency_half_life", 4.0))
    hist_mean = rw["mean"] if rw["mean"] > 0 else 100.0
    hist_std = rw["std"] if rw["std"] > 0 else 30.0

    # DOW variance from daily data
    dow_day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    dow_data = []
    for d in daily_totals:
        try:
            dt = datetime.strptime(d["date"], "%Y-%m-%d")
            dow_data.append({"dow": dt.weekday(), "count": d["count"]})
        except Exception:
            pass
    var = dow_variance(dow_data, half_life=cfg.get("recency_half_life", 4.0))

    # Pace acceleration
    accel = pace_acceleration(hourly_counts)

    # Hourly averages for DOW deviation
    hourly_avgs = {}
    if hourly_counts:
        from collections import defaultdict
        by_hour = defaultdict(list)
        for h in hourly_counts:
            by_hour[h.get("hour", 0)].append(h["count"])
        hourly_avgs = {k: sum(v) / len(v) for k, v in by_hour.items()}

    # DOW deviation
    dow_avg_today = var.get(now.weekday(), {}).get("mean", hist_mean / 7.0)
    dev = dow_deviation(running_total, now.hour, now.weekday(), dow_avg_today, hourly_avgs) if hourly_avgs else None

    # Regime
    regime = detect_regime(weekly_history) if len(weekly_history) >= 4 else {"label": "NORMAL", "zscore": 0, "trend": "STABLE", "volatility": 0.8}

    # Pacing models
    pace_val = regular_pace(running_total, elapsed_days, total_days) if elapsed_days > 0 else hist_mean
    bayes_val = bayesian_pace(running_total, elapsed_days, remaining_days, hist_mean, total_days)

    # DOW-adjusted
    remaining_hours = []
    for d in range(int(remaining_days) + 1):
        future_date = now + timedelta(days=d)
        start_hr = now.hour + 1 if d == 0 else 0
        for hr in range(start_hr, 24):
            remaining_hours.append({"hour": hr, "dow": future_date.weekday()})
    dow_weights_map = {i: var.get(i, {}).get("mean", hist_mean / 7) / max(hist_mean / 7, 0.1) for i in range(7)}
    dow_val = dow_hourly_bayesian_pace(running_total, remaining_hours, hourly_avgs, dow_weights_map, hist_mean, elapsed_days, remaining_days)

    model_outputs = {"pace": pace_val, "bayesian": bayes_val, "dow": dow_val, "historical": hist_mean}
    weights = ew(elapsed_days, total_days)
    bracket_probs = ensemble_projection(model_outputs, weights, hist_std)
    conf_bands = ensemble_confidence_bands(bracket_probs, top_n=cfg.get("confidence_band_top_n", 3))

    # Ensemble average
    ensemble_avg = sum(model_outputs[k] * weights.get(k, 0) for k in model_outputs)

    # Market prices for comparison
    slug = extract_slug_from_tracking(tracking) if tracking else None
    market_prices = await fetch_market_prices(slug) if slug else {}
    market_implied = max(market_prices, key=market_prices.get) if market_prices else None

    # Build daily table with real data
    days_prior = cfg.get("pacing_display_days_prior", 10)
    days_future_count = cfg.get("pacing_display_days_future", 7)
    daily_lookup = {d["date"]: d["count"] for d in daily_totals}

    daily_table = []
    cumulative = 0
    for d in range(-days_prior, days_future_count + 1):
        dt = now + timedelta(days=d)
        dt_str = dt.strftime("%Y-%m-%d")
        is_today = d == 0
        is_future = d > 0
        dow = dt.weekday()
        actual = daily_lookup.get(dt_str)
        dow_avg = var.get(dow, {}).get("mean", round(hist_mean / 7, 1))
        dow_std = var.get(dow, {}).get("std", 0)
        dow_weight = round(dow_weights_map.get(dow, 1.0), 2)

        if actual is not None:
            cumulative += actual
            deviation = actual - dow_avg if dow_avg > 0 else 0
            status = "ahead" if deviation > 2 else ("behind" if deviation < -2 else "on_pace")
        elif is_future:
            actual = None
            deviation = None
            status = "future"
        else:
            actual = 0
            deviation = -dow_avg
            status = "no_data"

        daily_table.append({
            "date": dt_str,
            "day": dow_day_names[dow],
            "dow": dow,
            "daily_posts": actual,
            "running_total": cumulative if actual is not None else None,
            "dow_avg": round(dow_avg, 1),
            "dow_weight": dow_weight,
            "dow_std": round(dow_std, 1),
            "deviation": round(deviation, 1) if deviation is not None else None,
            "status": status,
            "is_today": is_today,
            "is_future": is_future,
        })

    # DOW averages heatmap
    dow_heatmap = []
    for i in range(7):
        v = var.get(i, {})
        dow_heatmap.append({
            "day": dow_day_names[i],
            "dow": i,
            "avg": round(v.get("mean", 0), 1),
            "std": round(v.get("std", 0), 1),
            "samples": v.get("samples", 0),
        })

    # Ensemble sub-model breakdown
    ensemble_breakdown = []
    for model_name, projection in model_outputs.items():
        w = weights.get(model_name, 0)
        ensemble_breakdown.append({
            "model": model_name.replace("_", " ").title(),
            "projection": round(projection, 1),
            "weight": round(w * 100, 1),
            "contribution": round(projection * w, 1),
        })

    # Current + next auction
    current_auction = {
        "period": f"{week_start_str} to {week_end_str}" if week_start_str else None,
        "title": (tracking or {}).get("title"),
        "running_total": running_total,
        "days_elapsed": round(elapsed_days, 1),
        "days_remaining": round(remaining_days, 1),
        "pace": summary.get("pace", round(pace_val, 0)),
        "regime": regime,
        "projected_winner": conf_bands[0]["bracket"] if conf_bands else None,
        "market_implied_winner": market_implied,
        "ensemble_avg": round(ensemble_avg, 1),
    }

    # Find next auction tracking
    next_auction = None
    try:
        from api.modules.truth_social.data import fetch_active_tracking as fat
        import httpx as hx
        async with hx.AsyncClient(timeout=15) as client:
            r = await client.get("https://xtracker.polymarket.com/api/trackings", params={"platform": "truthsocial", "handle": "realDonaldTrump"})
            all_trackings = r.json().get("data", [])
            trump_future = [t for t in all_trackings
                           if "trump" in t.get("title", "").lower() and "truth social" in t.get("title", "").lower()
                           and t.get("startDate", "") > (tracking or {}).get("startDate", "")]
            if trump_future:
                nxt = trump_future[0]
                next_auction = {
                    "period": f"{nxt['startDate'][:10]} to {nxt['endDate'][:10]}",
                    "title": nxt.get("title"),
                    "running_total": 0,
                    "days_elapsed": 0,
                    "days_remaining": nxt.get("daysTotal", 7) if "daysTotal" in nxt else 7,
                }
    except Exception:
        pass

    return {
        "running_total": running_total,
        "elapsed_days": round(elapsed_days, 2),
        "remaining_days": round(remaining_days, 2),
        "total_days": total_days,
        "recency_weighted": rw,
        "dow_variance": var,
        "dow_heatmap": dow_heatmap,
        "pace_acceleration": accel,
        "dow_deviation": dev,
        "confidence_bands": conf_bands,
        "regime": regime,
        "daily_table": daily_table,
        "ensemble_breakdown": ensemble_breakdown,
        "ensemble_avg": round(ensemble_avg, 1),
        "current_auction": current_auction,
        "next_auction": next_auction,
        "market_prices": market_prices,
        "market_implied_winner": market_implied,
        "timestamp": now.isoformat(),
    }


@router.get("/{module_id}/parquet/search")
async def parquet_search(module_id: str, q: str = Query(..., min_length=1)):
    results = await search_parquet_markets(q)
    return results


@router.post("/{module_id}/parquet/download")
async def parquet_download(module_id: str, body: dict):
    slug = body.get("market_slug", "")
    if not slug:
        raise HTTPException(status_code=400, detail="market_slug required")
    df = await download_and_cache_parquet(slug)
    return {"rows": len(df), "columns": list(df.columns), "market_slug": slug}


@router.get("/{module_id}/parquet/preview")
async def parquet_preview(module_id: str):
    sb = get_supabase()
    module = sb.table("modules").select("market_slug").eq("id", module_id).single().execute()
    if not module.data or not module.data.get("market_slug"):
        raise HTTPException(status_code=404, detail="Module or market_slug not found")
    return preview_parquet_data(module.data["market_slug"])
