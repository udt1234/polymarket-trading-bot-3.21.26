"""S2 Basket-Hold decision layer (BUILD_SPEC F2), pure given inputs.

Rest patient maker bids a margin BELOW fair on the top brackets around the
projection; hold to resolution; salvage-exit clearly-dead holdings."""
import logging

from api.modules.shared import fair_value
from api.services.clob import snap_price
from api.services.risk_manager import Signal

log = logging.getLogger(__name__)


def build_entry_signals(module_id: str, auction: dict, cfg: dict,
                        bankroll: float, held: list[dict],
                        resting_brackets: set[str]) -> list[Signal]:
    prior_mean, prior_std = fair_value.VALIDATED_PRIORS.get(
        auction["duration_type"], fair_value.VALIDATED_PRIORS["2-day"])
    projection = fair_value.gamma_poisson_projection(
        auction["count"], auction["elapsed"], prior_mean, prior_std)
    labels = [b["label"] for b in auction["brackets"]]
    dist = fair_value.bracket_distribution(projection, auction["count"], labels,
                                           auction.get("remaining_hours"))

    by_label = {b["label"]: b for b in auction["brackets"]}
    held_by_bracket = {p["bracket"] for p in held}
    held_prices = [float(p["avg_price"]) for p in held]
    ceiling = min(cfg["aggregate_price_ceiling"], 0.65)

    candidates = sorted(dist.items(), key=lambda kv: kv[1], reverse=True)[
        : int(cfg["num_brackets"])]
    signals: list[Signal] = []
    basket_sum = sum(held_prices)
    for label, fair in candidates:
        b = by_label[label]
        if label in held_by_bracket or label in resting_brackets:
            continue  # already own it or already quoting it
        price = snap_price(fair - cfg["bid_margin_below_fair"], b["tick"])
        if price < b["tick"]:
            continue
        # Never bid AT/ABOVE the ask: post-only would reject, and a maker
        # buys the dip, not the top of book.
        if b["best_ask"] is not None and price >= b["best_ask"]:
            price = snap_price(b["best_ask"] - b["tick"], b["tick"])
        edge = fair - price
        if edge < cfg["min_edge_threshold"]:
            continue
        if basket_sum + price > ceiling:
            continue  # aggregate price ceiling (D4)
        f_star = (fair - price) / (1 - price) if price < 1 else 0
        stake = cfg["kelly_fraction"] * f_star * bankroll
        stake = min(stake, cfg["max_bet_pct"] * bankroll)
        size = int(stake / price) if price > 0 else 0
        if size * price < max(1.0, 0.001 * bankroll) or size < 5:
            continue
        basket_sum += price
        signals.append(Signal(
            module_id=module_id, market_id=b["condition_id"], bracket=label,
            side="BUY", price=price, size=size, token_id=b["yes_token"],
            fair_value=fair, edge=edge, auction_slug=auction["slug"],
            spread=b["spread"], best_bid=b["best_bid"], best_ask=b["best_ask"],
            metadata={"projection": round(projection, 2),
                      "count": auction["count"],
                      "elapsed": round(auction["elapsed"], 4)}))
    return signals


def build_salvage_exits(module_id: str, auction: dict, cfg: dict,
                        held: list[dict]) -> list[Signal]:
    """Post-only SELL a held bracket whose fair value collapsed below the
    salvage threshold - recover equity, recycle collateral (F2)."""
    if not held:
        return []
    prior_mean, prior_std = fair_value.VALIDATED_PRIORS.get(
        auction["duration_type"], fair_value.VALIDATED_PRIORS["2-day"])
    projection = fair_value.gamma_poisson_projection(
        auction["count"], auction["elapsed"], prior_mean, prior_std)
    labels = [b["label"] for b in auction["brackets"]]
    dist = fair_value.bracket_distribution(projection, auction["count"], labels,
                                           auction.get("remaining_hours"))
    by_label = {b["label"]: b for b in auction["brackets"]}
    out: list[Signal] = []
    for p in held:
        fair = dist.get(p["bracket"])
        b = by_label.get(p["bracket"])
        if fair is None or b is None or fair >= cfg["salvage_exit_threshold"]:
            continue
        if b["best_ask"] is None:
            continue
        price = max(snap_price(b["best_ask"], b["tick"]), b["tick"])
        out.append(Signal(
            module_id=module_id, market_id=p["market_id"], bracket=p["bracket"],
            side="SELL", price=price, size=float(p["size"]),
            token_id=p.get("token_id") or b["yes_token"], fair_value=fair,
            auction_slug=auction["slug"], is_exit=True,
            spread=b["spread"], best_bid=b["best_bid"], best_ask=b["best_ask"],
            metadata={"position_id": p["id"], "salvage": True}))
    return out
