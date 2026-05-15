"""5-archetype whale classifier — pure functions, no I/O.

Spec: _ImportantConfigFiles/WHALE_BRACKET_CARDS_SPEC.md lines 44-77 (the 5
archetypes + detection rules) and lines 199-220 (the fill-behavior grid).

The classifier receives a pre-fetched dict of {wallet -> list[fill]} where
each fill is a Polymarket data-api trade record (proxyWallet, side, size,
price, timestamp, outcome, slug, ...). The orchestrator (whale_snapshot.py)
is responsible for fetching trades and the spike series; classifier just
applies rules.

Dual-archetype: a wallet can be 60% Spike + 40% Pace if secondary >25%
of FILL COUNT (not dollars — single large trades shouldn't flip an
archetype). Lock established in the implementation plan.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from statistics import median
from typing import Iterable

ARCHETYPES = ("market_maker", "tail_scooper", "spike_trader", "pace_chaser", "tail_punter")
UNKNOWN = "unknown"

# Dual-archetype threshold — secondary fires when >25% of fills match it.
DUAL_THRESHOLD_PCT = 0.25

# Minimum fills before a wallet can be classified at all (spec caveat 3).
MIN_FILLS_FOR_CLASSIFY = 3


def _hour_index(timestamp: int, auction_start_epoch: int) -> float:
    return (timestamp - auction_start_epoch) / 3600.0


def _window_position(timestamp: int, start: int, end: int) -> float:
    """Returns 0.0 at start, 1.0 at end. Clamped."""
    if end <= start:
        return 0.0
    return max(0.0, min(1.0, (timestamp - start) / (end - start)))


def _is_buy(fill: dict) -> bool:
    return (fill.get("side") or "").upper() == "BUY"


def _is_sell(fill: dict) -> bool:
    return (fill.get("side") or "").upper() == "SELL"


def _dollars(fill: dict) -> float:
    return float(fill.get("size", 0) or 0) * float(fill.get("price", 0) or 0)


def _bucket(fill: dict) -> str:
    """The bracket label this fill landed in. Spec stores bracket on the
    market `slug` (e.g. 'elon-musk-of-tweets-may-9-may-11-40-64' → '40-64').
    We rely on a `bracket` field if the orchestrator pre-tagged the fill;
    otherwise fall back to None."""
    return fill.get("bracket") or fill.get("outcome") or "?"


# --- The 5 detection rules ---


def _rule_market_maker(fills: list[dict], auction_start: int, auction_end: int) -> bool:
    """Active hour 0-5 AND active in last hour AND fills both BUY+SELL AND >100 fills."""
    if len(fills) <= 100:
        return False
    has_buy = any(_is_buy(f) for f in fills)
    has_sell = any(_is_sell(f) for f in fills)
    if not (has_buy and has_sell):
        return False
    # Active in hours 0-5
    last_hour_start = auction_end - 3600
    early_cutoff = auction_start + 5 * 3600
    early = any(auction_start <= f.get("timestamp", 0) <= early_cutoff for f in fills)
    late = any(last_hour_start <= f.get("timestamp", 0) <= auction_end for f in fills)
    return early and late


def _rule_tail_scooper(fills: list[dict], auction_start: int, auction_end: int) -> bool:
    """Avg fill price >0.85 AND first fill in last 30% of window AND <30 fills."""
    if len(fills) >= 30 or not fills:
        return False
    prices = [float(f.get("price", 0) or 0) for f in fills]
    avg_px = sum(prices) / len(prices) if prices else 0.0
    if avg_px <= 0.85:
        return False
    timestamps = [f.get("timestamp", 0) for f in fills]
    first_ts = min(timestamps)
    first_pos = _window_position(first_ts, auction_start, auction_end)
    return first_pos >= 0.70


def _rule_spike_trader(
    fills: list[dict],
    auction_start: int,
    auction_end: int,
    spike_windows: list[tuple[int, int]] | None,
) -> bool:
    """Fills cluster within ±2hr of top-decile Δevent/hr spike AND avg price <0.50.

    `spike_windows`: list of (window_start_epoch, window_end_epoch) tuples
    expanded by ±2hr from each top-decile spike. None → use price-momentum
    fallback (handled by orchestrator pre-populating spike_windows from
    fill-price velocity)."""
    if not fills:
        return False
    prices = [float(f.get("price", 0) or 0) for f in fills]
    avg_px = sum(prices) / len(prices) if prices else 0.0
    if avg_px >= 0.50:
        return False
    if not spike_windows:
        # No spike series and no fallback windows → cannot fire this rule.
        return False
    hit = 0
    for f in fills:
        ts = f.get("timestamp", 0)
        if any(s <= ts <= e for s, e in spike_windows):
            hit += 1
    # Require majority of fills inside spike windows
    return hit / len(fills) >= 0.5


def _rule_pace_chaser(fills: list[dict], auction_start: int, auction_end: int) -> bool:
    """APPROXIMATION of spec rule. Spec requires "30%+ of $ when cumulative
    crosses bracket threshold AND avg price 0.20-0.60 AND first fill >50%
    into window." We can't detect the threshold-crossing without the pace
    series here, so we substitute: avg price in 0.20-0.60 AND first fill
    >50% into window AND ≥3 fills (late entrant paying mid-range prices).

    Trade-offs: false-positives on any late mid-priced buyer that wasn't
    chasing a pace cross; false-negatives on late buyers paying ≥0.60.
    Acceptable for v1 — Phase 4 can refine with the pace series."""
    if len(fills) < 3:
        return False
    prices = [float(f.get("price", 0) or 0) for f in fills]
    avg_px = sum(prices) / len(prices) if prices else 0.0
    if not (0.20 <= avg_px <= 0.60):
        return False
    first_ts = min(f.get("timestamp", 0) for f in fills)
    first_pos = _window_position(first_ts, auction_start, auction_end)
    return first_pos > 0.50


def _rule_tail_punter(fills: list[dict], modal_bucket: str | None) -> bool:
    """70%+ of $ on buckets ≥2 from modal AND avg price <0.10."""
    if not fills:
        return False
    prices = [float(f.get("price", 0) or 0) for f in fills]
    avg_px = sum(prices) / len(prices) if prices else 0.0
    if avg_px >= 0.10:
        return False
    if not modal_bucket:
        return False
    # Use the orchestrator-attached `bracket_distance` if available;
    # otherwise treat unknown buckets as far-from-modal (worst case).
    far_dollars = 0.0
    total_dollars = 0.0
    for f in fills:
        d = _dollars(f)
        total_dollars += d
        dist = f.get("bracket_distance")
        if dist is None:
            # Conservative: only count as far if bucket label differs
            if _bucket(f) != modal_bucket:
                far_dollars += d
        elif dist >= 2:
            far_dollars += d
    if total_dollars <= 0:
        return False
    return (far_dollars / total_dollars) >= 0.70


# --- Public API ---


def classify_wallet(
    fills: list[dict],
    auction_start_epoch: int,
    auction_end_epoch: int,
    spike_windows: list[tuple[int, int]] | None,
    modal_bucket: str | None,
) -> dict:
    """Classify one wallet's fills into archetype + optional secondary.

    Returns {
        "dominant": archetype_key,
        "secondary": archetype_key | None,
        "scores": {archetype: fill_count, ...},  -- absolute fill counts per rule fired
        "fills_count": int,
    }
    """
    if len(fills) < MIN_FILLS_FOR_CLASSIFY:
        return {"dominant": UNKNOWN, "secondary": None, "scores": {}, "fills_count": len(fills)}

    # Score each rule by the count of fills "explained" by that rule. For
    # the binary rules above we treat firing=all fills, not firing=0. For
    # dual classification we use per-fill matching against the simplest
    # archetype-specific criterion (avg price band + window position).
    rules_fired: dict[str, bool] = {
        "market_maker": _rule_market_maker(fills, auction_start_epoch, auction_end_epoch),
        "tail_scooper": _rule_tail_scooper(fills, auction_start_epoch, auction_end_epoch),
        "spike_trader": _rule_spike_trader(fills, auction_start_epoch, auction_end_epoch, spike_windows),
        "pace_chaser": _rule_pace_chaser(fills, auction_start_epoch, auction_end_epoch),
        "tail_punter": _rule_tail_punter(fills, modal_bucket),
    }
    fired = [k for k, v in rules_fired.items() if v]

    if not fired:
        return {"dominant": UNKNOWN, "secondary": None, "scores": {}, "fills_count": len(fills)}

    # Priority ordering when multiple rules fire — favor more specific
    # archetypes. Market-Maker is highest specificity (requires >100 fills
    # AND both sides AND early+late activity).
    priority = ["market_maker", "tail_punter", "tail_scooper", "spike_trader", "pace_chaser"]
    fired_sorted = sorted(fired, key=lambda k: priority.index(k))
    dominant = fired_sorted[0]

    # Secondary fires if a second rule also matched and the wallet has
    # >25% of fills consistent with that rule's criterion. We approximate
    # consistency with per-fill price-band heuristics.
    secondary = None
    if len(fired_sorted) > 1:
        candidate = fired_sorted[1]
        match_fraction = _per_fill_match_fraction(fills, candidate)
        if match_fraction >= DUAL_THRESHOLD_PCT:
            secondary = candidate

    return {
        "dominant": dominant,
        "secondary": secondary,
        "scores": {k: len(fills) if v else 0 for k, v in rules_fired.items()},
        "fills_count": len(fills),
    }


def _per_fill_match_fraction(fills: list[dict], archetype: str) -> float:
    """Approximate per-fill consistency with an archetype's price band.
    Used only for the secondary-archetype 25% threshold check."""
    if not fills:
        return 0.0
    if archetype == "market_maker":
        # MMs typically quote near 0.3-0.7
        match = sum(1 for f in fills if 0.30 <= float(f.get("price", 0) or 0) <= 0.70)
    elif archetype == "tail_scooper":
        match = sum(1 for f in fills if float(f.get("price", 0) or 0) > 0.85)
    elif archetype == "spike_trader":
        match = sum(1 for f in fills if float(f.get("price", 0) or 0) < 0.50)
    elif archetype == "pace_chaser":
        match = sum(1 for f in fills if 0.20 <= float(f.get("price", 0) or 0) <= 0.60)
    elif archetype == "tail_punter":
        match = sum(1 for f in fills if float(f.get("price", 0) or 0) < 0.10)
    else:
        match = 0
    return match / len(fills)


def compute_archetype_breakdown(
    wallet_fills: dict[str, list[dict]],
    classifications: dict[str, dict],
    bot_wallet: str | None,
) -> tuple[dict, dict]:
    """Returns (breakdown, dollar_volume) — share-of-dollars and absolute
    dollars per archetype. The `is_us` flag is set on the archetype that
    contains the bot's wallet."""
    dollars_per_archetype: dict[str, float] = defaultdict(float)
    us_archetype: str | None = None
    bot_lower = (bot_wallet or "").lower()

    for wallet, fills in wallet_fills.items():
        cls = classifications.get(wallet, {})
        arch = cls.get("dominant") or UNKNOWN
        wallet_dollars = sum(_dollars(f) for f in fills)
        dollars_per_archetype[arch] += wallet_dollars
        if bot_lower and wallet.lower() == bot_lower and arch in ARCHETYPES:
            us_archetype = arch

    total = sum(dollars_per_archetype.get(a, 0.0) for a in ARCHETYPES)
    breakdown: dict[str, dict] = {}
    dollar_volume: dict[str, float] = {}
    for a in ARCHETYPES:
        d = dollars_per_archetype.get(a, 0.0)
        breakdown[a] = {
            "share": round(d / total, 4) if total > 0 else 0.0,
            "dollars": round(d, 2),
            "is_us": (a == us_archetype),
        }
        dollar_volume[a] = round(d, 2)
    return breakdown, dollar_volume


