import asyncio
import logging
import math
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from api.dependencies import get_supabase
from api.modules.truth_social.data import _fetch_trackings_raw
from api.modules.truth_social.module_config import get_module_config, save_module_config
from api.modules.truth_social.enhanced_pacing import (
    recency_weighted_averages, dow_variance, pace_acceleration,
    dow_deviation, ensemble_confidence_bands,
)
from api.modules.truth_social.parquet_history import (
    search_parquet_markets, download_and_cache_parquet, preview_parquet_data,
)

router = APIRouter()

DOW_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _detect_handle(module_data: dict) -> str:
    name = (module_data.get("name", "") or "").lower()
    if "truth" in name or "trump" in name:
        return "realDonaldTrump"
    if "elon" in name:
        return "elonmusk"
    return "realDonaldTrump"


def _detect_name_filter(handle: str) -> str:
    if handle == "elonmusk":
        return "tweets"
    return "truth social"


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


@router.get("/{module_id}/auctions")
async def get_auctions(module_id: str, include_past: bool = True):
    sb = get_supabase()
    module = sb.table("modules").select("*").eq("id", module_id).single().execute()
    if not module.data:
        raise HTTPException(status_code=404, detail="Module not found")

    handle = _detect_handle(module.data)
    name_filter = _detect_name_filter(handle)
    now = datetime.now(timezone.utc)

    all_trackings = await _fetch_trackings_raw(handle)

    module_trackings = [
        t for t in all_trackings
        if name_filter in t.get("title", "").lower()
    ]

    results = []
    for t in module_trackings:
        tid = t.get("id") or t.get("trackingId")
        start_str = t.get("startDate", "")
        end_str = t.get("endDate", "")

        try:
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        except Exception:
            continue

        elapsed = max((now - start_dt).total_seconds() / 86400, 0)
        remaining = max((end_dt - now).total_seconds() / 86400, 0)
        is_active = start_dt <= now <= end_dt
        is_past = now > end_dt
        is_future = now < start_dt

        if is_past and not include_past:
            continue

        status = "active" if is_active else ("past" if is_past else "future")

        results.append({
            "tracking_id": str(tid),
            "title": t.get("title", ""),
            "start_date": start_str[:10],
            "end_date": end_str[:10],
            "elapsed_days": round(elapsed, 1),
            "remaining_days": round(remaining, 1),
            "status": status,
            "is_active": is_active,
            "market_link": t.get("marketLink", ""),
        })

    # Sort: active first (by start date), then future, then past (most recent first)
    results.sort(key=lambda x: (
        0 if x["status"] == "active" else (1 if x["status"] == "future" else 2),
        x["start_date"] if x["status"] != "past" else "",
        -x["elapsed_days"] if x["status"] == "past" else 0,
    ))

    return results


def _compute_pacing_models(running_total, elapsed_days, remaining_days, total_days, hist_mean, hist_std, hourly_counts, var, now, cfg, dynamic_brackets=None):
    from api.modules.truth_social.pacing import regular_pace, bayesian_pace, dow_hourly_bayesian_pace
    from api.modules.truth_social.projection import ensemble_weights as ew, ensemble_projection

    pace_val = regular_pace(running_total, elapsed_days, total_days) if elapsed_days > 0 else hist_mean
    bayes_val = bayesian_pace(running_total, elapsed_days, remaining_days, hist_mean, total_days)

    hourly_avgs = {}
    if hourly_counts:
        by_hour = defaultdict(list)
        for h in hourly_counts:
            by_hour[h.get("hour", 0)].append(h["count"])
        hourly_avgs = {k: sum(v) / len(v) for k, v in by_hour.items()}

    remaining_hours = []
    for d in range(int(remaining_days) + 1):
        future_date = now + timedelta(days=d)
        start_hr = now.hour + 1 if d == 0 else 0
        for hr in range(start_hr, 24):
            remaining_hours.append({"hour": hr, "dow": future_date.weekday()})

    dow_weights_map = {i: var.get(i, {}).get("mean", hist_mean / 7) / max(hist_mean / 7, 0.1) for i in range(7)}
    dow_val = dow_hourly_bayesian_pace(running_total, remaining_hours, hourly_avgs, dow_weights_map, hist_mean, elapsed_days, remaining_days)

    model_outputs = {"pace": pace_val, "bayesian": bayes_val, "dow": dow_val, "historical": hist_mean}
    enabled_models = cfg.get("enabled_models", ["pace", "bayesian", "dow", "historical", "hawkes"])
    weights = ew(elapsed_days, total_days, enabled_models=enabled_models)
    bracket_probs = ensemble_projection(model_outputs, weights, hist_std, bracket_labels=dynamic_brackets)
    conf_bands = ensemble_confidence_bands(bracket_probs, top_n=cfg.get("confidence_band_top_n", 3))
    ensemble_avg = sum(model_outputs[k] * weights.get(k, 0) for k in model_outputs)

    return model_outputs, weights, conf_bands, ensemble_avg, hourly_avgs, dow_weights_map, bracket_probs


