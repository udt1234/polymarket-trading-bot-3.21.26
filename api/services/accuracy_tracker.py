import logging
from datetime import datetime, timedelta
from api.dependencies import get_supabase

log = logging.getLogger(__name__)


def compute_accuracy_report(module_id: str = None) -> dict:
    sb = get_supabase()
    query = sb.table("calibration_log").select("*").not_.is_("brier_score", "null")
    if module_id:
        query = query.eq("module_id", module_id)
    rows = query.order("resolved_at", desc=True).limit(1000).execute()

    if not rows.data:
        return {
            "count": 0, "overall_brier": None, "by_bracket": [],
            "by_week": [], "calibration_curve": [], "confidence_score": None,
        }

    data = rows.data
    brier_scores = [r["brier_score"] for r in data]
    overall_brier = sum(brier_scores) / len(brier_scores)

    bracket_groups = {}
    for r in data:
        b = r.get("bracket", "unknown")
        bracket_groups.setdefault(b, []).append(r["brier_score"])

    by_bracket = [
        {"bracket": b, "brier": round(sum(v) / len(v), 6), "count": len(v)}
        for b, v in sorted(bracket_groups.items())
    ]

    week_groups = {}
    for r in data:
        dt = r.get("resolved_at", "")[:10]
        if not dt:
            continue
        try:
            d = datetime.fromisoformat(dt)
            week_key = (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        week_groups.setdefault(week_key, []).append(r["brier_score"])

    by_week = [
        {"week": w, "brier": round(sum(v) / len(v), 6), "count": len(v)}
        for w, v in sorted(week_groups.items())
    ]

    bins = [{"low": i / 10, "high": (i + 1) / 10, "predictions": [], "actuals": []} for i in range(10)]
    for r in data:
        prob = r["predicted_prob"]
        idx = min(int(prob * 10), 9)
        bins[idx]["predictions"].append(prob)
        bins[idx]["actuals"].append(1.0 if r["actual_outcome"] else 0.0)

    calibration_curve = []
    total_cal_error = 0
    cal_count = 0
    for b in bins:
        if not b["predictions"]:
            calibration_curve.append({
                "bin": f"{b['low']:.0%}-{b['high']:.0%}",
                "avg_predicted": None, "avg_actual": None, "count": 0,
            })
            continue
        avg_pred = sum(b["predictions"]) / len(b["predictions"])
        avg_act = sum(b["actuals"]) / len(b["actuals"])
        total_cal_error += abs(avg_pred - avg_act) * len(b["predictions"])
        cal_count += len(b["predictions"])
        calibration_curve.append({
            "bin": f"{b['low']:.0%}-{b['high']:.0%}",
            "avg_predicted": round(avg_pred, 4),
            "avg_actual": round(avg_act, 4),
            "count": len(b["predictions"]),
        })

    confidence_score = round(1.0 - (total_cal_error / cal_count), 4) if cal_count > 0 else None

    return {
        "count": len(data),
        "overall_brier": round(overall_brier, 6),
        "by_bracket": by_bracket,
        "by_week": by_week,
        "calibration_curve": calibration_curve,
        "confidence_score": confidence_score,
    }


def get_accuracy_trend(module_id: str = None, weeks: int = 12) -> dict:
    sb = get_supabase()
    cutoff = (datetime.utcnow() - timedelta(weeks=weeks)).isoformat()

    query = (
        sb.table("calibration_log")
        .select("brier_score,resolved_at")
        .not_.is_("brier_score", "null")
        .gte("resolved_at", cutoff)
    )
    if module_id:
        query = query.eq("module_id", module_id)
    rows = query.order("resolved_at").execute()

    if not rows.data:
        return {"weeks": [], "trend": "insufficient_data", "improving": None}

    week_groups = {}
    for r in rows.data:
        dt = r.get("resolved_at", "")[:10]
        if not dt:
            continue
        try:
            d = datetime.fromisoformat(dt)
            week_key = (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        week_groups.setdefault(week_key, []).append(r["brier_score"])

    weekly = [
        {"week": w, "brier": round(sum(v) / len(v), 6), "count": len(v)}
        for w, v in sorted(week_groups.items())
    ]

    if len(weekly) >= 4:
        first_half = weekly[:len(weekly) // 2]
        second_half = weekly[len(weekly) // 2:]
        avg_first = sum(w["brier"] for w in first_half) / len(first_half)
        avg_second = sum(w["brier"] for w in second_half) / len(second_half)
        if avg_second < avg_first * 0.9:
            trend = "improving"
        elif avg_second > avg_first * 1.1:
            trend = "degrading"
        else:
            trend = "stable"
        improving = avg_second < avg_first
    else:
        trend = "insufficient_data"
        improving = None

    return {"weeks": weekly, "trend": trend, "improving": improving}
