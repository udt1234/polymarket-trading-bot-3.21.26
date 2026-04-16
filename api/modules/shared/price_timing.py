"""
Price-timing logic for wait-and-buy-low.

Given a proposed BUY signal, decide whether to execute immediately or defer until
historical analogs suggest the price will drop.

Primary data source: price_snapshots table (recency-weighted).
Fallback: parquet history (truth_social only).
"""

import logging
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

from api.dependencies import get_supabase

log = logging.getLogger(__name__)

MIN_ANALOGS = 5
DEFAULT_LOOKAHEAD_HOURS = [6, 12, 24, 36, 48, 72]
RECENCY_HALF_LIFE_WEEKS = 4.0
ELAPSED_PCT_TOLERANCE = 0.05  # ±5pp
HOUR_OF_DAY_TOLERANCE = 3     # ±3 hours


def _auction_length_bucket(total_days: float) -> str:
    if total_days <= 3:
        return "2d"
    if total_days <= 14:
        return "7d"
    return "30d"


def _recency_weight(snapshot_hour_iso: str, now: datetime) -> float:
    try:
        dt = datetime.fromisoformat(snapshot_hour_iso.replace("Z", "+00:00"))
        weeks_ago = max(0.0, (now - dt).total_seconds() / (86400 * 7))
        return 0.5 ** (weeks_ago / RECENCY_HALF_LIFE_WEEKS)
    except Exception:
        return 0.1


def should_defer_signal(
    module_id: str,
    bracket: str,
    current_price: float,
    elapsed_hours: float,
    total_hours: float,
    dow: int,
    hour_of_day: int,
    slug: str | None = None,
    min_drop_threshold: float = 0.05,
    max_wait_days: float = 3.0,
    abandon_surge_pct: float = 0.05,
) -> dict | None:
    """
    Decide whether to defer a BUY signal. Returns None if buy-now; dict with defer params if wait.

    Args:
        elapsed_hours: Hours since auction start (current auction).
        total_hours: Total auction length in hours.
        dow: Current day of week (0=Monday ... 6=Sunday).
        hour_of_day: Current hour 0-23.
        slug: Current market slug (for parquet fallback).
        min_drop_threshold: Minimum expected drop (fraction, e.g. 0.05 = 5%) to trigger a wait.

    Returns:
        None if should buy now.
        dict{target_price, wait_hours, abandon_price, expected_drop_pct, analog_count, analog_source}
        if should defer.
    """
    if current_price <= 0 or current_price >= 1:
        return None
    if total_hours <= 0:
        return None
    if elapsed_hours < 0:
        return None

    elapsed_pct = min(1.0, elapsed_hours / total_hours)
    total_days = total_hours / 24.0
    length_bucket = _auction_length_bucket(total_days)

    now = datetime.now(timezone.utc)

    analogs = _fetch_analogs_from_snapshots(
        module_id=module_id,
        bracket=bracket,
        elapsed_pct=elapsed_pct,
        length_bucket=length_bucket,
        dow=dow,
        hour_of_day=hour_of_day,
        now=now,
    )
    analog_source = "snapshots"

    if len(analogs) < MIN_ANALOGS:
        analogs = _fetch_analogs_from_snapshots(
            module_id=module_id,
            bracket=bracket,
            elapsed_pct=elapsed_pct,
            length_bucket=None,
            dow=None,
            hour_of_day=None,
            now=now,
        )
        analog_source = "snapshots_wide"

    if len(analogs) < MIN_ANALOGS and slug:
        parquet_analogs = _fetch_analogs_from_parquet(slug, bracket, elapsed_pct)
        if parquet_analogs:
            analogs = parquet_analogs
            analog_source = "parquet"

    if len(analogs) < MIN_ANALOGS:
        log.info(f"price_timing: insufficient analogs for {bracket} (found {len(analogs)}) — buy now")
        return None

    best_drop = 0.0
    best_horizon_hours = 0
    for horizon_hours in DEFAULT_LOOKAHEAD_HOURS:
        if horizon_hours / 24.0 > max_wait_days:
            continue
        weighted_changes = []
        weights = []
        for a in analogs:
            future = _find_future_price(
                module_id=module_id,
                bracket=bracket,
                tracking_id=a["tracking_id"],
                target_elapsed_hours=a["elapsed_hours"] + horizon_hours,
            )
            if future is None:
                continue
            change_pct = (future / a["price"]) - 1.0
            weighted_changes.append(change_pct)
            weights.append(a["weight"])
        if len(weighted_changes) < 3:
            continue
        total_w = sum(weights)
        if total_w <= 0:
            continue
        avg_change = sum(c * w for c, w in zip(weighted_changes, weights)) / total_w
        if avg_change < best_drop:
            best_drop = avg_change
            best_horizon_hours = horizon_hours

    expected_drop_pct = -best_drop
    if expected_drop_pct < min_drop_threshold:
        return None

    target_price = round(current_price * (1 + best_drop), 4)
    abandon_price = round(current_price * (1 + abandon_surge_pct), 4)
    wait_until = now + timedelta(hours=best_horizon_hours)

    return {
        "target_price": target_price,
        "wait_until": wait_until.isoformat(),
        "wait_hours": best_horizon_hours,
        "abandon_price": abandon_price,
        "expected_drop_pct": round(expected_drop_pct, 4),
        "analog_count": len(analogs),
        "analog_source": analog_source,
    }