def _build_daily_table(daily_totals, week_start_str, week_end_str, now, var, hist_mean, dow_weights_map, cfg):
    daily_lookup = {d["date"]: d["count"] for d in daily_totals}

    if week_start_str and week_end_str:
        table_start = datetime.strptime(week_start_str, "%Y-%m-%d").date()
        table_end = datetime.strptime(week_end_str, "%Y-%m-%d").date() + timedelta(days=1)
    else:
        table_start = (now - timedelta(days=cfg.get("pacing_display_days_prior", 10))).date()
        table_end = (now + timedelta(days=cfg.get("pacing_display_days_future", 7))).date()

    daily_table = []
    cumulative = 0
    current_date = table_start
    today_date = now.date()
    while current_date <= table_end:
        dt_str = current_date.strftime("%Y-%m-%d")
        is_today = current_date == today_date
        is_future = current_date > today_date
        dow = current_date.weekday()
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
            "date": dt_str, "day": DOW_DAY_NAMES[dow], "dow": dow,
            "daily_posts": actual,
            "running_total": cumulative if actual is not None else None,
            "dow_avg": round(dow_avg, 1), "dow_weight": dow_weight,
            "dow_std": round(dow_std, 1),
            "deviation": round(deviation, 1) if deviation is not None else None,
            "status": status, "is_today": is_today, "is_future": is_future,
        })
        current_date += timedelta(days=1)
    return daily_table


def _build_dow_heatmap(var):
    return [
        {"day": DOW_DAY_NAMES[i], "dow": i,
         "avg": round(var.get(i, {}).get("mean", 0), 1),
         "std": round(var.get(i, {}).get("std", 0), 1),
         "samples": var.get(i, {}).get("samples", 0)}
        for i in range(7)
    ]


def _build_historical_hourly_heatmap(hist_hourly: dict) -> list[dict]:
    hourly = hist_hourly.get("hourly", {}) if isinstance(hist_hourly, dict) else {}
    if not hourly:
        return []
    return [
        {"hour": hr, "avg": round(hourly.get(hr, 0), 2), "source": "historical"}
        for hr in range(24)
    ]


def _build_dow_hour_heatmap(handle: str) -> list[dict]:
    """Real DOW × hour averages from years of historical hourly post data.

    Reads _DataMetricPulls/historical/{handle}/hourly.json which contains rows of
    {date, hour, dow, count} aggregated from xTracker history. Computes mean
    posts per (dow, hour) cell across all observed weeks.

    Returns 168 cells (7 days × 24 hours). Empty cells (no historical data)
    have avg=0, samples=0.
    """
    import json
    hist_path = Path(__file__).parent.parent.parent / "_DataMetricPulls" / "historical" / handle / "hourly.json"
    if not hist_path.exists():
        return []
    try:
        with open(hist_path) as f:
            rows = json.load(f)
    except Exception:
        return []

    by_cell = defaultdict(list)
    for r in rows:
        try:
            dow = int(r.get("dow"))
            hr = int(r.get("hour"))
            cnt = float(r.get("count", 0))
            if 0 <= dow < 7 and 0 <= hr < 24:
                by_cell[(dow, hr)].append(cnt)
        except (TypeError, ValueError):
            continue

    out = []
    for dow in range(7):
        for hr in range(24):
            vals = by_cell.get((dow, hr), [])
            avg = round(sum(vals) / len(vals), 2) if vals else 0
            out.append({"dow": dow, "hour": hr, "avg": avg, "samples": len(vals)})
    return out


