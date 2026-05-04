"""Sell-rule simulator for the Spike Rider strategy.

Replays historical price_snapshots through different sell rules and reports
realized P&L per rule. Pure offline math — no orders are placed.

Usage:
  python scripts/simulate_sell_rules.py --module elon
  python scripts/simulate_sell_rules.py --module elon --bracket "<40"
  python scripts/simulate_sell_rules.py --module elon --entry-size 10 --fee 0.02 --slippage 0.05
  python scripts/simulate_sell_rules.py --module elon --output _ImportantConfigFiles/spike_rider_simulator_report.md

Requires SUPABASE_URL + SUPABASE_SERVICE_KEY in env (same pattern as backfill_prices.py).
"""
import argparse
import os
import sys
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from supabase import create_client

ELON_MODULE_NAME_HINT = "elon"
TRUMP_MODULE_NAME_HINT = "trump"

# Brackets your prior analysis flagged as best
ELON_FOCUS_BRACKETS = ["<40", "40-59", "160-179"]


@dataclass
class TradeResult:
    auction_key: str  # tracking_id or fallback
    bracket: str
    entry_price: float
    entry_time: datetime
    exit_price: float
    exit_time: datetime
    peak_price: float
    rule: str
    notional: float
    realized_pnl: float
    return_pct: float
    held_hours: float


@dataclass
class RuleSummary:
    rule: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    returns: list[float] = field(default_factory=list)
    captured_of_max: list[float] = field(default_factory=list)


def get_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY (or SUPABASE_KEY) required in env",
              file=sys.stderr)
        sys.exit(1)
    return create_client(url, key)


def find_module_id(sb, hint: str) -> tuple[str, str]:
    """Return (module_id, module_name) for the first module whose name matches hint."""
    res = sb.table("modules").select("id,name").execute()
    for row in res.data or []:
        if hint.lower() in (row.get("name") or "").lower():
            return row["id"], row["name"]
    print(f"ERROR: no module found matching '{hint}'", file=sys.stderr)
    sys.exit(1)


def fetch_snapshots(sb, module_id: str, bracket_filter: str | None) -> list[dict]:
    """Fetch all price_snapshots for a module, paginated. Returns rows sorted by snapshot_hour asc."""
    all_rows: list[dict] = []
    page = 0
    page_size = 1000
    while True:
        q = (
            sb.table("price_snapshots")
            .select("bracket,price,snapshot_hour,tracking_id,elapsed_days")
            .eq("module_id", module_id)
            .order("snapshot_hour")
            .range(page * page_size, (page + 1) * page_size - 1)
        )
        if bracket_filter:
            q = q.eq("bracket", bracket_filter)
        res = q.execute()
        rows = res.data or []
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        page += 1
    return all_rows


