import math
from collections import defaultdict


def recency_weighted_averages(weekly_totals: list[float], half_life: float = 4.0) -> dict:
    if not weekly_totals:
        return {"mean": 0.0, "std": 0.0}
    n = len(weekly_totals)
    weights = [2 ** (-i / half_life) for i in range(n)]
    weights.reverse()
    w_sum = sum(weights)
    w_mean = sum(w * x for w, x in zip(weights, weekly_totals)) / w_sum
    w_var = sum(w * (x - w_mean) ** 2 for w, x in zip(weights, weekly_totals)) / w_sum
    return {"mean": round(w_mean, 2), "std": round(math.sqrt(w_var), 2)}


def regime_conditional_dow_averages(
    daily_data: list[dict], regimes: list[str], target_regime: str
) -> dict[int, float]:
    regime_dow = defaultdict(list)
    all_dow = defaultdict(list)
    for entry, regime in zip(daily_data, regimes):
        dow = entry["dow"]
        count = entry["count"]
        all_dow[dow].append(count)
        if regime == target_regime:
            regime_dow[dow].append(count)

    overall_avg = sum(e["count"] for e in daily_data) / max(len(daily_data), 1)

    result = {}
    for dow in range(7):
        samples = regime_dow.get(dow, [])
        if len(samples) >= 3:
            result[dow] = sum(samples) / len(samples)
        elif all_dow.get(dow):
            result[dow] = sum(all_dow[dow]) / len(all_dow[dow])
        else:
            result[dow] = overall_avg
    return result


def dow_variance(daily_data: list[dict], half_life: float = 4.0) -> dict[int, dict]:
    by_dow = defaultdict(list)
    for entry in daily_data:
        by_dow[entry["dow"]].append(entry["count"])

    result = {}
    for dow in range(7):
        samples = by_dow.get(dow, [])
        if not samples:
            result[dow] = {"mean": 0.0, "std": 0.0, "variance": 0.0, "samples": 0}
            continue
        n = len(samples)
        weights = [2 ** (-i / half_life) for i in range(n)]
        weights.reverse()
        w_sum = sum(weights)
        w_mean = sum(w * x for w, x in zip(weights, samples)) / w_sum
        w_var = sum(w * (x - w_mean) ** 2 for w, x in zip(weights, samples)) / w_sum
        result[dow] = {
            "mean": round(w_mean, 2),
            "std": round(math.sqrt(w_var), 2),
            "variance": round(w_var, 2),
            "samples": n,
        }
    return result


def pace_acceleration(hourly_counts: list[dict], hours_back: int = 24) -> dict:
    if len(hourly_counts) < 2:
        return {"acceleration": 0.0, "momentum": "steady", "current_rate": 0.0, "prior_rate": 0.0}

    recent = hourly_counts[-hours_back:] if len(hourly_counts) >= hours_back else hourly_counts
    mid = len(recent) // 2
    prior_half = recent[:mid]
    current_half = recent[mid:]

    prior_rate = sum(h["count"] for h in prior_half) / max(len(prior_half), 1)
    current_rate = sum(h["count"] for h in current_half) / max(len(current_half), 1)

    if prior_rate > 0:
        acceleration = (current_rate - prior_rate) / prior_rate
    else:
        acceleration = 0.0

    if acceleration > 0.15:
        momentum = "accelerating"
    elif acceleration < -0.15:
        momentum = "decelerating"
    else:
        momentum = "steady"

    return {
        "acceleration": round(acceleration, 4),
        "momentum": momentum,
        "current_rate": round(current_rate, 2),
        "prior_rate": round(prior_rate, 2),
    }


def dow_deviation(
    current_count: int, hour_of_day: int, dow: int,
    dow_avg: float, hourly_distribution: dict[int, float]
) -> dict:
    total_dist = sum(hourly_distribution.values())
    if total_dist <= 0:
        return {"expected": 0, "actual": current_count, "deviation": current_count, "deviation_pct": 0, "status": "on_pace"}

    cumulative_pct = sum(hourly_distribution.get(h, 0) for h in range(hour_of_day + 1)) / total_dist
    expected = dow_avg * cumulative_pct

    deviation = current_count - expected
    deviation_pct = (deviation / expected * 100) if expected > 0 else 0

    if deviation_pct > 10:
        status = "ahead"
    elif deviation_pct < -10:
        status = "behind"
    else:
        status = "on_pace"

    return {
        "expected": round(expected, 1),
        "actual": current_count,
        "deviation": round(deviation, 1),
        "deviation_pct": round(deviation_pct, 1),
        "status": status,
    }