def _build_hourly_heatmap(hourly_counts: list[dict]) -> list[dict]:
    by_hour = defaultdict(list)
    for h in hourly_counts:
        by_hour[h.get("hour", 0)].append(h["count"])
    return [
        {"hour": hr, "avg": round(sum(vals) / len(vals), 2) if vals else 0,
         "std": round((sum((v - sum(vals)/len(vals))**2 for v in vals)/len(vals))**0.5, 2) if len(vals) > 1 else 0,
         "samples": len(vals)}
        for hr, vals in sorted(((h, by_hour.get(h, [])) for h in range(24)), key=lambda x: x[0])
    ]


def _build_ensemble_breakdown(model_outputs, weights):
    return [
        {"model": name.replace("_", " ").title(),
         "projection": round(proj, 1),
         "weight": round(weights.get(name, 0) * 100, 1),
         "contribution": round(proj * weights.get(name, 0), 1)}
        for name, proj in model_outputs.items()
    ]


@router.get("/{module_id}/pacing")
async def get_pacing(module_id: str, tracking_id: str | None = Query(default=None)):
    sb = get_supabase()
    module = sb.table("modules").select("*").eq("id", module_id).single().execute()
    if not module.data:
        raise HTTPException(status_code=404, detail="Module not found")

    from api.modules.truth_social.data import (
        fetch_active_tracking, fetch_tracking_by_id, fetch_xtracker_stats,
        parse_hourly_counts, parse_daily_totals, get_xtracker_summary,
        compute_elapsed_days, fetch_historical_weekly_totals,
        fetch_market_prices, extract_slug_from_tracking,
    )
    from api.modules.truth_social.regime import detect_regime

    cfg = get_module_config(module_id)
    handle = _detect_handle(module.data)
    now = datetime.now(timezone.utc)

    if tracking_id:
        tracking = await fetch_tracking_by_id(handle, tracking_id)
    else:
        tracking = await fetch_active_tracking(handle)

    if tracking:
        tid = tracking.get("id") or tracking.get("trackingId")
        raw_data = await fetch_xtracker_stats(str(tid)) if tid else {}
        if tid:
            raw_data["_tracking"] = tracking
    else:
        raw_data = {}

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

    rw = recency_weighted_averages(weekly_history, half_life=cfg.get("recency_half_life", 4.0))
    hist_mean = rw["mean"] if rw["mean"] > 0 else 100.0
    hist_std = rw["std"] if rw["std"] > 0 else 30.0

    dow_data = []
    for d in daily_totals:
        try:
            dt = datetime.strptime(d["date"], "%Y-%m-%d")
            dow_data.append({"dow": dt.weekday(), "count": d["count"]})
        except Exception:
            pass
    var = dow_variance(dow_data, half_life=cfg.get("recency_half_life", 4.0))

    accel = pace_acceleration(hourly_counts)

    # Fetch dynamic brackets from Gamma API for non-Trump modules
    dynamic_brackets = None
    slug_for_brackets = extract_slug_from_tracking(tracking) if tracking else None
    if slug_for_brackets:
        market_prices_early = await fetch_market_prices(slug_for_brackets)
        if market_prices_early and len(market_prices_early) > 11:
            dynamic_brackets = sorted(market_prices_early.keys(), key=lambda b: int(b.split("-")[0].replace("<", "0").replace("+", "")) if any(c.isdigit() for c in b) else 0)

    model_outputs, weights, conf_bands, ensemble_avg, hourly_avgs, dow_weights_map, bracket_probs = _compute_pacing_models(
        running_total, elapsed_days, remaining_days, total_days,
        hist_mean, hist_std, hourly_counts, var, now, cfg, dynamic_brackets,
    )

    dow_avg_today = var.get(now.weekday(), {}).get("mean", hist_mean / 7.0)
    dev = dow_deviation(running_total, now.hour, now.weekday(), dow_avg_today, hourly_avgs) if hourly_avgs else None

    regime = detect_regime(weekly_history) if len(weekly_history) >= 4 else {"label": "NORMAL", "zscore": 0, "trend": "STABLE", "volatility": 0.8}

    slug = extract_slug_from_tracking(tracking) if tracking else None
    market_prices = await fetch_market_prices(slug) if slug else {}
    market_implied = max(market_prices, key=market_prices.get) if market_prices else None

    from api.modules.truth_social.enhanced_pacing import optimal_entry_timing
    entry_timing = {}
    if conf_bands:
        top_bracket = conf_bands[0]["bracket"]
        snap_rows = sb.table("price_snapshots").select("bracket,price,hour_of_day,dow").eq("module_id", module.data["id"]).execute()
        price_data = [{"bracket": r["bracket"], "price": r["price"], "hour": r["hour_of_day"], "dow": r["dow"]} for r in (snap_rows.data or [])]
        if price_data:
            entry_timing = optimal_entry_timing(price_data, top_bracket)

    daily_table = _build_daily_table(daily_totals, week_start_str, week_end_str, now, var, hist_mean, dow_weights_map, cfg)
    dow_heatmap = _build_dow_heatmap(var)
    hourly_heatmap = _build_hourly_heatmap(hourly_counts)
    dow_hour_heatmap = _build_dow_hour_heatmap(handle)

    from api.modules.truth_social.enhanced_pacing import historical_hourly_averages
    hist_dir = str(Path(__file__).resolve().parent.parent.parent / "_DataMetricPulls" / "historical")
    hist_hourly = historical_hourly_averages(hist_dir, handle)
    historical_hourly_heatmap = _build_historical_hourly_heatmap(hist_hourly)

    ensemble_breakdown = _build_ensemble_breakdown(model_outputs, weights)

    # Truth Social direct fetch is supplemental — must NEVER block the pacing endpoint.
    # Wrap in a tight timeout; on timeout/failure we return None and the frontend renders gracefully.
    truth_social_direct = None
    if handle == "realDonaldTrump" and tracking:
        try:
            from api.modules.truth_social.truthsocial_direct import count_posts_in_window
            ws = (tracking or {}).get("startDate", "")
            we = (tracking or {}).get("endDate", "")
            if ws and we:
                w_start = datetime.fromisoformat(ws.replace("Z", "+00:00"))
                w_end = datetime.fromisoformat(we.replace("Z", "+00:00"))
                w_end_capped = min(w_end, now)
                ts_result = await asyncio.wait_for(
                    count_posts_in_window(w_start, w_end_capped, handle=handle),
                    timeout=3.0,
                )
                ts_count = ts_result.get("count")
                truth_social_direct = {
                    "count": ts_count,
                    "latest_post_at": ts_result.get("latest_post_at"),
                    "diff_vs_xtracker": (ts_count - running_total) if isinstance(ts_count, int) else None,
                    "source": "truthsocial.com/api/v1",
                }
        except asyncio.TimeoutError:
            log.warning("Truth Social direct fetch timed out (>3s) — pacing continues without it")
            truth_social_direct = {"count": None, "error": "timeout"}
        except Exception as e:
            log.warning(f"Truth Social direct fetch failed: {e}")
            truth_social_direct = {"count": None, "error": str(e)[:120]}

    current_auction = {
        "period": f"{week_start_str} to {week_end_str}" if week_start_str else None,
        "title": (tracking or {}).get("title"),
        "running_total": running_total,
        "days_elapsed": round(elapsed_days, 1),
        "days_remaining": round(remaining_days, 1),
        "pace": summary.get("pace", round(list(model_outputs.values())[0], 0)),
        "regime": regime,
        "projected_winner": conf_bands[0]["bracket"] if conf_bands else None,
        "market_implied_winner": market_implied,
        "ensemble_avg": round(ensemble_avg, 1),
        "truth_social_direct": truth_social_direct,
    }

    next_auction = None
    try:
        name_filter = _detect_name_filter(handle)
        all_trackings = await _fetch_trackings_raw(handle)
        future_trackings = [t for t in all_trackings
                        if name_filter in t.get("title", "").lower()
                        and t.get("startDate", "") > (tracking or {}).get("startDate", "")]
        if future_trackings:
            nxt = future_trackings[0]
            next_auction = {
                "period": f"{nxt['startDate'][:10]} to {nxt['endDate'][:10]}",
                "title": nxt.get("title"),
                "running_total": 0, "days_elapsed": 0,
                "days_remaining": nxt.get("daysTotal", 7) if "daysTotal" in nxt else 7,
            }
    except Exception:
        pass

    active_tracking_id = str((tracking or {}).get("id") or (tracking or {}).get("trackingId") or "")

    return {
        "tracking_id": active_tracking_id,
        "running_total": running_total,
        "elapsed_days": round(elapsed_days, 2),
        "remaining_days": round(remaining_days, 2),
        "total_days": total_days,
        "recency_weighted": rw,
        "dow_variance": var,
        "dow_heatmap": dow_heatmap,
        "hourly_heatmap": hourly_heatmap,
        "dow_hour_heatmap": dow_hour_heatmap,
        "historical_hourly_heatmap": historical_hourly_heatmap,
        "pace_acceleration": accel,
        "dow_deviation": dev,
        "confidence_bands": conf_bands,
        "all_bracket_probs": {k: round(v, 4) for k, v in bracket_probs.items()} if bracket_probs else {},
        "regime": regime,
        "daily_table": daily_table,
        "ensemble_breakdown": ensemble_breakdown,
        "ensemble_avg": round(ensemble_avg, 1),
        "current_auction": current_auction,
        "next_auction": next_auction,
        "market_prices": market_prices,
        "market_implied_winner": market_implied,
        "optimal_entry_timing": entry_timing,
        "timestamp": now.isoformat(),
    }