def compute_top_wallets(
    wallet_fills: dict[str, list[dict]],
    classifications: dict[str, dict],
    wallet_meta: dict[str, dict],
    bot_wallet: str | None,
    top_n: int = 10,
) -> list[dict]:
    """Top wallets by dollars flowed in this auction.

    `wallet_meta` (optional): {wallet -> {name_or_pseudonym, roi_pct,
    portfolio_value, win_rate_pct, auctions_seen}} — comes from
    whale_wallet_profiles. Missing wallets just get nulls.
    """
    bot_lower = (bot_wallet or "").lower()
    rows = []
    for w, fills in wallet_fills.items():
        cls = classifications.get(w, {})
        dollars = round(sum(_dollars(f) for f in fills), 2)
        meta = wallet_meta.get(w, {})
        rows.append({
            "wallet": w,
            "wallet_short": (w[:6] + "..." + w[-4:]) if len(w) > 10 else w,
            "archetype": cls.get("dominant") or UNKNOWN,
            "archetype_secondary": cls.get("secondary"),
            "fills_count": cls.get("fills_count", 0),
            "dollars_flowed": dollars,
            "name_or_pseudonym": meta.get("name_or_pseudonym") or _pick_name(fills),
            "roi_pct": meta.get("roi_pct"),
            "portfolio_value": meta.get("portfolio_value"),
            "win_rate_pct": meta.get("win_rate_pct"),
            "auctions_seen": meta.get("auctions_seen"),
            "is_us": bool(bot_lower and w.lower() == bot_lower),
        })
    rows.sort(key=lambda r: r["dollars_flowed"], reverse=True)
    return rows[:top_n]


