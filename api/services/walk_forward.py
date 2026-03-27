import logging
from api.dependencies import get_supabase
from api.services.calibration import get_calibration_stats

log = logging.getLogger(__name__)


def validate_model(module_id: str, min_samples: int = 20, max_brier: float = 0.30) -> dict:
    stats = get_calibration_stats(module_id, limit=min_samples * 2)

    if stats["count"] < min_samples:
        return {
            "valid": True,
            "reason": f"insufficient data ({stats['count']}/{min_samples})",
            "action": "continue",
            "stats": stats,
        }

    avg_brier = stats["avg_brier"]

    if avg_brier > max_brier:
        return {
            "valid": False,
            "reason": f"brier {avg_brier:.4f} exceeds threshold {max_brier}",
            "action": "reduce_kelly",
            "kelly_multiplier": 0.5,
            "stats": stats,
        }

    calibration_drift = _detect_calibration_drift(stats["buckets"])
    if calibration_drift > 0.15:
        return {
            "valid": False,
            "reason": f"calibration drift {calibration_drift:.4f}",
            "action": "reduce_kelly",
            "kelly_multiplier": 0.7,
            "stats": stats,
        }

    return {
        "valid": True,
        "reason": f"brier {avg_brier:.4f} within threshold",
        "action": "continue",
        "stats": stats,
    }


def _detect_calibration_drift(buckets: list[dict]) -> float:
    if not buckets:
        return 0
    drifts = [abs(b["predicted_avg"] - b["actual_avg"]) for b in buckets if b["count"] >= 3]
    return sum(drifts) / len(drifts) if drifts else 0


def run_walk_forward_check(module_id: str) -> dict:
    sb = get_supabase()
    result = validate_model(module_id)

    sb.table("logs").insert({
        "log_type": "system",
        "severity": "warning" if not result["valid"] else "info",
        "module_id": module_id,
        "message": f"Walk-forward: {result['reason']} — action: {result['action']}",
        "metadata": {"brier": result["stats"].get("avg_brier"), "action": result["action"]},
    }).execute()

    sb.table("audit_log").insert({
        "action": "walk_forward_validation",
        "resource_type": "module",
        "resource_id": module_id,
        "details": result,
    }).execute()

    return result
