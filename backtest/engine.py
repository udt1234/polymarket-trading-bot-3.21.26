import json
import math
from datetime import datetime
from pathlib import Path
from scipy import stats

BRACKETS = [
    (0, 19), (20, 39), (40, 59), (60, 79), (80, 99),
    (100, 119), (120, 139), (140, 159), (160, 179), (180, 199), (200, 999),
]
BRACKET_LABELS = [
    "0-19", "20-39", "40-59", "60-79", "80-99",
    "100-119", "120-139", "140-159", "160-179", "180-199", "200+",
]

DATA_ROOT = Path(__file__).parent.parent / "_DataMetricPulls" / "historical"

HANDLE_DEFAULTS = {
    "realDonaldTrump": {"hist_mean": 120.0, "weekly_std": 35.0},
    "elonmusk": {"hist_mean": 210.0, "weekly_std": 80.0},
}


def _load_dow_hourly_stats(handle):
    path = DATA_ROOT / handle / "dow_hourly_stats.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


# --- SIGNAL: Regime Detection (from regime.py) ---
def _detect_regime(daily_counts):
    if len(daily_counts) < 4:
        return "NORMAL", 0, 0
    mean_all = sum(daily_counts) / len(daily_counts)
    std_all = math.sqrt(sum((x - mean_all) ** 2 for x in daily_counts) / len(daily_counts))
    std_all = max(std_all, 1.0)
    recent = daily_counts[-3:]
    mean_recent = sum(recent) / len(recent)
    zscore = (mean_recent - mean_all) / std_all
    volatility = std_all / mean_all if mean_all > 0 else 0
    if zscore > 1.5:
        label = "HIGH"
    elif zscore > 0.5:
        label = "SURGE"
    elif zscore < -1.5:
        label = "LOW"
    elif zscore < -0.5:
        label = "QUIET"
    else:
        label = "NORMAL"
    return label, zscore, volatility


def _regime_modifier(label):
    return {"HIGH": 1.20, "SURGE": 1.10, "NORMAL": 1.0, "QUIET": 0.90, "LOW": 0.80, "TRANSITION": 1.0}.get(label, 1.0)


def _regime_kelly_scale(label, volatility):
    if label in ("HIGH", "SURGE"):
        return 1.0
    elif label == "QUIET":
        return 0.85
    elif label == "LOW":
        return 0.70
    if volatility > 0.5:
        return 0.80
    return 1.0


# --- SIGNAL: DOW-Hourly Pattern ---
def _dow_hourly_modifier(hourly_data, hour_idx, dow_stats):
    if not dow_stats or hour_idx < 0:
        return 1.0
    entry = hourly_data[hour_idx]
    date_str = entry.get("date", "")
    if date_str:
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            dow = str(dt.weekday())
        except Exception:
            return 1.0
    else:
        return 1.0
    dow_avgs = dow_stats.get("dow_averages", {})
    overall_avg = sum(float(v) for v in dow_avgs.values()) / len(dow_avgs) if dow_avgs else 1.0
    this_dow_avg = float(dow_avgs.get(dow, overall_avg))
    ratio = this_dow_avg / overall_avg if overall_avg > 0 else 1.0
    return max(0.80, min(ratio, 1.20))


# --- SIGNAL: Hawkes Burst Detection (from hawkes.py) ---
def _hawkes_burst_modifier(hourly_data, hour_idx):
    if hour_idx < 12:
        return 1.0
    recent_counts = [hourly_data[i]["count"] for i in range(max(0, hour_idx - 6), hour_idx + 1)]
    older_counts = [hourly_data[i]["count"] for i in range(max(0, hour_idx - 12), max(0, hour_idx - 6))]
    if not older_counts:
        return 1.0
    recent_sum = sum(recent_counts)
    older_sum = sum(older_counts)
    older_avg = older_sum / len(older_counts)
    if older_avg <= 0:
        return 1.10 if recent_sum > 3 else 1.0
    burst_ratio = (recent_sum / len(recent_counts)) / older_avg
    consecutive_nonzero = 0
    for c in reversed(recent_counts):
        if c > 0:
            consecutive_nonzero += 1
        else:
            break
    if burst_ratio > 2.5 and consecutive_nonzero >= 4:
        return 1.15
    elif burst_ratio > 1.8 and consecutive_nonzero >= 3:
        return 1.08
    elif burst_ratio < 0.3:
        return 0.92
    return 1.0