@router.get("/{module_id}/price-heatmaps")
async def get_price_heatmaps(module_id: str):
    sb = get_supabase()
    rows = sb.table("price_snapshots").select(
        "bracket,price,dow,hour_of_day,elapsed_days"
    ).eq("module_id", module_id).order("snapshot_hour").execute()

    if not rows.data:
        return {"by_dow_hour": [], "by_elapsed_day": [], "snapshot_count": 0}

    by_dow_hour = defaultdict(lambda: defaultdict(list))
    by_elapsed = defaultdict(lambda: defaultdict(list))

    for r in rows.data:
        price = r.get("price") or 0
        bracket = r.get("bracket", "")
        if not bracket or price <= 0:
            continue
        by_dow_hour[(r["dow"], r["hour_of_day"])][bracket].append(price)
        if r.get("elapsed_days") is not None:
            by_elapsed[int(r["elapsed_days"])][bracket].append(price)

    dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    dow_hour_rows = []
    for dow in range(7):
        for hour in range(24):
            cell = by_dow_hour.get((dow, hour), {})
            for bracket, prices in cell.items():
                dow_hour_rows.append({
                    "dow": dow, "day": dow_names[dow], "hour": hour,
                    "bracket": bracket,
                    "avg_price": round(sum(prices) / len(prices), 4),
                    "min_price": round(min(prices), 4),
                    "max_price": round(max(prices), 4),
                    "samples": len(prices),
                })

    elapsed_rows = []
    for day_bucket in sorted(by_elapsed.keys()):
        for bracket, prices in by_elapsed[day_bucket].items():
            elapsed_rows.append({
                "elapsed_day": day_bucket,
                "bracket": bracket,
                "avg_price": round(sum(prices) / len(prices), 4),
                "min_price": round(min(prices), 4),
                "max_price": round(max(prices), 4),
                "samples": len(prices),
            })

    return {"by_dow_hour": dow_hour_rows, "by_elapsed_day": elapsed_rows, "snapshot_count": len(rows.data)}


