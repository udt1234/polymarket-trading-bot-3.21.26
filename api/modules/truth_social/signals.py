import math


def compute_signal_modifier(news_intensity: int, conflict_score: int, schedule_events: list[str]) -> float:
    mod = 1.0

    if news_intensity > 80:
        mod += 0.15
    elif news_intensity > 50:
        mod += 0.08
    elif news_intensity < 15:
        mod -= 0.05

    if conflict_score > 15:
        mod += 0.20
    elif conflict_score > 8:
        mod += 0.10
    elif conflict_score > 3:
        mod += 0.05

    for event in schedule_events:
        event_lower = event.lower()
        if "rally" in event_lower or "speech" in event_lower:
            mod += 0.15
        elif "legal" in event_lower or "court" in event_lower or "indictment" in event_lower:
            mod += 0.20
        elif "golf" in event_lower:
            mod += 0.05

    return max(0.5, min(mod, 1.5))


def kelly_sizing(
    model_prob: float,
    market_price: float,
    kelly_fraction: float = 0.25,
    volatility: float = 0.8,
    regime_label: str = "NORMAL",
    elapsed_pct: float = 0.0,
) -> dict:
    edge = model_prob - market_price
    if market_price <= 0 or market_price >= 1:
        return {"edge": edge, "kelly_pct": 0, "action": "PASS"}

    odds = (1 - market_price) / market_price
    full_kelly = model_prob - (1 - model_prob) / odds

    if regime_label == "TRANSITION":
        frac = 0.10
    elif volatility > 1.5:
        frac = 0.15
    elif volatility > 1.0:
        frac = 0.20
    else:
        frac = kelly_fraction

    confidence = 0.5 + 0.5 * (1 - min(volatility, 2) / 2)
    sized_kelly = full_kelly * frac * confidence

    # Time-weighted Kelly: reduce sizing late in the auction period
    if elapsed_pct > 0.7:
        time_decay = 1.0 - elapsed_pct
        sized_kelly *= time_decay

    sized_kelly = min(sized_kelly, 0.15)  # position cap

    if sized_kelly > 0.01:
        action = "BUY"
    elif sized_kelly < -0.005:
        action = "AVOID"
    else:
        action = "PASS"

    return {"edge": round(edge, 4), "kelly_pct": round(sized_kelly, 4), "action": action}


def rank_brackets(
    bracket_probs: dict[str, float],
    market_prices: dict[str, float],
    order_books: dict[str, float] | None = None,
) -> list[dict]:
    scored = []
    for bracket, model_prob in bracket_probs.items():
        market_price = market_prices.get(bracket, 0)
        if market_price <= 0 or market_price >= 1:
            continue

        edge = model_prob - market_price
        if edge <= 0:
            continue

        liquidity = 1.0
        if order_books and bracket in order_books:
            liquidity = max(order_books[bracket], 0.01)

        confidence = min(model_prob / market_price, 2.0) if market_price > 0 else 1.0
        score = edge * math.sqrt(liquidity) * confidence

        scored.append({
            "bracket": bracket,
            "score": round(score, 6),
            "edge": round(edge, 4),
            "model_prob": round(model_prob, 4),
            "market_price": round(market_price, 4),
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:3]
