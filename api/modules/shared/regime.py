# Regime detection via rolling 7-day Z-scores
# See: _InstructionalFiles/truth-social-module-spec.md

import math


def detect_regime(rolling_sums: list[float]) -> dict:
    if len(rolling_sums) < 4:
        return {"label": "NORMAL", "zscore": 0, "trend": "STABLE", "volatility": 0}

    recent = rolling_sums[-3:]
    mean_all = sum(rolling_sums) / len(rolling_sums)
    std_all = math.sqrt(sum((x - mean_all) ** 2 for x in rolling_sums) / len(rolling_sums))
    std_all = max(std_all, 1.0)

    mean_recent = sum(recent) / len(recent)
    zscore = (mean_recent - mean_all) / std_all

    if len(rolling_sums) >= 4:
        slope = (rolling_sums[-1] - rolling_sums[-2]) / std_all
    else:
        slope = 0

    if abs(slope) > 0.5 and _crosses_threshold(rolling_sums, mean_all, std_all):
        label = "TRANSITION"
    elif zscore > 1.5:
        label = "HIGH"
    elif zscore > 0.5:
        label = "SURGE"
    elif zscore < -1.5:
        label = "LOW"
    elif zscore < -0.5:
        label = "QUIET"
    else:
        label = "NORMAL"

    trend = "RISING" if slope > 0.3 else ("FALLING" if slope < -0.3 else "STABLE")
    volatility = std_all / mean_all if mean_all > 0 else 0

    return {"label": label, "zscore": round(zscore, 2), "trend": trend, "volatility": round(volatility, 2)}


def _crosses_threshold(sums: list[float], mean: float, std: float) -> bool:
    if len(sums) < 2:
        return False
    prev_z = (sums[-2] - mean) / std
    curr_z = (sums[-1] - mean) / std
    thresholds = [-1.5, -0.5, 0.5, 1.5]
    for t in thresholds:
        if (prev_z < t <= curr_z) or (curr_z < t <= prev_z):
            return True
    return False