# --- SIGNAL: Volatility-adjusted Kelly ---
def _volatility_kelly_scale(hourly_data, hour_idx):
    if hour_idx < 24:
        return 1.0
    counts = [hourly_data[i]["count"] for i in range(max(0, hour_idx - 24), hour_idx + 1)]
    mean_c = sum(counts) / len(counts) if counts else 1
    if mean_c <= 0:
        return 0.80
    std_c = math.sqrt(sum((c - mean_c) ** 2 for c in counts) / len(counts))
    cv = std_c / mean_c
    if cv > 2.0:
        return 0.70
    elif cv > 1.5:
        return 0.80
    elif cv > 1.0:
        return 0.90
    return 1.0


def load_auctions(handle="realDonaldTrump", only_complete=True):
    data_dir = DATA_ROOT / handle
    with open(data_dir / "all_trackings.json") as f:
        data = json.load(f)
    defaults = HANDLE_DEFAULTS.get(handle, {"hist_mean": 120.0, "weekly_std": 35.0})
    defaults["dow_stats"] = _load_dow_hourly_stats(handle)
    auctions = []
    for t in data:
        s = t.get("stats", {})
        if only_complete and not s.get("isComplete"):
            continue
        daily = s.get("daily", [])
        if not daily:
            continue
        auctions.append({
            "title": t["title"],
            "start": t["startDate"],
            "end": t["endDate"],
            "final_count": s["total"],
            "winning_bracket": _count_to_bracket(s["total"]),
            "hourly": daily,
            "total_hours": len(daily),
            "days_total": s.get("daysTotal", 7),
            "handle": handle,
        })
    return auctions, defaults


def _count_to_bracket(count):
    for (lo, hi), label in zip(BRACKETS, BRACKET_LABELS):
        if lo <= count <= hi:
            return label
    return "200+"


def bracket_probs_from_projection(projected_mean, std=None):
    std = max(std or 35.0, 10.0)
    norm_dist = stats.norm(loc=projected_mean, scale=std)
    p_nb = projected_mean / (std ** 2) if std ** 2 > projected_mean else 0.99
    p_nb = max(min(p_nb, 0.99), 0.01)
    r_nb = projected_mean * p_nb / (1 - p_nb)
    r_nb = max(r_nb, 1.0)
    nb = stats.nbinom(r_nb, p_nb)

    probs = {}
    for (lo, hi), label in zip(BRACKETS, BRACKET_LABELS):
        p_norm = norm_dist.cdf(hi + 0.5) - norm_dist.cdf(lo - 0.5)
        p_nb_val = nb.cdf(hi) - nb.cdf(lo - 1) if lo > 0 else nb.cdf(hi)
        probs[label] = 0.4 * max(p_norm, 0) + 0.6 * max(p_nb_val, 0)
    total = sum(probs.values())
    if total > 0:
        probs = {k: v / total for k, v in probs.items()}
    return probs


def _compute_signal_modifier(hourly_data, hour_idx, total_hours):
    if hour_idx < 6:
        return 1.0
    recent = [hourly_data[i]["count"] for i in range(max(0, hour_idx - 6), hour_idx + 1)]
    older = [hourly_data[i]["count"] for i in range(max(0, hour_idx - 24), max(0, hour_idx - 6))]
    if not older:
        return 1.0
    recent_avg = sum(recent) / len(recent)
    older_avg = sum(older) / len(older) if older else recent_avg
    if older_avg <= 0:
        return 1.0 if recent_avg <= 0 else 1.15
    ratio = recent_avg / older_avg
    if ratio > 2.0:
        return 1.20  # surge
    elif ratio > 1.3:
        return 1.10  # elevated
    elif ratio < 0.3:
        return 0.85  # quiet
    elif ratio < 0.6:
        return 0.93  # low
    return 1.0