@router.post("/{module_id}/price-snapshot")
async def trigger_price_snapshot(module_id: str):
    from api.services.snapshots import take_price_snapshot
    take_price_snapshot()
    return {"status": "ok", "message": "Price snapshot triggered"}


@router.get("/{module_id}/deep-dive/posts")
async def deep_dive_posts(
    module_id: str,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=10, le=200),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
):
    import json as _json

    sb = get_supabase()
    module = sb.table("modules").select("name").eq("id", module_id).single().execute()
    if not module.data:
        raise HTTPException(status_code=404, detail="Module not found")

    handle = _detect_handle(module.data)

    hist_path = Path(__file__).resolve().parent.parent.parent / "_DataMetricPulls" / "historical" / handle / "hourly.json"
    if not hist_path.exists():
        return {"data": [], "total": 0, "page": page, "per_page": per_page}

    with open(hist_path) as f:
        all_posts = _json.load(f)

    if date_from:
        all_posts = [p for p in all_posts if p.get("date", "") >= date_from]
    if date_to:
        all_posts = [p for p in all_posts if p.get("date", "") <= date_to]

    all_posts.sort(key=lambda x: (x.get("date", ""), x.get("hour", 0)), reverse=True)
    total = len(all_posts)
    start = (page - 1) * per_page
    page_data = all_posts[start:start + per_page]

    return {"data": page_data, "total": total, "page": page, "per_page": per_page}