def _pick_name(fills: list[dict]) -> str | None:
    """Best display name from trade records — prefer non-empty `name`,
    else `pseudonym`. Picks from the most recent fill."""
    if not fills:
        return None
    sorted_fills = sorted(fills, key=lambda f: f.get("timestamp", 0), reverse=True)
    for f in sorted_fills:
        n = (f.get("name") or "").strip()
        if n:
            return n
        p = (f.get("pseudonym") or "").strip()
        if p:
            return p
    return None


def compute_grid_metrics(
    wallet_fills: dict[str, list[dict]],
    classifications: dict[str, dict],
    auction_start_epoch: int,
    auction_end_epoch: int,
) -> list[dict]:
    """Per-archetype fill-behavior grid (spec lines 213-219).

    Returns list of {archetype, median_entry_hour, median_entry_price,
    avg_fill_size_usd, roi_pct (placeholder None for v1 — needs resolved
    outcome data we don't carry here)}."""
    by_arch: dict[str, list[dict]] = defaultdict(list)
    for w, fills in wallet_fills.items():
        cls = classifications.get(w, {})
        arch = cls.get("dominant") or UNKNOWN
        if arch in ARCHETYPES:
            by_arch[arch].extend(fills)

    rows = []
    for arch in ARCHETYPES:
        fills = by_arch.get(arch, [])
        if not fills:
            rows.append({
                "archetype": arch,
                "median_entry_hour": None,
                "median_entry_price": None,
                "avg_fill_size_usd": None,
                "fills_count": 0,
            })
            continue
        hours = [_hour_index(f.get("timestamp", 0), auction_start_epoch) for f in fills]
        prices = [float(f.get("price", 0) or 0) for f in fills]
        sizes = [_dollars(f) for f in fills]
        rows.append({
            "archetype": arch,
            "median_entry_hour": round(median(hours), 1) if hours else None,
            "median_entry_price": round(median(prices), 3) if prices else None,
            "avg_fill_size_usd": round(sum(sizes) / len(sizes), 2) if sizes else None,
            "fills_count": len(fills),
        })
    return rows


