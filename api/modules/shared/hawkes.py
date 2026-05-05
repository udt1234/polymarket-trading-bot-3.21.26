import math


def hawkes_intensity(
    event_times: list[float],
    now: float,
    mu: float = 0.5,
    alpha: float = 0.8,
    beta: float = 1.2,
) -> float:
    intensity = mu
    for t in event_times:
        if t < now:
            intensity += alpha * math.exp(-beta * (now - t))
    return intensity


def hawkes_pace(
    hourly_counts: list[dict],
    remaining_hours: int,
    running_total: int,
    mu: float = 0.5,
    alpha: float = 0.8,
    beta: float = 1.2,
) -> float:
    if not hourly_counts or remaining_hours <= 0:
        return float(running_total)

    event_times = []
    t = 0.0
    for h in hourly_counts:
        count = h.get("count", 0)
        for _ in range(int(count)):
            event_times.append(t + 0.5)
        t += 1.0

    now = t
    projected = float(running_total)

    for hour_ahead in range(remaining_hours):
        current_t = now + hour_ahead
        intensity = hawkes_intensity(event_times, current_t, mu, alpha, beta)
        projected += max(intensity, 0)
        if intensity > 0.1:
            event_times.append(current_t + 0.5)

    return projected


def fit_hawkes_params(hourly_counts: list[dict]) -> dict:
    if len(hourly_counts) < 6:
        return {"mu": 0.5, "alpha": 0.8, "beta": 1.2, "fitted": False}

    counts = [h.get("count", 0) for h in hourly_counts]
    mean_rate = sum(counts) / len(counts) if counts else 0.5

    burst_pairs = 0
    total_pairs = max(len(counts) - 1, 1)
    for i in range(1, len(counts)):
        if counts[i] > 0 and counts[i - 1] > 0:
            burst_pairs += 1

    clustering = burst_pairs / total_pairs

    consecutive_high = 0
    max_consecutive = 0
    threshold = mean_rate * 1.5
    for c in counts:
        if c > threshold:
            consecutive_high += 1
            max_consecutive = max(max_consecutive, consecutive_high)
        else:
            consecutive_high = 0

    mu = max(mean_rate * 0.3, 0.1)
    alpha = min(clustering * 1.5, 0.95)
    beta = 1.0 / max(max_consecutive, 1)
    beta = max(min(beta, 3.0), 0.3)

    return {"mu": round(mu, 3), "alpha": round(alpha, 3), "beta": round(beta, 3), "fitted": True}