def group_by_auction_bracket(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """Group snapshots by (tracking_id, bracket). Falls back to a date-bucket if tracking_id is missing."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        bracket = r.get("bracket") or ""
        tid = r.get("tracking_id") or ""
        if not tid:
            # Fallback: bucket by start week of snapshot. Imperfect but keeps orphan rows usable.
            try:
                ts = datetime.fromisoformat((r.get("snapshot_hour") or "").replace("Z", "+00:00"))
                tid = f"week-{ts.strftime('%Y-W%W')}"
            except Exception:
                tid = "unknown"
        groups[(tid, bracket)].append(r)
    for key in groups:
        groups[key].sort(key=lambda x: x.get("snapshot_hour") or "")
    return groups


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# --- Sell rules -----------------------------------------------------------

def rule_trailing_stop(series: list[dict], trail_pct: float, min_gain_pct: float) -> int | None:
    """Return index where we sell. Sell when price drops trail_pct off peak,
    only after we've been up min_gain_pct from entry. None = hold to last."""
    if not series:
        return None
    entry = series[0]["price"]
    if entry <= 0:
        return None
    peak = entry
    armed = False
    for i, snap in enumerate(series[1:], start=1):
        p = snap["price"]
        if p > peak:
            peak = p
        if not armed and peak >= entry * (1 + min_gain_pct):
            armed = True
        if armed and p <= peak * (1 - trail_pct):
            return i
    return None


def rule_target_multiplier(series: list[dict], multiplier: float) -> int | None:
    if not series:
        return None
    entry = series[0]["price"]
    if entry <= 0:
        return None
    target = entry * multiplier
    for i, snap in enumerate(series[1:], start=1):
        if snap["price"] >= target:
            return i
    return None


def rule_time_based(series: list[dict], elapsed_frac: float) -> int | None:
    if not series:
        return None
    n = len(series)
    idx = int(n * elapsed_frac)
    if 0 < idx < n:
        return idx
    return None


def rule_multi_stage(series: list[dict], targets: list[float]) -> list[tuple[int, float]]:
    """Multi-stage exit: returns list of (index, fraction_to_sell). Each target multiplier
    triggers selling 1/N of original position. Remaining position rides to last snapshot."""
    if not series:
        return []
    entry = series[0]["price"]
    if entry <= 0:
        return []
    n_stages = len(targets)
    fraction = 1.0 / n_stages
    triggered = [False] * n_stages
    plan: list[tuple[int, float]] = []
    for i, snap in enumerate(series[1:], start=1):
        p = snap["price"]
        for j, mult in enumerate(targets):
            if not triggered[j] and p >= entry * mult:
                triggered[j] = True
                plan.append((i, fraction))
    return plan


# --- Simulator -----------------------------------------------------------

def simulate(
    groups: dict[tuple[str, str], list[dict]],
    rule_name: str,
    rule_fn,
    entry_size: float,
    fee_pct: float,
    slippage_pct: float,
    bracket_filter: list[str] | None = None,
    entry_min: float = 0.02,
    entry_max: float = 0.40,
) -> tuple[list[TradeResult], RuleSummary]:
    summary = RuleSummary(rule=rule_name)
    results: list[TradeResult] = []

    for (tid, bracket), series in groups.items():
        if bracket_filter and bracket not in bracket_filter:
            continue
        if len(series) < 3:
            continue
        first = series[0]
        entry_raw = first.get("price", 0) or 0
        if entry_raw < entry_min or entry_raw > entry_max:
            continue
        # Entry includes slippage adverse to buyer (pay a bit more)
        entry_price = entry_raw * (1 + slippage_pct)
        entry_time = parse_ts(first["snapshot_hour"])
        peak_price = max(s.get("price", 0) for s in series)

        if rule_name.startswith("multi_stage"):
            plan = rule_fn(series)
            if not plan:
                continue
            # Aggregate across tranches into a single weighted result
            total_realized = 0.0
            shares_total = entry_size / entry_price if entry_price > 0 else 0
            shares_remaining = shares_total
            last_idx = 0
            for idx, frac in plan:
                exit_raw = series[idx].get("price", 0) or 0
                exit_price = exit_raw * (1 - slippage_pct)
                shares_sold = shares_total * frac
                proceeds = shares_sold * exit_price * (1 - fee_pct)
                total_realized += proceeds
                shares_remaining -= shares_sold
                last_idx = idx
            # Tail: ride remainder to final snapshot
            final_raw = series[-1].get("price", 0) or 0
            final_price = final_raw * (1 - slippage_pct)
            total_realized += shares_remaining * final_price * (1 - fee_pct)
            cost = entry_size * (1 + fee_pct)
            realized_pnl = total_realized - cost
            return_pct = realized_pnl / entry_size if entry_size > 0 else 0
            exit_idx = last_idx
            exit_time = parse_ts(series[exit_idx]["snapshot_hour"])
            exit_price_avg = (total_realized / shares_total) if shares_total > 0 else final_price
            held_h = (exit_time - entry_time).total_seconds() / 3600
            results.append(TradeResult(
                auction_key=tid, bracket=bracket, entry_price=entry_price,
                entry_time=entry_time, exit_price=exit_price_avg, exit_time=exit_time,
                peak_price=peak_price, rule=rule_name, notional=entry_size,
                realized_pnl=realized_pnl, return_pct=return_pct, held_hours=held_h,
            ))
        else:
            exit_idx = rule_fn(series)
            if exit_idx is None:
                # Hold to last snapshot
                exit_idx = len(series) - 1
            exit_raw = series[exit_idx].get("price", 0) or 0
            exit_price = exit_raw * (1 - slippage_pct)
            exit_time = parse_ts(series[exit_idx]["snapshot_hour"])
            shares = entry_size / entry_price if entry_price > 0 else 0
            cost = entry_size * (1 + fee_pct)
            proceeds = shares * exit_price * (1 - fee_pct)
            realized_pnl = proceeds - cost
            return_pct = realized_pnl / entry_size if entry_size > 0 else 0
            held_h = (exit_time - entry_time).total_seconds() / 3600
            results.append(TradeResult(
                auction_key=tid, bracket=bracket, entry_price=entry_price,
                entry_time=entry_time, exit_price=exit_price, exit_time=exit_time,
                peak_price=peak_price, rule=rule_name, notional=entry_size,
                realized_pnl=realized_pnl, return_pct=return_pct, held_hours=held_h,
            ))

        # Theoretical max if you sold at peak
        peak_proceeds = (entry_size / entry_price) * (peak_price * (1 - slippage_pct)) * (1 - fee_pct)
        max_pnl = peak_proceeds - entry_size * (1 + fee_pct)
        if max_pnl > 0:
            summary.captured_of_max.append(results[-1].realized_pnl / max_pnl)

    for r in results:
        summary.trades += 1
        summary.total_pnl += r.realized_pnl
        summary.returns.append(r.return_pct)
        if r.realized_pnl > 0:
            summary.wins += 1
        else:
            summary.losses += 1

    return results, summary


def median(xs: list[float]) -> float:
    return statistics.median(xs) if xs else 0.0


def fmt_pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def write_report(
    output_path: Path,
    summaries: list[RuleSummary],
    args,
    universe_label: str,
    bracket_universe_size: int,
):
    lines = []
    lines.append("# Spike Rider — Sell Rule Simulator Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    lines.append("## Parameters")
    lines.append(f"- Module: `{args.module}`")
    lines.append(f"- Universe: {universe_label} ({bracket_universe_size} auction-bracket pairs)")
    lines.append(f"- Entry size: ${args.entry_size:.2f} per trade")
    lines.append(f"- Fee: {args.fee * 100:.1f}% per leg")
    lines.append(f"- Slippage: {args.slippage * 100:.1f}% per leg")
    lines.append(f"- Bracket filter: {args.bracket or 'all'}")
    lines.append(f"- Entry price band: [{args.entry_min:.2f}, {args.entry_max:.2f}]")
    lines.append("")
    lines.append("## Entry rule")
    lines.append("Buy at the first snapshot of every (auction, bracket) where price is between 0 and 1.")
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append("| Rule | Trades | Win % | Total P&L | Avg return | Median return | Max return | Min return | Avg %-of-peak captured |")
    lines.append("|------|-------:|------:|----------:|-----------:|--------------:|-----------:|-----------:|-----------------------:|")
    # Rank by median return — robust to a single dust-priced bracket producing outsize returns.
    ranked = sorted(summaries, key=lambda s: median(s.returns), reverse=True)
    for s in ranked:
        win_pct = (s.wins / s.trades * 100) if s.trades else 0
        avg_ret = (sum(s.returns) / len(s.returns)) if s.returns else 0
        med_ret = median(s.returns)
        max_ret = max(s.returns) if s.returns else 0
        min_ret = min(s.returns) if s.returns else 0
        avg_capture = (sum(s.captured_of_max) / len(s.captured_of_max)) if s.captured_of_max else 0
        lines.append(
            f"| {s.rule} | {s.trades} | {win_pct:.0f}% | ${s.total_pnl:+,.2f} | "
            f"{fmt_pct(avg_ret)} | {fmt_pct(med_ret)} | {fmt_pct(max_ret)} | {fmt_pct(min_ret)} | "
            f"{avg_capture * 100:.1f}% |"
        )
    lines.append("")
    if ranked:
        winner = ranked[0]
        lines.append(f"## Winner: `{winner.rule}`")
        lines.append("")
        lines.append(f"- Total P&L: ${winner.total_pnl:+,.2f} across {winner.trades} simulated trades")
        if winner.returns:
            lines.append(f"- Average return: {fmt_pct(sum(winner.returns) / len(winner.returns))}")
            lines.append(f"- Median return: {fmt_pct(median(winner.returns))}")
        if winner.captured_of_max:
            lines.append(f"- Captured {sum(winner.captured_of_max) / len(winner.captured_of_max) * 100:.1f}% of peak P&L on average")
        lines.append("")
    lines.append("## Notes")
    lines.append("- Buy-and-hold is included as the baseline rule (no sell trigger; exits at last snapshot).")
    lines.append("- `%-of-peak captured` is realized_pnl / pnl-if-sold-at-peak, only counted when peak P&L > 0.")
    lines.append("- Slippage and fees are applied on both legs; results are net.")
    lines.append("- Equal weighting per (auction, bracket) — no position-sizing logic here.")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote report -> {output_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--module", default="elon", help="module name hint (elon|trump|<id>)")
    parser.add_argument("--bracket", default=None, help="filter to a single bracket label")
    parser.add_argument("--entry-size", type=float, default=10.0, help="dollars per simulated trade")
    parser.add_argument("--fee", type=float, default=0.02, help="fee fraction per leg")
    parser.add_argument("--slippage", type=float, default=0.05, help="slippage fraction per leg")
    parser.add_argument("--output", default="_ImportantConfigFiles/spike_rider_simulator_report.md")
    parser.add_argument("--focus-only", action="store_true",
                        help="restrict to ELON_FOCUS_BRACKETS (<40, 40-59, 160-179)")
    parser.add_argument("--entry-min", type=float, default=0.02,
                        help="minimum entry price (skip dust ticks below this; default 0.02 = 2c)")
    parser.add_argument("--entry-max", type=float, default=0.40,
                        help="maximum entry price (skip already-rich brackets; default 0.40)")
    args = parser.parse_args()

    sb = get_supabase()
    module_id, module_name = find_module_id(sb, args.module)
    print(f"Module: {module_name} ({module_id})")

    rows = fetch_snapshots(sb, module_id, args.bracket)
    print(f"Fetched {len(rows)} snapshots")

    groups = group_by_auction_bracket(rows)
    print(f"Grouped into {len(groups)} (auction, bracket) pairs")

    bracket_filter = None
    universe_label = "all (auction, bracket) pairs with 3+ snapshots"
    if args.focus_only:
        bracket_filter = ELON_FOCUS_BRACKETS
        universe_label = f"focus brackets {ELON_FOCUS_BRACKETS}"

    rules: list[tuple[str, callable]] = [
        ("buy_and_hold", lambda s: None),
        ("trailing_stop_30_min50", lambda s: rule_trailing_stop(s, 0.30, 0.50)),
        ("trailing_stop_25_min30", lambda s: rule_trailing_stop(s, 0.25, 0.30)),
        ("trailing_stop_40_min100", lambda s: rule_trailing_stop(s, 0.40, 1.00)),
        ("target_2x", lambda s: rule_target_multiplier(s, 2.0)),
        ("target_3x", lambda s: rule_target_multiplier(s, 3.0)),
        ("target_5x", lambda s: rule_target_multiplier(s, 5.0)),
        ("time_50pct_elapsed", lambda s: rule_time_based(s, 0.50)),
        ("time_33pct_elapsed", lambda s: rule_time_based(s, 0.33)),
        ("multi_stage_2x_3x_5x", lambda s: rule_multi_stage(s, [2.0, 3.0, 5.0])),
    ]

    summaries: list[RuleSummary] = []
    matched = 0
    for name, fn in rules:
        _, summary = simulate(
            groups, name, fn, args.entry_size, args.fee, args.slippage, bracket_filter,
            entry_min=args.entry_min, entry_max=args.entry_max,
        )
        summaries.append(summary)
        matched = max(matched, summary.trades)
        print(f"  {name}: {summary.trades} trades, P&L ${summary.total_pnl:+,.2f}")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_report(out_path, summaries, args, universe_label, matched)


if __name__ == "__main__":
    main()