def _fetch_analogs_from_snapshots(
    module_id: str,
    bracket: str,
    elapsed_pct: float,
    length_bucket: str | None,
    dow: int | None,
    hour_of_day: int | None,
    now: datetime,
) -> list[dict]:
    sb = get_supabase()
    try:
        q = sb.table("price_snapshots").select("bracket,price,elapsed_days,tracking_id,snapshot_hour,dow,hour_of_day").eq("module_id", module_id).eq("bracket", bracket).not_.is_("elapsed_days", "null").not_.is_("tracking_id", "null")
        res = q.limit(2000).execute()
        rows = res.data or []
    except Exception as e:
        log.warning(f"price_timing: snapshot query failed: {e}")
        return []

    if not rows:
        return []

    by_tracking: dict = {}
    for r in rows:
        t = r.get("tracking_id")
        if not t:
            continue
        ed = float(r.get("elapsed_days") or 0)
        prev = by_tracking.get(t, 0)
        if ed > prev:
            by_tracking[t] = ed

    analogs: list[dict] = []
    for r in rows:
        t = r.get("tracking_id")
        if not t or t not in by_tracking:
            continue
        auc_total_days = by_tracking[t]
        if auc_total_days <= 0.1:
            continue

        if length_bucket is not None:
            row_bucket = _auction_length_bucket(auc_total_days)
            if row_bucket != length_bucket:
                continue

        row_elapsed_pct = min(1.0, float(r.get("elapsed_days") or 0) / auc_total_days)
        if abs(row_elapsed_pct - elapsed_pct) > ELAPSED_PCT_TOLERANCE:
            continue

        if dow is not None and r.get("dow") is not None:
            if int(r["dow"]) != dow:
                continue
        if hour_of_day is not None and r.get("hour_of_day") is not None:
            diff = abs(int(r["hour_of_day"]) - hour_of_day)
            diff = min(diff, 24 - diff)
            if diff > HOUR_OF_DAY_TOLERANCE:
                continue

        price = float(r.get("price") or 0)
        if price <= 0 or price >= 1:
            continue

        weight = _recency_weight(r.get("snapshot_hour", ""), now)
        analogs.append({
            "tracking_id": t,
            "price": price,
            "elapsed_days": float(r.get("elapsed_days") or 0),
            "elapsed_hours": float(r.get("elapsed_days") or 0) * 24.0,
            "snapshot_hour": r.get("snapshot_hour"),
            "weight": weight,
        })

    return analogs


def _fetch_analogs_from_parquet(slug: str, bracket: str, elapsed_pct: float) -> list[dict]:
    try:
        from api.modules.truth_social.parquet_history import PARQUET_CACHE_DIR
        cache_path = PARQUET_CACHE_DIR / f"{slug}.parquet"
        if not cache_path.exists():
            return []
        import pandas as pd
        df = pd.read_parquet(cache_path)
        if "bracket" not in df.columns or "elapsed_days" not in df.columns or "price" not in df.columns:
            return []
        df = df[df["bracket"] == bracket].copy()
        if df.empty:
            return []
        if "tracking_id" in df.columns:
            df["auc_total"] = df.groupby("tracking_id")["elapsed_days"].transform("max")
        else:
            df["tracking_id"] = "parquet"
            df["auc_total"] = df["elapsed_days"].max()
        df = df[df["auc_total"] > 0.1]
        df["elapsed_pct"] = df["elapsed_days"] / df["auc_total"]
        df = df[(df["elapsed_pct"] - elapsed_pct).abs() <= ELAPSED_PCT_TOLERANCE]
        if df.empty:
            return []
        analogs = []
        for _, r in df.iterrows():
            analogs.append({
                "tracking_id": str(r.get("tracking_id", "parquet")),
                "price": float(r["price"]),
                "elapsed_days": float(r["elapsed_days"]),
                "elapsed_hours": float(r["elapsed_days"]) * 24.0,
                "snapshot_hour": None,
                "weight": 0.3,
            })
        return analogs
    except Exception as e:
        log.warning(f"price_timing: parquet fallback failed: {e}")
        return []


def _find_future_price(module_id: str, bracket: str, tracking_id: str, target_elapsed_hours: float) -> float | None:
    target_elapsed_days = target_elapsed_hours / 24.0
    tolerance_days = 0.25
    sb = get_supabase()
    try:
        res = sb.table("price_snapshots").select("price,elapsed_days").eq("module_id", module_id).eq("bracket", bracket).eq("tracking_id", tracking_id).gte("elapsed_days", target_elapsed_days - tolerance_days).lte("elapsed_days", target_elapsed_days + tolerance_days).limit(5).execute()
        rows = res.data or []
        if not rows:
            return None
        best = min(rows, key=lambda r: abs(float(r.get("elapsed_days") or 0) - target_elapsed_days))
        price = float(best.get("price") or 0)
        if price <= 0 or price >= 1:
            return None
        return price
    except Exception:
        return None
