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


def ensemble_weights(elapsed_days: float, total_days: float = 7.0) -> dict[str, float]:
    remaining = total_days - elapsed_days
    if elapsed_days < 2:
        return {"pace": 0.10, "bayesian": 0.35, "dow": 0.20, "historical": 0.35}
    elif remaining < 2:
        return {"pace": 0.50, "bayesian": 0.30, "dow": 0.15, "historical": 0.05}
    return {"pace": 0.30, "bayesian": 0.35, "dow": 0.20, "historical": 0.15}


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


def ensemble_projection(
    model_outputs: dict[str, float],  # {pace, bayesian, dow, historical} -> projected mean
    weights: dict[str, float],
    weekly_std: float,
    signal_modifier: float = 1.0,
) -> dict[str, float]:
    combined_probs = {label: 0.0 for label in BRACKET_LABELS}

    for model_name, projected_mean in model_outputs.items():
        w = weights.get(model_name, 0)
        adjusted_mean = projected_mean * signal_modifier
        probs = bracket_probabilities(adjusted_mean, weekly_std)
        for label in BRACKET_LABELS:
            combined_probs[label] += w * probs.get(label, 0)

    total = sum(combined_probs.values())
    if total > 0:
        combined_probs = {k: v / total for k, v in combined_probs.items()}
    return combined_probs
