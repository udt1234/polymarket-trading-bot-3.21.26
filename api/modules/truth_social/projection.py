# Ensemble projection model: 4 sub-models → bracket probabilities
# See: _InstructionalFiles/truth-social-module-spec.md

import math
from scipy import stats


BRACKETS = [
    (0, 19), (20, 39), (40, 59), (60, 79), (80, 99),
    (100, 119), (120, 139), (140, 159), (160, 179), (180, 199), (200, 999),
]
BRACKET_LABELS = [
    "0-19", "20-39", "40-59", "60-79", "80-99",
    "100-119", "120-139", "140-159", "160-179", "180-199", "200+",
]


def ensemble_weights(
    elapsed_days: float, total_days: float = 7.0, regime_label: str = "NORMAL"
) -> dict[str, float]:
    # Use percentages so this works for 7-day, 14-day, or 30-day auctions
    elapsed_pct = elapsed_days / total_days if total_days > 0 else 0
    remaining_pct = 1.0 - elapsed_pct

    # Hawkes gets more weight during burst regimes
    hawkes_w = 0.15 if regime_label in ("SURGE", "HIGH") else 0.08

    if elapsed_pct < 0.25:
        # Early period: trust history + prior, pace unreliable with little data
        base = {"pace": 0.10, "bayesian": 0.32, "dow": 0.18, "historical": 0.32}
    elif remaining_pct < 0.25:
        # Late period: trust observed pace heavily, history is stale
        base = {"pace": 0.45, "bayesian": 0.27, "dow": 0.13, "historical": 0.05}
    else:
        # Mid period: balanced blend
        base = {"pace": 0.27, "bayesian": 0.32, "dow": 0.18, "historical": 0.13}

    # Scale base weights to make room for Hawkes
    scale = (1.0 - hawkes_w) / sum(base.values())
    weights = {k: round(v * scale, 4) for k, v in base.items()}
    weights["hawkes"] = hawkes_w
    return weights


def bracket_probabilities(mean: float, std: float) -> dict[str, float]:
    std = max(std, 10.0)
    norm = stats.norm(loc=mean, scale=std)
    # Negative binomial params from mean/std
    p_nb = mean / (std ** 2) if std ** 2 > mean else 0.99
    p_nb = max(min(p_nb, 0.99), 0.01)
    r_nb = mean * p_nb / (1 - p_nb)
    r_nb = max(r_nb, 1.0)
    nb = stats.nbinom(r_nb, p_nb)

    probs = {}
    for (lo, hi), label in zip(BRACKETS, BRACKET_LABELS):
        p_norm = norm.cdf(hi + 0.5) - norm.cdf(lo - 0.5)
        p_nb_val = nb.cdf(hi) - nb.cdf(lo - 1) if lo > 0 else nb.cdf(hi)
        probs[label] = 0.4 * max(p_norm, 0) + 0.6 * max(p_nb_val, 0)

    total = sum(probs.values())
    if total > 0:
        probs = {k: v / total for k, v in probs.items()}
    return probs


def calibration_adjusted_weights(
    base_weights: dict[str, float],
    calibration_scores: dict[str, float] | None = None,
    max_adjustment: float = 0.20,
) -> dict[str, float]:
    if not calibration_scores:
        return base_weights

    # Lower Brier score = better calibration = higher weight
    scored_models = {m: calibration_scores[m] for m in base_weights if m in calibration_scores}
    if not scored_models:
        return base_weights

    best = min(scored_models.values())
    worst = max(scored_models.values())
    spread = worst - best if worst > best else 1.0

    adjusted = dict(base_weights)
    for model, score in scored_models.items():
        # Normalize: 0 = worst, 1 = best
        quality = 1.0 - (score - best) / spread if spread > 0 else 0.5
        # Adjustment range: -max_adjustment to +max_adjustment
        adj = (quality - 0.5) * 2 * max_adjustment
        adjusted[model] = max(adjusted[model] + adj * adjusted[model], 0.01)

    total = sum(adjusted.values())
    return {k: v / total for k, v in adjusted.items()}


def ensemble_projection(
    model_outputs: dict[str, float],
    weights: dict[str, float],
    weekly_std: float,
    signal_modifier: float = 1.0,
    calibration_scores: dict[str, float] | None = None,
) -> dict[str, float]:
    # Apply calibration-driven weight adjustment if available
    final_weights = calibration_adjusted_weights(weights, calibration_scores)

    combined_probs = {label: 0.0 for label in BRACKET_LABELS}

    for model_name, projected_mean in model_outputs.items():
        w = final_weights.get(model_name, 0)
        adjusted_mean = projected_mean * signal_modifier
        probs = bracket_probabilities(adjusted_mean, weekly_std)
        for label in BRACKET_LABELS:
            combined_probs[label] += w * probs.get(label, 0)

    # Cross-bracket normalization: force sum to 1.0
    total = sum(combined_probs.values())
    if total > 0:
        combined_probs = {k: v / total for k, v in combined_probs.items()}
    return combined_probs
