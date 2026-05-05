# Pacing models for Truth Social post count projection
# See: _InstructionalFiles/truth-social-module-spec.md


def regular_pace(posts_so_far: int, elapsed_days: float, total_days: float = 7.0) -> float:
    if elapsed_days <= 0:
        return 0
    return (posts_so_far / elapsed_days) * total_days


def bayesian_pace(
    posts_so_far: int,
    elapsed_days: float,
    remaining_days: float,
    hist_mean: float,
    total_days: float = 7.0,
) -> float:
    current_pace = (posts_so_far / elapsed_days * total_days) if elapsed_days > 0 else hist_mean
    prior_weight = max(remaining_days, 0.5)
    observed_weight = max(elapsed_days, 0)
    return (prior_weight * hist_mean + observed_weight * current_pace) / (prior_weight + observed_weight)


def dow_hourly_bayesian_pace(
    running_total: int,
    remaining_hours: list[dict],  # [{hour: int, dow: int}]
    hourly_avgs: dict[int, float],  # hour -> avg posts
    dow_weights: dict[int, float],  # dow -> weight (relative to overall daily avg)
    hist_mean: float,
    elapsed_days: float,
    remaining_days: float,
) -> float:
    projected_remaining = 0.0
    for h in remaining_hours:
        hour_avg = hourly_avgs.get(h["hour"], 0)
        dow_weight = dow_weights.get(h["dow"], 1.0)
        projected_remaining += hour_avg * dow_weight

    raw_projection = running_total + projected_remaining

    prior_weight = max(remaining_days, 0.5)
    observed_weight = max(elapsed_days, 0)
    return (prior_weight * hist_mean + observed_weight * raw_projection) / (prior_weight + observed_weight)