def optimize_periods(
    resolved_auctions: list[dict], min_periods: int = 6, max_periods: int = 20
) -> dict:
    if len(resolved_auctions) < min_periods:
        return {"optimal_periods": min_periods, "brier_scores": {}, "current_brier": 1.0, "improvement_pct": 0.0}

    brier_scores = {}
    for n in range(min_periods, min(max_periods + 1, len(resolved_auctions) + 1)):
        subset = resolved_auctions[-n:]
        score = 0.0
        for a in subset:
            predicted = a.get("predicted_bracket", "")
            actual = a.get("actual_bracket", "")
            prob = 1.0 if predicted == actual else 0.0
            score += (prob - 1.0) ** 2
        brier_scores[n] = round(score / len(subset), 4)

    optimal = min(brier_scores, key=brier_scores.get)
    current_n = resolved_auctions[-1].get("periods_used", min_periods) if resolved_auctions else min_periods
    current_brier = brier_scores.get(current_n, 1.0)
    best_brier = brier_scores[optimal]
    improvement = ((current_brier - best_brier) / current_brier * 100) if current_brier > 0 else 0

    return {
        "optimal_periods": optimal,
        "brier_scores": brier_scores,
        "current_brier": current_brier,
        "improvement_pct": round(improvement, 2),
    }


def period_type_dow_adjustment(
    dow_avgs: dict[int, float], period_start_dow: int, period_end_dow: int
) -> float:
    dows_in_period = []
    d = period_start_dow
    for _ in range(7):
        dows_in_period.append(d)
        if d == period_end_dow:
            break
        d = (d + 1) % 7
    if not dows_in_period:
        dows_in_period = list(range(7))

    daily_avg = sum(dow_avgs.values()) / max(len(dow_avgs), 1)
    period_daily_avg = sum(dow_avgs.get(d, daily_avg) for d in dows_in_period) / len(dows_in_period)

    return round(period_daily_avg * 7, 2)


def ensemble_confidence_bands(
    bracket_probs: dict[str, float], top_n: int = 3
) -> list[dict]:
    sorted_brackets = sorted(bracket_probs.items(), key=lambda x: x[1], reverse=True)
    top = sorted_brackets[:top_n]
    top_sum = sum(p for _, p in top)

    result = []
    cumulative = 0.0
    for rank, (bracket, prob) in enumerate(top, 1):
        cumulative += prob
        result.append({
            "bracket": bracket,
            "probability": round(prob, 4),
            "cumulative": round(cumulative, 4),
            "rank": rank,
        })

    if result:
        result[0]["confidence"] = round(top[0][1] / top_sum, 4) if top_sum > 0 else 0
    return result


def optimal_entry_timing(historical_prices: list[dict], bracket: str) -> dict:
    filtered = [p for p in historical_prices if p.get("bracket") == bracket]
    if not filtered:
        return {"best_hour": 0, "best_dow": 0, "avg_price_at_best": 0, "avg_price_overall": 0, "savings_pct": 0}

    avg_overall = sum(p["price"] for p in filtered) / len(filtered)

    by_combo = defaultdict(list)
    for p in filtered:
        by_combo[(p.get("hour", 0), p.get("dow", 0))].append(p["price"])

    best_combo = None
    best_avg = float("inf")
    for (hour, dow), prices in by_combo.items():
        avg = sum(prices) / len(prices)
        if avg < best_avg:
            best_avg = avg
            best_combo = (hour, dow)

    if best_combo is None:
        return {"best_hour": 0, "best_dow": 0, "avg_price_at_best": 0, "avg_price_overall": round(avg_overall, 4), "savings_pct": 0}

    savings = ((avg_overall - best_avg) / avg_overall * 100) if avg_overall > 0 else 0
    return {
        "best_hour": best_combo[0],
        "best_dow": best_combo[1],
        "avg_price_at_best": round(best_avg, 4),
        "avg_price_overall": round(avg_overall, 4),
        "savings_pct": round(savings, 2),
    }