@router.get("/{module_id}/deep-dive/prices")
async def deep_dive_prices(
    module_id: str,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=10, le=200),
    bracket: str = Query(default=""),
    tracking_id: str = Query(default=""),
):
    sb = get_supabase()
    query = sb.table("price_snapshots").select("*", count="exact").eq("module_id", module_id)
    if bracket:
        query = query.eq("bracket", bracket)
    if tracking_id:
        query = query.eq("tracking_id", tracking_id)
    query = query.order("snapshot_hour", desc=True)
    offset = (page - 1) * per_page
    res = query.range(offset, offset + per_page - 1).execute()
    return {"data": res.data, "total": res.count or 0, "page": page, "per_page": per_page}


@router.get("/{module_id}/deep-dive/signals")
async def deep_dive_signals(
    module_id: str,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=30, ge=10, le=100),
):
    sb = get_supabase()
    query = sb.table("signals").select("*", count="exact").eq("module_id", module_id)
    query = query.order("created_at", desc=True)
    offset = (page - 1) * per_page
    res = query.range(offset, offset + per_page - 1).execute()
    return {"data": res.data, "total": res.count or 0, "page": page, "per_page": per_page}


@router.get("/{module_id}/deep-dive/decisions")
async def deep_dive_decisions(
    module_id: str,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=30, ge=10, le=100),
    market_id: str = Query(default=""),
):
    sb = get_supabase()

    # Get trades with context
    trade_q = sb.table("trades").select("*", count="exact").eq("module_id", module_id)
    if market_id:
        trade_q = trade_q.eq("market_id", market_id)
    trade_q = trade_q.order("executed_at", desc=True)
    offset = (page - 1) * per_page
    trades = trade_q.range(offset, offset + per_page - 1).execute()

    # Enrich trades with signal context
    enriched = []
    for t in (trades.data or []):
        signal = None
        if t.get("market_id") and t.get("bracket"):
            sig_res = sb.table("signals").select("edge,model_prob,market_price,kelly_pct,metadata").eq(
                "module_id", module_id
            ).eq("market_id", t["market_id"]).eq("bracket", t["bracket"]).eq(
                "approved", True
            ).order("created_at", desc=True).limit(1).execute()
            if sig_res.data:
                signal = sig_res.data[0]

        enriched.append({
            **t,
            "signal_edge": signal.get("edge") if signal else None,
            "signal_model_prob": signal.get("model_prob") if signal else None,
            "signal_market_price": signal.get("market_price") if signal else None,
            "signal_kelly_pct": signal.get("kelly_pct") if signal else None,
            "signal_context": signal.get("metadata") if signal else None,
        })

    # Also get decision logs for this module
    logs = sb.table("logs").select("message,metadata,created_at,severity").eq(
        "module_id", module_id
    ).in_("log_type", ["decision", "execution"]).order("created_at", desc=True).limit(50).execute()

    return {
        "trades": {"data": enriched, "total": trades.count or 0, "page": page, "per_page": per_page},
        "logs": logs.data or [],
    }