def _price_momentum(price_history, window=5):
    if len(price_history) < window + 2:
        return 0
    recent = sum(price_history[-3:]) / 3
    older = sum(price_history[-window - 3:-window]) / 3 if len(price_history) >= window + 3 else recent
    return recent - older


def _project_at_hour(hourly_data, hour_idx, total_hours, hist_mean, signal_mod=1.0):
    cum = hourly_data[hour_idx]["cumulative"]
    elapsed_frac = (hour_idx + 1) / total_hours
    if elapsed_frac <= 0:
        return hist_mean
    raw_pace = cum / elapsed_frac
    remaining_frac = 1.0 - elapsed_frac
    projection = remaining_frac * hist_mean + elapsed_frac * raw_pace
    return projection * signal_mod


def _kelly_size(model_prob, market_price, kelly_fraction=0.25, elapsed_pct=0.0):
    if market_price <= 0.01 or market_price >= 0.99:
        return 0
    edge = model_prob - market_price
    if edge <= 0.02:
        return 0
    odds = (1 - market_price) / market_price
    full_kelly = model_prob - (1 - model_prob) / odds
    sized = full_kelly * kelly_fraction
    if elapsed_pct > 0.7:
        sized *= (1.0 - elapsed_pct)
    return max(0, min(sized, 0.15))


