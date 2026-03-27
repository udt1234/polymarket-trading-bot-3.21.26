import math
import logging
from api.dependencies import get_supabase

log = logging.getLogger(__name__)


def log_prediction(module_id: str, market_id: str, bracket: str, predicted_prob: float):
    sb = get_supabase()
    sb.table("calibration_log").insert({
        "module_id": module_id,
        "market_id": market_id,
        "bracket": bracket,
        "predicted_prob": predicted_prob,
        "actual_outcome": None,
        "brier_score": None,
        "log_loss": None,
    }).execute()


def resolve_prediction(calibration_id: str, actual_outcome: bool):
    sb = get_supabase()
    row = sb.table("calibration_log").select("predicted_prob").eq("id", calibration_id).single().execute()
    if not row.data:
        return

    prob = row.data["predicted_prob"]
    outcome = 1.0 if actual_outcome else 0.0
    brier = (prob - outcome) ** 2
    log_loss_val = -(outcome * math.log(max(prob, 1e-10)) + (1 - outcome) * math.log(max(1 - prob, 1e-10)))

    sb.table("calibration_log").update({
        "actual_outcome": actual_outcome,
        "brier_score": round(brier, 6),
        "log_loss": round(log_loss_val, 6),
    }).eq("id", calibration_id).execute()


def get_calibration_stats(module_id: str | None = None, limit: int = 100) -> dict:
    sb = get_supabase()
    query = sb.table("calibration_log").select("*").not_.is_("brier_score", "null")
    if module_id:
        query = query.eq("module_id", module_id)
    rows = query.order("resolved_at", desc=True).limit(limit).execute()

    if not rows.data:
        return {"count": 0, "avg_brier": None, "avg_log_loss": None, "buckets": []}

    brier_scores = [r["brier_score"] for r in rows.data]
    log_losses = [r["log_loss"] for r in rows.data if r.get("log_loss") is not None]

    buckets = {}
    for r in rows.data:
        prob = r["predicted_prob"]
        bucket_key = round(prob * 10) / 10
        buckets.setdefault(bucket_key, {"predicted": [], "actual": []})
        buckets[bucket_key]["predicted"].append(prob)
        buckets[bucket_key]["actual"].append(1.0 if r["actual_outcome"] else 0.0)

    calibration_buckets = []
    for k in sorted(buckets.keys()):
        b = buckets[k]
        calibration_buckets.append({
            "predicted_avg": sum(b["predicted"]) / len(b["predicted"]),
            "actual_avg": sum(b["actual"]) / len(b["actual"]),
            "count": len(b["predicted"]),
        })

    return {
        "count": len(brier_scores),
        "avg_brier": round(sum(brier_scores) / len(brier_scores), 6),
        "avg_log_loss": round(sum(log_losses) / len(log_losses), 6) if log_losses else None,
        "buckets": calibration_buckets,
    }


def compute_ensemble_weight_adjustment(module_id: str) -> dict[str, float]:
    stats = get_calibration_stats(module_id, limit=50)
    if stats["count"] < 20 or stats["avg_brier"] is None:
        return {}

    avg_brier = stats["avg_brier"]
    if avg_brier < 0.15:
        return {"confidence_boost": 1.1}
    elif avg_brier > 0.30:
        return {"confidence_penalty": 0.8}
    return {}