@router.get("/{module_id}/data-sources")
async def module_data_sources(module_id: str):
    """Return status of all data sources + historical data for this module."""
    import json as _json
    from pathlib import Path as _Path

    sb = get_supabase()
    module = sb.table("modules").select("*").eq("id", module_id).single().execute()
    if not module.data:
        raise HTTPException(status_code=404, detail="Module not found")

    handle = _detect_handle(module.data)

    hist_dir = _Path(__file__).parent.parent.parent / "_DataMetricPulls" / "historical" / handle

    # Check what local historical data exists
    local_files = {}
    for fname in ["hourly.json", "daily.json", "weekly_totals.json", "dow_hourly_stats.json",
                   "all_trackings.json", "daily_from_xtracker.json", "hourly.parquet"]:
        fpath = hist_dir / fname
        if fpath.exists():
            size = fpath.stat().st_size
            local_files[fname] = {"exists": True, "size_kb": round(size / 1024, 1)}
        else:
            local_files[fname] = {"exists": False}

    # Load stats summary if available
    stats = {}
    stats_path = hist_dir / "dow_hourly_stats.json"
    if stats_path.exists():
        try:
            with open(stats_path) as f:
                stats = _json.load(f)
        except Exception:
            pass

    # Get most recent signal with metadata
    recent_signal = None
    try:
        res = sb.table("signals").select("metadata,created_at").eq("module_id", module_id).order("created_at", desc=True).limit(1).execute()
        if res.data and res.data[0].get("metadata"):
            recent_signal = res.data[0]
    except Exception:
        pass

    return {
        "handle": handle,
        "historical_files": local_files,
        "stats_summary": {
            "dow_averages": stats.get("dow_averages", {}),
            "hourly_averages": stats.get("hourly_averages", {}),
            "total_posts": stats.get("total_posts", 0),
            "total_days": stats.get("total_days", 0),
            "date_range": stats.get("date_range", {}),
        },
        "recent_signal_context": recent_signal.get("metadata") if recent_signal else None,
        "recent_signal_time": recent_signal.get("created_at") if recent_signal else None,
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


@router.get("/{module_id}/price-history")
async def price_history(module_id: str, bracket: str | None = None, limit: int = 200):
    sb = get_supabase()
    q = sb.table("price_snapshots").select("bracket,price,volume,snapshot_hour").eq("module_id", module_id)
    if bracket:
        q = q.eq("bracket", bracket)
    result = q.order("snapshot_hour", desc=False).limit(limit).execute()
    series = result.data or []

    trades_result = sb.table("trades").select("bracket,side,price,size,executed_at").eq("module_id", module_id).order("executed_at", desc=False).limit(100).execute()
    trades = trades_result.data or []
    if bracket:
        trades = [t for t in trades if t.get("bracket") == bracket]

    return {"series": series, "trades": trades}


@router.get("/{module_id}/post-count-history")
async def post_count_history(
    module_id: str,
    tracking_id: str | None = Query(default=None),
    limit: int = 500,
):
    """Time-series of xTracker vs Truth Social Direct post counts for the active (or specified) tracking."""
    sb = get_supabase()
    q = sb.table("post_count_snapshots").select(
        "source,tracking_id,window_start,window_end,count,latest_post_at,error,captured_at"
    ).eq("module_id", module_id)

    if tracking_id:
        q = q.eq("tracking_id", tracking_id)
    else:
        from api.modules.truth_social.data import fetch_active_tracking
        handle = _detect_handle({"name": (sb.table("modules").select("name").eq("id", module_id).single().execute().data or {}).get("name", "")})
        try:
            tracking = await fetch_active_tracking(handle)
            if tracking:
                tid = str(tracking.get("id") or tracking.get("trackingId") or "")
                if tid:
                    q = q.eq("tracking_id", tid)
        except Exception:
            pass

    result = q.order("captured_at", desc=False).limit(limit).execute()
    rows = result.data or []

    by_time: dict[str, dict] = {}
    for r in rows:
        t = r.get("captured_at")
        if not t:
            continue
        bucket = by_time.setdefault(t, {"captured_at": t})
        bucket[r["source"]] = r.get("count")
        if r.get("error"):
            bucket[f"{r['source']}_error"] = r["error"]

    series = sorted(by_time.values(), key=lambda x: x["captured_at"])

    latest = {"xtracker": None, "truthsocial_direct": None, "diff": None, "captured_at": None}
    for row in reversed(series):
        if latest["xtracker"] is None and row.get("xtracker") is not None:
            latest["xtracker"] = row["xtracker"]
            latest["captured_at"] = row["captured_at"]
        if latest["truthsocial_direct"] is None and row.get("truthsocial_direct") is not None:
            latest["truthsocial_direct"] = row["truthsocial_direct"]
        if latest["xtracker"] is not None and latest["truthsocial_direct"] is not None:
            break
    if isinstance(latest["xtracker"], int) and isinstance(latest["truthsocial_direct"], int):
        latest["diff"] = latest["truthsocial_direct"] - latest["xtracker"]

    return {"series": series, "latest": latest, "row_count": len(rows)}


@router.get("/{module_id}/kelly-tracker")
async def kelly_tracker(module_id: str, limit: int = 20):
    sb = get_supabase()
    module = sb.table("modules").select("budget").eq("id", module_id).single().execute()
    bankroll = (module.data or {}).get("budget", 100)

    signals = sb.table("signals").select("bracket,kelly_pct,market_price,created_at").eq("module_id", module_id).eq("approved", True).order("created_at", desc=True).limit(limit).execute()
    trades = sb.table("trades").select("bracket,size,price,executed_at").eq("module_id", module_id).order("executed_at", desc=True).limit(limit * 3).execute()

    trades_by_bracket = defaultdict(list)
    for t in (trades.data or []):
        trades_by_bracket[t["bracket"]].append(t)

    rows = []
    for s in (signals.data or []):
        recommended = float(s.get("kelly_pct", 0) or 0) * float(bankroll)
        trade_candidates = trades_by_bracket.get(s["bracket"], [])
        actual = 0.0
        if trade_candidates:
            sig_dt = s.get("created_at", "")
            best = None
            for t in trade_candidates:
                if t.get("executed_at", "") >= sig_dt:
                    if best is None or t["executed_at"] < best["executed_at"]:
                        best = t
            if best:
                actual = float(best.get("size", 0) or 0) * float(best.get("price", 0) or 0)
        rows.append({
            "bracket": s["bracket"],
            "recommended": round(recommended, 2),
            "actual": round(actual, 2),
            "created_at": s.get("created_at"),
        })
    return {"rows": list(reversed(rows))}


@router.get("/{module_id}/latency-histogram")
async def latency_histogram(module_id: str):
    sb = get_supabase()
    signals = sb.table("signals").select("bracket,post_detected_at,created_at").eq("module_id", module_id).eq("approved", True).not_.is_("post_detected_at", "null").order("created_at", desc=True).limit(200).execute()
    trades = sb.table("trades").select("bracket,executed_at").eq("module_id", module_id).order("executed_at", desc=True).limit(500).execute()

    trades_by_bracket = defaultdict(list)
    for t in (trades.data or []):
        trades_by_bracket[t["bracket"]].append(t)

    buckets = {"<1s": 0, "1-5s": 0, "5-30s": 0, "30-60s": 0, ">60s": 0}
    samples = []
    for s in (signals.data or []):
        detected = s.get("post_detected_at")
        if not detected:
            continue
        candidates = trades_by_bracket.get(s["bracket"], [])
        matching = [t for t in candidates if t.get("executed_at", "") >= s.get("created_at", "")]
        if not matching:
            continue
        matching.sort(key=lambda t: t.get("executed_at", ""))
        executed_at = matching[0]["executed_at"]
        try:
            d1 = datetime.fromisoformat(detected.replace("Z", "+00:00"))
            d2 = datetime.fromisoformat(executed_at.replace("Z", "+00:00"))
            latency_s = (d2 - d1).total_seconds()
        except Exception:
            continue
        samples.append(latency_s)
        if latency_s < 1:
            buckets["<1s"] += 1
        elif latency_s < 5:
            buckets["1-5s"] += 1
        elif latency_s < 30:
            buckets["5-30s"] += 1
        elif latency_s < 60:
            buckets["30-60s"] += 1
        else:
            buckets[">60s"] += 1

    avg = round(sum(samples) / len(samples), 2) if samples else 0
    median = round(sorted(samples)[len(samples)//2], 2) if samples else 0
    return {
        "buckets": [{"bucket": k, "count": v} for k, v in buckets.items()],
        "sample_count": len(samples),
        "avg_latency_s": avg,
        "median_latency_s": median,
    }


@router.get("/{module_id}/pending-signals")
async def get_pending_signals(module_id: str, status: str = "waiting"):
    sb = get_supabase()
    res = sb.table("pending_signals").select("*").eq("module_id", module_id).eq("status", status).order("created_at", desc=True).limit(50).execute()
    return {"rows": res.data or []}


@router.delete("/{module_id}/pending-signals/{pending_id}")
async def cancel_pending_signal(module_id: str, pending_id: str):
    sb = get_supabase()
    now_iso = datetime.now(timezone.utc).isoformat()
    sb.table("pending_signals").update({"status": "cancelled", "resolved_at": now_iso}).eq("id", pending_id).eq("module_id", module_id).execute()
    return {"ok": True}


@router.get("/{module_id}/order-book-depth")
async def order_book_depth(module_id: str, bracket: str | None = None):
    sb = get_supabase()
    q = sb.table("order_book_snapshots").select("bracket,best_bid,best_ask,bid_depth_5,ask_depth_5,spread,midpoint,snapshot_at").eq("module_id", module_id)
    if bracket:
        q = q.eq("bracket", bracket)
    result = q.order("snapshot_at", desc=True).limit(50).execute()
    rows = result.data or []
    latest_by_bracket: dict[str, dict] = {}
    for r in rows:
        b = r["bracket"]
        if b not in latest_by_bracket:
            latest_by_bracket[b] = r
    return {"snapshots": list(latest_by_bracket.values())}