def _select_brackets(probs, strategy_alloc, bankroll, market_prices=None, kelly_fraction=0.25, elapsed_pct=0.0):
    sorted_brackets = sorted(probs.items(), key=lambda x: x[1])
    n = len(sorted_brackets)
    positions = {}

    if strategy_alloc == "kelly":
        total_kelly = 0
        kelly_sizes = {}
        for b, model_prob in probs.items():
            mp = (market_prices or probs).get(b, model_prob)
            k = _kelly_size(model_prob, mp, kelly_fraction, elapsed_pct)
            if k > 0:
                kelly_sizes[b] = k
                total_kelly += k

        if not kelly_sizes:
            top = sorted_brackets[-1]
            positions[top[0]] = {"cost": bankroll * 0.1, "buy_price": top[1], "shares": 0, "tier": "kelly_min"}
        else:
            for b, k in kelly_sizes.items():
                cost = bankroll * k / total_kelly * min(total_kelly * 2, 1.0)
                positions[b] = {"cost": cost, "buy_price": probs[b], "shares": 0, "tier": "kelly",
                                "kelly_pct": round(k, 4), "edge": round(probs[b] - (market_prices or probs).get(b, probs[b]), 4)}

    elif isinstance(strategy_alloc, dict) and "cheapest" in strategy_alloc:
        cheap_pct = strategy_alloc.get("cheapest", 0.5)
        mid_pct = strategy_alloc.get("mid", 0.3)
        exp_pct = strategy_alloc.get("expensive", 0.2)

        cheap_brackets = [b for b, p in sorted_brackets if p < 0.08]
        mid_brackets = [b for b, p in sorted_brackets if 0.08 <= p < 0.20]
        exp_brackets = [b for b, p in sorted_brackets if p >= 0.20]

        if not cheap_brackets:
            cheap_brackets = [sorted_brackets[0][0]]
        if not mid_brackets:
            mid_brackets = [sorted_brackets[n // 2][0]]
        if not exp_brackets:
            exp_brackets = [sorted_brackets[-1][0]]

        for b in cheap_brackets:
            positions[b] = {"cost": bankroll * cheap_pct / len(cheap_brackets), "buy_price": probs[b], "shares": 0, "tier": "cheap"}
        for b in mid_brackets:
            positions[b] = {"cost": bankroll * mid_pct / len(mid_brackets), "buy_price": probs[b], "shares": 0, "tier": "mid"}
        for b in exp_brackets:
            positions[b] = {"cost": bankroll * exp_pct / len(exp_brackets), "buy_price": probs[b], "shares": 0, "tier": "expensive"}

    elif strategy_alloc == "equal":
        top_n = [b for b, _ in sorted_brackets[-3:]]
        per_bracket = bankroll / len(top_n)
        for b in top_n:
            positions[b] = {"cost": per_bracket, "buy_price": probs[b], "shares": 0, "tier": "equal"}

    elif strategy_alloc == "all":
        for b, p in sorted_brackets:
            if p >= 0.02:
                positions[b] = {"cost": bankroll * p, "buy_price": p, "shares": 0, "tier": "weighted"}

    for b in positions:
        price = max(positions[b]["buy_price"], 0.01)
        positions[b]["shares"] = positions[b]["cost"] / price

    return positions


def simulate_auction(auction, config, defaults):
    bankroll = config.get("bankroll", 100)
    alloc = config.get("allocation", {"cheapest": 0.5, "mid": 0.3, "expensive": 0.2})
    entry_pct = config.get("entry_pct", 0.15)
    exit_rules = config.get("exit_rules", [])
    hist_mean = defaults["hist_mean"]
    weekly_std = defaults["weekly_std"]
    hourly = auction["hourly"]
    total_hours = auction["total_hours"]
    winning = auction["winning_bracket"]

    # Scale hist_mean/std for non-7-day auctions
    days = auction.get("days_total", 7)
    scaled_mean = hist_mean * days / 7
    scaled_std = weekly_std * math.sqrt(days / 7)

    use_signal_mod = config.get("use_signal_modifier", False)
    use_price_strategy = config.get("price_strategy", None)
    signals = config.get("signals", {})
    use_regime = signals.get("regime", False)
    use_dow = signals.get("dow", False)
    use_hawkes = signals.get("hawkes", False)
    use_vol_adj = signals.get("volatility_adjust", False)
    dow_stats = defaults.get("dow_stats")

    entry_hour = max(1, int(total_hours * entry_pct))

    # Build composite signal modifier at entry
    entry_sig = 1.0
    if use_signal_mod:
        entry_sig *= _compute_signal_modifier(hourly, entry_hour, total_hours)
    if use_regime:
        daily_sums = []
        for d in range(0, entry_hour, 24):
            day_end = min(d + 24, entry_hour)
            day_sum = sum(hourly[i]["count"] for i in range(d, day_end))
            if day_sum > 0 or d > 0:
                daily_sums.append(day_sum)
        if daily_sums:
            regime_label, zscore, vol = _detect_regime(daily_sums)
            entry_sig *= _regime_modifier(regime_label)
    if use_dow and dow_stats:
        entry_sig *= _dow_hourly_modifier(hourly, entry_hour, dow_stats)
    if use_hawkes:
        entry_sig *= _hawkes_burst_modifier(hourly, entry_hour)

    entry_projection = _project_at_hour(hourly, entry_hour, total_hours, scaled_mean, entry_sig)
    entry_probs = bracket_probs_from_projection(entry_projection, scaled_std)

    kelly_fraction = config.get("kelly_fraction", 0.25)
    # Volatility-adjusted Kelly scaling
    kelly_scale = 1.0
    if use_vol_adj:
        kelly_scale *= _volatility_kelly_scale(hourly, entry_hour)
    if use_regime and daily_sums:
        kelly_scale *= _regime_kelly_scale(regime_label, vol)
    effective_kelly = kelly_fraction * kelly_scale

    positions = _select_brackets(entry_probs, alloc, bankroll, kelly_fraction=effective_kelly, elapsed_pct=entry_pct)
    total_invested = sum(p["cost"] for p in positions.values())
    basis_covered = False
    early_exit_amount = 0
    exit_trigger = None
    shares_sold = {}
    stop_loss_exits = 0
    price_histories = {b: [pos["buy_price"]] for b, pos in positions.items()}
    rebalance_count = 0

    for h in range(entry_hour + 1, total_hours):
        sig = 1.0
        if use_signal_mod:
            sig *= _compute_signal_modifier(hourly, h, total_hours)
        if use_regime:
            ds = []
            for d in range(0, h, 24):
                de = min(d + 24, h)
                ds.append(sum(hourly[i]["count"] for i in range(d, de)))
            if ds:
                rl, _, _ = _detect_regime(ds)
                sig *= _regime_modifier(rl)
        if use_dow and dow_stats:
            sig *= _dow_hourly_modifier(hourly, h, dow_stats)
        if use_hawkes:
            sig *= _hawkes_burst_modifier(hourly, h)
        proj = _project_at_hour(hourly, h, total_hours, scaled_mean, sig)
        current_probs = bracket_probs_from_projection(proj, scaled_std)

        for b in price_histories:
            price_histories[b].append(current_probs.get(b, 0))

        if use_price_strategy and h % 12 == 0:
            for b, pos in list(positions.items()):
                if pos["shares"] <= 0:
                    continue
                cp = current_probs.get(b, 0)
                hist = price_histories.get(b, [])
                if len(hist) < 8:
                    continue

                mean_price = sum(hist[-12:]) / min(len(hist), 12)
                momentum = _price_momentum(hist)

                sell_signal = False
                if use_price_strategy in ("mean_reversion", "both"):
                    if cp > mean_price * 1.4 and cp > pos["buy_price"] * 1.3:
                        sell_signal = True
                if use_price_strategy in ("momentum", "both"):
                    if momentum < -0.05 and cp < pos["buy_price"] * 0.9:
                        sell_signal = True

                if sell_signal:
                    sale = pos["shares"] * 0.5 * cp
                    early_exit_amount += sale
                    pos["shares"] *= 0.5
                    rebalance_count += 1

        for rule in exit_rules:
            trigger = rule["trigger"]

            if trigger == "any_range_doubles" and not basis_covered:
                for b, pos in positions.items():
                    current_price = current_probs.get(b, 0)
                    if current_price >= pos["buy_price"] * 2 and pos["shares"] > 0:
                        shares_to_sell = min(pos["shares"], total_invested / current_price)
                        sale_proceeds = shares_to_sell * current_price
                        early_exit_amount += sale_proceeds
                        shares_sold[b] = shares_sold.get(b, 0) + shares_to_sell
                        pos["shares"] -= shares_to_sell
                        if early_exit_amount >= total_invested:
                            basis_covered = True
                            exit_trigger = f"basis_covered via {b} @hr{h}"
                            break

            elif trigger == "pct_gain":
                threshold = rule.get("threshold", 2.0)
                sell_frac = rule.get("sell_fraction", 0.5)
                for b, pos in positions.items():
                    current_price = current_probs.get(b, 0)
                    if current_price >= pos["buy_price"] * threshold and pos["shares"] > 0:
                        shares_to_sell = pos["shares"] * sell_frac
                        sale_proceeds = shares_to_sell * current_price
                        early_exit_amount += sale_proceeds
                        shares_sold[b] = shares_sold.get(b, 0) + shares_to_sell
                        pos["shares"] -= shares_to_sell

            elif trigger == "stop_loss":
                drop_pct = rule.get("drop_pct", 0.30)
                for b, pos in list(positions.items()):
                    current_price = current_probs.get(b, 0)
                    if pos["shares"] > 0 and current_price <= pos["buy_price"] * (1 - drop_pct):
                        sale_proceeds = pos["shares"] * current_price
                        early_exit_amount += sale_proceeds
                        shares_sold[b] = shares_sold.get(b, 0) + pos["shares"]
                        pos["shares"] = 0
                        stop_loss_exits += 1
                        if not exit_trigger:
                            exit_trigger = f"stop_loss {b} @hr{h}"

            elif trigger == "buy_high_to_hedge":
                threshold_odds = rule.get("odds_threshold", 0.90)
                hedge_pct = rule.get("hedge_pct", 0.20)
                elapsed_frac = (h + 1) / total_hours
                if elapsed_frac >= 0.6:
                    all_losing = all(
                        current_probs.get(b, 0) < pos["buy_price"] * 0.5
                        for b, pos in positions.items() if pos["shares"] > 0
                    )
                    if all_losing:
                        for b_label, p in current_probs.items():
                            if p >= threshold_odds and b_label not in positions:
                                hedge_cost = bankroll * hedge_pct
                                positions[b_label] = {
                                    "cost": hedge_cost,
                                    "buy_price": p,
                                    "shares": hedge_cost / p,
                                    "tier": "hedge",
                                }
                                total_invested += hedge_cost
                                if not exit_trigger:
                                    exit_trigger = f"hedged {b_label}@{p:.0%} hr{h}"
                                break

    settlement = 0
    for b, pos in positions.items():
        if b == winning and pos["shares"] > 0:
            settlement += pos["shares"] * 1.0

    total_returned = early_exit_amount + settlement
    pnl = total_returned - total_invested

    return {
        "auction": auction["title"][:55],
        "final_count": auction["final_count"],
        "winning_bracket": winning,
        "invested": round(total_invested, 2),
        "early_exit": round(early_exit_amount, 2),
        "settlement": round(settlement, 2),
        "returned": round(total_returned, 2),
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl / total_invested * 100, 1) if total_invested > 0 else 0,
        "exit_trigger": exit_trigger or "settlement",
        "positions_held": {b: round(p["shares"], 1) for b, p in positions.items() if p["shares"] > 0},
        "basis_covered": basis_covered,
        "stop_loss_exits": stop_loss_exits,
        "rebalance_count": rebalance_count,
    }


def run_backtest(config, handle="realDonaldTrump"):
    auctions, defaults = load_auctions(handle)
    results = [simulate_auction(a, config, defaults) for a in auctions]
    return summarize(results, config, handle)


def summarize(results, config, handle=""):
    if not results:
        return {"summary": "No completed auctions found.", "results": [], "totals": {}}

    total_invested = sum(r["invested"] for r in results)
    total_returned = sum(r["returned"] for r in results)
    total_pnl = total_returned - total_invested
    winners = [r for r in results if r["pnl"] > 0]
    losers = [r for r in results if r["pnl"] <= 0]
    max_loss = min(r["pnl"] for r in results)
    max_win = max(r["pnl"] for r in results)
    basis_covered_count = sum(1 for r in results if r["basis_covered"])
    stop_loss_count = sum(1 for r in results if r.get("stop_loss_exits", 0) > 0)

    lines = []
    handle_label = handle or "unknown"
    lines.append(f"Handle: {handle_label} ({len(results)} auctions)")
    lines.append(f"Strategy: {json.dumps(config, indent=2)}")
    lines.append("")
    lines.append(f"{'Auction':<55} | {'Inv':>6} | {'Ret':>6} | {'P&L':>7} | Exit")
    lines.append("-" * 100)
    for r in results:
        pnl_str = f"+${r['pnl']:.0f}" if r["pnl"] >= 0 else f"-${abs(r['pnl']):.0f}"
        lines.append(f"{r['auction']:<55} | ${r['invested']:>4.0f} | ${r['returned']:>4.0f} | {pnl_str:>7} | {r['exit_trigger'][:25]}")
    lines.append("=" * 100)
    pnl_str = f"+${total_pnl:.0f}" if total_pnl >= 0 else f"-${abs(total_pnl):.0f}"
    lines.append(f"{'TOTAL':<55} | ${total_invested:>4.0f} | ${total_returned:>4.0f} | {pnl_str:>7}")
    lines.append("")
    lines.append(f"ROI: {total_pnl / total_invested * 100:.1f}%  |  Win rate: {len(winners)}/{len(results)} ({len(winners)/len(results)*100:.0f}%)")
    lines.append(f"Avg P&L: ${total_pnl / len(results):.2f}  |  Max win: +${max_win:.0f}  |  Max loss: -${abs(max_loss):.0f}")
    if basis_covered_count:
        lines.append(f"Basis covered early: {basis_covered_count}/{len(results)} auctions")
    if stop_loss_count:
        lines.append(f"Stop-loss triggered: {stop_loss_count}/{len(results)} auctions")

    return {
        "summary": "\n".join(lines),
        "results": results,
        "totals": {
            "invested": round(total_invested, 2),
            "returned": round(total_returned, 2),
            "pnl": round(total_pnl, 2),
            "roi_pct": round(total_pnl / total_invested * 100, 1) if total_invested > 0 else 0,
            "win_rate": round(len(winners) / len(results) * 100, 1),
            "max_loss": round(max_loss, 2),
            "max_win": round(max_win, 2),
            "basis_covered_count": basis_covered_count,
            "stop_loss_count": stop_loss_count,
        },
    }
