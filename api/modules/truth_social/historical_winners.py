"""Historical bracket-winner frequencies + low-price entry timing.

Two independent inputs to the strategy:
1. `bracket_winner_frequencies` — recency-weighted P(bracket wins) from past
   resolved auctions. Blended 70/30 (ensemble / historical) into bracket_probs.
2. `bracket_in_low_window` — true if (now.hour, now.dow) is in the historical
   bottom-quartile price window for that bracket. Used to boost Kelly when
   the market is currently in its empirically-cheap entry window.
"""
import json
import logging
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

BRACKETS = [
    (0, 19, "0-19"), (20, 39, "20-39"), (40, 59, "40-59"), (60, 79, "60-79"),
    (80, 99, "80-99"), (100, 119, "100-119"), (120, 139, "120-139"),
    (140, 159, "140-159"), (160, 179, "160-179"), (180, 199, "180-199"),
    (200, 99999, "200+"),
]


def _bracket_for_total(total: int) -> str | None:
    for lo, hi, label in BRACKETS:
        if lo <= total <= hi:
            return label
    return None


def bracket_winner_frequencies(
    historical_data_dir: str, handle: str, half_life_weeks: float = 8.0,
) -> dict[str, float]:
    """Recency-weighted P(bracket wins) from past resolved auctions.

    Reads `_DataMetricPulls/historical/{handle}/weekly_totals.json` which contains
    completed weeks with `total` post counts. Filters to `days == 7` (full weeks).
    Weight per week = 0.5 ^ (age_in_weeks / half_life). Returns normalized
    probabilities summing to 1.0. Empty if data missing.
    """
    path = Path(historical_data_dir) / handle / "weekly_totals.json"
    if not path.exists():
        log.warning(f"bracket_winner_frequencies: {path} not found")
        return {}

    try:
        with open(path) as f:
            weeks = json.load(f)
    except Exception as e:
        log.warning(f"bracket_winner_frequencies: failed to load {path}: {e}")
        return {}

    completed = [
        w for w in weeks
        if w.get("days", 0) == 7 and (w.get("total") or 0) > 0 and w.get("end")
    ]
    if not completed:
        return {}

    completed.sort(key=lambda w: w["end"])
    most_recent_end = datetime.fromisoformat(completed[-1]["end"].replace("Z", "+00:00"))

    weighted: dict[str, float] = defaultdict(float)
    total_weight = 0.0
    for w in completed:
        try:
            end = datetime.fromisoformat(w["end"].replace("Z", "+00:00"))
        except Exception:
            continue
        age_weeks = (most_recent_end - end).total_seconds() / 86400 / 7
        weight = 0.5 ** (age_weeks / max(half_life_weeks, 0.1))
        bracket = _bracket_for_total(int(w["total"]))
        if bracket:
            weighted[bracket] += weight
            total_weight += weight

    if total_weight <= 0:
        return {}

    return {b: round(weighted[b] / total_weight, 4) for b in weighted}


def blend_with_historical(
    ensemble_probs: dict[str, float],
    historical_freqs: dict[str, float],
    ensemble_weight: float = 0.70,
) -> dict[str, float]:
    """Blend ensemble probabilities with historical winner frequencies.

    `ensemble_weight` controls how much the live ensemble contributes (default 0.70).
    Historical gets `1 - ensemble_weight` (default 0.30). If historical_freqs is
    empty (insufficient data), returns ensemble_probs untouched.
    """
    if not historical_freqs or not ensemble_probs:
        return ensemble_probs
    ew = max(0.0, min(ensemble_weight, 1.0))
    hw = 1.0 - ew
    blended = {}
    for label, p in ensemble_probs.items():
        h = historical_freqs.get(label, 0.0)
        blended[label] = ew * p + hw * h
    total = sum(blended.values())
    if total > 0:
        blended = {k: v / total for k, v in blended.items()}
    return blended


def bracket_in_low_window(
    bracket: str,
    now_hour: int,
    now_dow: int,
    historical_prices: list[dict],
    quartile: float = 0.25,
) -> bool:
    """True if (hour, dow) is in the historical bottom-quartile price window.

    `historical_prices`: list of {bracket, price, hour, dow} from price_snapshots.
    Filters to the bracket, computes the quartile threshold, and returns True if
    any historical observation at this (hour, dow) is at or below that threshold.
    Falls back to False on insufficient data.
    """
    relevant = [p for p in historical_prices if p.get("bracket") == bracket]
    if len(relevant) < 10:
        return False

    by_combo = defaultdict(list)
    for p in relevant:
        h = p.get("hour")
        d = p.get("dow")
        if h is None or d is None:
            continue
        by_combo[(int(h), int(d))].append(float(p.get("price", 0)))

    if not by_combo:
        return False

    combo_avgs = [sum(prices) / len(prices) for prices in by_combo.values() if prices]
    if not combo_avgs:
        return False

    # Need at least 4 distinct (hour, dow) buckets to talk meaningfully about quartiles.
    if len(combo_avgs) < 4:
        return False

    combo_avgs_sorted = sorted(combo_avgs)
    cutoff_idx = max(0, int(math.floor(len(combo_avgs_sorted) * quartile)) - 1)
    threshold = combo_avgs_sorted[cutoff_idx]

    now_prices = by_combo.get((now_hour, now_dow), [])
    if not now_prices:
        return False
    now_avg = sum(now_prices) / len(now_prices)
    return now_avg <= threshold