def compute_modal_bucket(fills_by_bucket: dict[str, list[dict]]) -> str | None:
    """Bucket with the most total dollars flowed. None if no fills."""
    if not fills_by_bucket:
        return None
    totals = {b: sum(_dollars(f) for f in fs) for b, fs in fills_by_bucket.items()}
    if not totals:
        return None
    return max(totals.items(), key=lambda kv: kv[1])[0]


def derive_price_momentum_spike_windows(
    all_fills: Iterable[dict],
    auction_start_epoch: int,
    auction_end_epoch: int,
) -> list[tuple[int, int]]:
    """Fallback spike-window source for Spike Trader detection when no
    post_count series is available. Bins fills into 1-hour buckets, computes
    median price per bucket, then flags hours where median Δprice crosses the
    top-decile threshold. Returns ±2hr windows around each flagged hour."""
    fills = list(all_fills)
    if not fills or auction_end_epoch <= auction_start_epoch:
        return []
    duration_hours = max(1, int((auction_end_epoch - auction_start_epoch) / 3600))
    bins: dict[int, list[float]] = defaultdict(list)
    for f in fills:
        ts = f.get("timestamp", 0)
        if ts < auction_start_epoch or ts > auction_end_epoch:
            continue
        h = int((ts - auction_start_epoch) / 3600)
        bins[h].append(float(f.get("price", 0) or 0))
    if len(bins) < 3:
        return []
    medians = [(h, median(p)) for h, p in sorted(bins.items())]
    deltas = []
    for i in range(1, len(medians)):
        prev_h, prev_p = medians[i - 1]
        h, p = medians[i]
        deltas.append((h, abs(p - prev_p)))
    if not deltas:
        return []
    sorted_delta_vals = sorted(d for _, d in deltas)
    cutoff_idx = int(len(sorted_delta_vals) * 0.9)
    cutoff = sorted_delta_vals[cutoff_idx] if sorted_delta_vals else 0.0
    if cutoff <= 0:
        return []
    windows = []
    for h, d in deltas:
        if d >= cutoff:
            center = auction_start_epoch + h * 3600
            windows.append((center - 2 * 3600, center + 2 * 3600))
    return windows
