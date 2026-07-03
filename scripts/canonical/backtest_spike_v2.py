"""
Backtest v2 — Spike's REAL strategy on Elon 2-day <40 bracket auctions.

UNIVERSE
  canonical/auctions/elonmusk/*.parquet
    duration_type = '2-day'
    confidence in ('high','medium')
    '<40' bracket present in all_buckets

STRATEGY (mirrors api/modules/spike_trading/strategies/cheap_lottery_pacing.py)
  buy_ladder = [
    {price: 0.03, notional_usd: 3.0, label: deep_discount},
    {price: 0.05, notional_usd: 5.0, label: cheap_normal},
    {price: 0.07, notional_usd: 7.0, label: at_ask},
    {price: 0.10, notional_usd: 5.0, label: pay_up},
    {price: 0.15, notional_usd: 5.0, label: insurance},
  ]  # total $25 per auction

  sell_multipliers = [1.5, 2.0, 4.0, 8.0]
  sell_multiplier_pcts = [0.30, 0.30, 0.20, 0.20]
  # For each tier, after fill, place 4 limit-sell ladders at entry*mult.
  # If the bracket's hourly HIGH ever touches a multiplier price -> fill.
  # Remaining shares (unfilled at all multipliers) hold to resolution.

P&L
  per fill: shares = capital / fill_price
  for each sell_multiplier:
     pct of those shares sold if bracket high ever >= entry * multiplier
     proceeds += sold_shares * sell_price
  remaining shares: if bracket resolves YES -> proceeds += remaining * 1.0
  pnl = proceeds - capital_in

Compare against v1's hold-to-resolution baseline.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "_DataMetricPulls" / "canonical"
OUT_CSV = CANON / "_backtests" / "spike_v2.csv"

# Use canonical loader with QA gating
sys.path.insert(0, str(ROOT))
from api.modules.shared.canonical_data import load_auctions, load_prices

LADDER = [
    {"price": 0.03, "notional_usd": 3.0, "label": "deep_discount"},
    {"price": 0.05, "notional_usd": 5.0, "label": "cheap_normal"},
    {"price": 0.07, "notional_usd": 7.0, "label": "at_ask"},
    {"price": 0.10, "notional_usd": 5.0, "label": "pay_up"},
    {"price": 0.15, "notional_usd": 5.0, "label": "insurance"},
]
SELL_MULTIPLIERS = [1.5, 2.0, 4.0, 8.0]
SELL_MULT_PCTS = [0.30, 0.30, 0.20, 0.20]


def _load_auctions_for_backtest() -> pd.DataFrame:
    """Load via canonical loader — QA gates at 95% pass rate before returning."""
    df = load_auctions(
        handle="elonmusk",
        duration_type="2-day",
        confidence=("high",),
        bracket_must_contain="<40",
        sample_size=10,
        caller="backtest_spike_v2.py",
    )
    df = df[df["winning_bucket"].notna() & (df["winning_bucket"] != "")]
    return df.reset_index(drop=True)


def _load_prices_for_backtest(auction_slug: str) -> pd.DataFrame:
    """Load via canonical loader — QA gates per-auction price slice."""
    df = load_prices(
        handle="elonmusk",
        auction_slug=auction_slug,
        sample_size=3,
        caller="backtest_spike_v2.py",
    )
    return df.sort_values("hour_utc")


def simulate_auction(prices_lt40: pd.DataFrame, bracket_wins: bool) -> dict:
    """
    For one auction's <40 bracket price series:
      walk hour by hour
      check each tier: fills if hourly LOW <= tier.price (and not yet filled)
      after fill, run sell ladder against subsequent hours' HIGH
      remaining shares at end: payout = shares if bracket_wins else 0
    """
    if len(prices_lt40) == 0:
        return {
            "capital_in": 0.0, "proceeds": 0.0, "pnl": 0.0,
            "tier_fills": {t["label"]: 0 for t in LADDER},
            "sell_mult_hits": {f"mult_{m}x": 0 for m in SELL_MULTIPLIERS},
            "n_hours": 0,
        }

    p = prices_lt40.sort_values("hour_utc").reset_index(drop=True)
    # per-tier state
    tier_state = [
        {"price": t["price"], "notional": t["notional_usd"], "label": t["label"],
         "filled": False, "fill_hour": None, "shares_filled": 0.0,
         "shares_remaining": 0.0,
         "sells_done": [False] * len(SELL_MULTIPLIERS),
         "proceeds_from_sells": 0.0}
        for t in LADDER
    ]
    capital_in = 0.0
    proceeds = 0.0

    for i, row in p.iterrows():
        hr_low = float(row["low"])
        hr_high = float(row["high"])
        # 1) try to fill tiers (use low of this hour)
        for ts in tier_state:
            if not ts["filled"] and hr_low <= ts["price"]:
                # fill at tier price (limit order; touched means filled)
                ts["filled"] = True
                ts["fill_hour"] = i
                ts["shares_filled"] = ts["notional"] / ts["price"]
                ts["shares_remaining"] = ts["shares_filled"]
                capital_in += ts["notional"]

        # 2) for filled tiers, check sell-ladder hits using high
        for ts in tier_state:
            if not ts["filled"]:
                continue
            if i <= ts["fill_hour"]:
                continue  # can't sell same hour as fill
            for k, mult in enumerate(SELL_MULTIPLIERS):
                if ts["sells_done"][k]:
                    continue
                sell_price = min(ts["price"] * mult, 0.99)
                if hr_high >= sell_price and ts["shares_remaining"] > 0:
                    sell_shares = ts["shares_filled"] * SELL_MULT_PCTS[k]
                    sell_shares = min(sell_shares, ts["shares_remaining"])
                    ts["proceeds_from_sells"] += sell_shares * sell_price
                    ts["shares_remaining"] -= sell_shares
                    ts["sells_done"][k] = True

    # 3) end-of-auction resolution for remaining shares
    end_payout = 0.0
    for ts in tier_state:
        if ts["shares_remaining"] > 0:
            end_payout += ts["shares_remaining"] * (1.0 if bracket_wins else 0.0)

    proceeds = sum(ts["proceeds_from_sells"] for ts in tier_state) + end_payout
    pnl = proceeds - capital_in

    return {
        "capital_in": capital_in,
        "proceeds": proceeds,
        "pnl": pnl,
        "tier_fills": {ts["label"]: int(ts["filled"]) for ts in tier_state},
        "sell_mult_hits": {
            f"mult_{m}x": int(any(ts["sells_done"][k] for ts in tier_state))
            for k, m in enumerate(SELL_MULTIPLIERS)
        },
        "n_hours": len(p),
    }


def main():
    auctions = _load_auctions_for_backtest()
    print(f"[v2] universe: {len(auctions)} 2-day Elon <40 auctions (resolved, conf high/medium)")

    rows = []
    for _, a in auctions.iterrows():
        slug = a["auction_slug"]
        bracket_wins = (a["winning_bucket"] == "<40")
        prices = _load_prices_for_backtest(slug)
        lt40 = prices[prices["bucket"] == "<40"] if len(prices) else pd.DataFrame()
        if len(lt40) == 0:
            continue
        res = simulate_auction(lt40, bracket_wins)
        roi = (res["pnl"] / res["capital_in"]) if res["capital_in"] else None
        rows.append({
            "auction_slug": slug,
            "start_et": str(a["start_et"]),
            "winning_bucket": a["winning_bucket"],
            "bracket_wins": bracket_wins,
            "min_low": float(lt40["low"].min()),
            "max_high": float(lt40["high"].max()),
            "n_hours": res["n_hours"],
            "capital_in": round(res["capital_in"], 2),
            "proceeds": round(res["proceeds"], 2),
            "pnl": round(res["pnl"], 2),
            "roi": round(roi, 4) if roi is not None else None,
            **{f"fill_{k}": v for k, v in res["tier_fills"].items()},
            **res["sell_mult_hits"],
        })
    df = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"[v2] wrote {len(df)} rows -> {OUT_CSV.relative_to(ROOT)}")
    print()

    # summary
    active = df[df["capital_in"] > 0]
    print("=" * 70)
    print("SPIKE v2 RESULTS (real tiers 3/5/7/10/15c, sell-multiplier ladder)")
    print("=" * 70)
    print(f"  Auctions tested: {len(df)}")
    print(f"  Any tier filled: {len(active)} ({100*len(active)/len(df):.1f}%)")
    print(f"  Bracket-wins when filled: {(active['bracket_wins']).sum()} ({100*(active['bracket_wins']).sum()/max(len(active),1):.1f}%)")
    print(f"  Total capital deployed:  ${active['capital_in'].sum():,.2f}")
    print(f"  Total proceeds:          ${active['proceeds'].sum():,.2f}")
    print(f"  Total P&L:               ${active['pnl'].sum():,.2f}")
    if active['capital_in'].sum() > 0:
        print(f"  Capital-weighted ROI:    {100*active['pnl'].sum()/active['capital_in'].sum():+.2f}%")
    print(f"  Mean per-auction ROI:    {100*active['roi'].mean():+.2f}%")
    print(f"  Median per-auction ROI:  {100*active['roi'].median():+.2f}%")
    print()
    print("  Tier fill rates:")
    for t in LADDER:
        col = f"fill_{t['label']}"
        n = df[col].sum()
        print(f"    {t['price']*100:>5.1f}c {t['label']:<16}: {n}/{len(df)} ({100*n/len(df):.1f}%)")
    print()
    print("  Sell-multiplier hit rates (any tier triggered):")
    for k, m in enumerate(SELL_MULTIPLIERS):
        col = f"mult_{m}x"
        n = df[col].sum()
        print(f"    {m}x ({SELL_MULT_PCTS[k]*100:.0f}% of fill): {n}/{len(df)} ({100*n/len(df):.1f}%)")
    print()
    # vs v1 quick compare
    v1 = ROOT / "_DataMetricPulls" / "canonical" / "_backtests" / "spike_ladder_vs_floor.csv"
    if v1.exists():
        v1df = pd.read_csv(v1)
        v1_pnl = v1df["B_pnl"].sum()
        v1_cap = v1df["B_capital"].sum()
        print("=" * 70)
        print("v1 (hold-to-resolution, 0.3/0.5/2/5/12c) vs v2 (Spike real)")
        print("=" * 70)
        print(f"  v1: ${v1_cap:,.0f} in, P&L ${v1_pnl:+,.0f}, ROI {100*v1_pnl/v1_cap:+.2f}%")
        v2_cap = active['capital_in'].sum()
        v2_pnl = active['pnl'].sum()
        print(f"  v2: ${v2_cap:,.0f} in, P&L ${v2_pnl:+,.0f}, ROI {100*v2_pnl/v2_cap:+.2f}%")
        delta = (v2_pnl/v2_cap if v2_cap else 0) - (v1_pnl/v1_cap if v1_cap else 0)
        print(f"  ROI delta: {100*delta:+.2f} pp")


if __name__ == "__main__":
    main()
