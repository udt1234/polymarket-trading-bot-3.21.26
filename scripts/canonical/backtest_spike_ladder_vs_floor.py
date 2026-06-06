"""
Backtest: Spike 5-tier ladder (0.3/0.5/2/5/12 cents) vs Single 12 cents floor
on 2-day Elon <40 bracket auctions.

UNIVERSE
  canonical/auctions/elonmusk/*.parquet
    duration_type = '2-day'
    confidence in ('high','medium')
    has a '<40' (or smallest) bracket present

STRATEGIES
  A. SINGLE 12c FLOOR:
       limit BUY at 0.12 on the smallest bracket, $100 capital
       fills if hourly LOW for that bracket touched 0.12
       hold to resolution
  B. SPIKE 5-TIER LADDER:
       limit BUYs at 0.003, 0.005, 0.02, 0.05, 0.12 on the smallest bracket
       $20 capital per tier
       each tier fills independently if hourly LOW touched that price
       hold all filled shares to resolution

P&L
  shares_filled = capital_used / fill_price
  payout = shares_filled * $1 if bracket resolves YES else $0
  per-auction ROI = (payout - capital_used) / capital_used  (NaN if nothing filled)

OUTPUT
  Per-auction CSV + Google Sheet tab Backtest_Spike_Ladder
  Summary stats in script stdout
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "_DataMetricPulls" / "canonical"
OUT_CSV = CANON / "_backtests" / "spike_ladder_vs_floor.csv"

LADDER_TIERS_CENTS = [0.3, 0.5, 2.0, 5.0, 12.0]   # cents
SINGLE_FLOOR_CENT = 12.0
CAPITAL_PER_AUCTION = 100.0


def smallest_bracket(all_buckets: str) -> str:
    """Return the lowest-numbered bracket from an auction's bracket list."""
    candidates = [b.strip() for b in all_buckets.split(",")]
    # Prefer literal '<40' or '<N' if present
    for c in candidates:
        if c.startswith("<"):
            return c
    # Otherwise pick the lowest numeric range
    def _low(b: str) -> float:
        try:
            return float(b.split("-")[0].replace("+", "").strip())
        except Exception:
            return 1e9
    if not candidates:
        return ""
    return min(candidates, key=_low)


def load_auctions() -> pd.DataFrame:
    files = sorted((CANON / "auctions/elonmusk").glob("*.parquet"))
    df = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
    df = df[df["duration_type"] == "2-day"]
    df = df[df["confidence"].isin(["high", "medium"])]
    df = df[df["winning_bucket"].notna() & (df["winning_bucket"] != "")]
    return df.reset_index(drop=True)


def load_prices_for(auction_slug: str) -> pd.DataFrame:
    """Load hourly prices for one auction across all months."""
    files = sorted((CANON / "prices/elonmusk").glob("*.parquet"))
    chunks = []
    for p in files:
        df = pd.read_parquet(p, columns=["auction_slug", "bucket", "hour_utc", "low"])
        sub = df[df["auction_slug"] == auction_slug]
        if len(sub):
            chunks.append(sub)
    if not chunks:
        return pd.DataFrame()
    return pd.concat(chunks, ignore_index=True)


def simulate_floor(prices_for_bracket: pd.DataFrame, floor_cents: float, capital: float) -> tuple[bool, float, float]:
    """Returns (filled, fill_price, shares)."""
    floor = floor_cents / 100.0
    # filled if ANY hourly low touched the floor price
    if prices_for_bracket["low"].min() <= floor:
        shares = capital / floor
        return (True, floor, shares)
    return (False, 0.0, 0.0)


def simulate_ladder(prices_for_bracket: pd.DataFrame, tiers_cents: list[float], capital_per_tier: float) -> dict:
    """Returns dict per tier: filled, fill_price, shares."""
    results = {}
    min_low = prices_for_bracket["low"].min() if len(prices_for_bracket) else 1.0
    for tier_c in tiers_cents:
        tier_price = tier_c / 100.0
        if min_low <= tier_price:
            shares = capital_per_tier / tier_price
            results[tier_c] = {"filled": True, "fill_price": tier_price, "shares": shares, "capital": capital_per_tier}
        else:
            results[tier_c] = {"filled": False, "fill_price": 0.0, "shares": 0.0, "capital": 0.0}
    return results


def backtest():
    auctions = load_auctions()
    print(f"[backtest] universe: {len(auctions)} 2-day Elon auctions (conf high/medium, resolved)")

    rows = []
    for _, a in auctions.iterrows():
        slug = a["auction_slug"]
        sb = smallest_bracket(a["all_buckets"])
        if not sb:
            continue
        winner = a["winning_bucket"]
        bracket_wins = (winner == sb)

        # load hourly prices for the smallest bracket only
        all_prices = load_prices_for(slug)
        sb_prices = all_prices[all_prices["bucket"] == sb] if len(all_prices) else pd.DataFrame()
        if len(sb_prices) == 0:
            # no price data for this bracket - skip
            continue

        # Strategy A: single floor
        a_filled, a_fp, a_shares = simulate_floor(sb_prices, SINGLE_FLOOR_CENT, CAPITAL_PER_AUCTION)
        a_capital = CAPITAL_PER_AUCTION if a_filled else 0.0
        a_payout = a_shares if bracket_wins else 0.0  # $1/share if wins
        a_roi = ((a_payout - a_capital) / a_capital) if a_capital else None

        # Strategy B: ladder
        capital_per_tier = CAPITAL_PER_AUCTION / len(LADDER_TIERS_CENTS)
        b_result = simulate_ladder(sb_prices, LADDER_TIERS_CENTS, capital_per_tier)
        b_capital = sum(r["capital"] for r in b_result.values())
        b_shares = sum(r["shares"] for r in b_result.values())
        b_payout = b_shares if bracket_wins else 0.0
        b_roi = ((b_payout - b_capital) / b_capital) if b_capital else None

        # tier-fill flags for transparency
        tier_fills = {f"tier_{int(c*10)}": int(b_result[c]["filled"]) for c in LADDER_TIERS_CENTS}

        rows.append({
            "auction_slug": slug,
            "start_et": str(a["start_et"]),
            "winning_bucket": winner,
            "tested_bracket": sb,
            "bracket_wins": bracket_wins,
            "min_low_observed": float(sb_prices["low"].min()),
            # Strategy A
            "A_filled": a_filled,
            "A_capital": a_capital,
            "A_shares": round(a_shares, 2),
            "A_payout": round(a_payout, 2),
            "A_pnl": round(a_payout - a_capital, 2),
            "A_roi": round(a_roi, 4) if a_roi is not None else None,
            # Strategy B
            "B_capital": round(b_capital, 2),
            "B_shares": round(b_shares, 2),
            "B_payout": round(b_payout, 2),
            "B_pnl": round(b_payout - b_capital, 2),
            "B_roi": round(b_roi, 4) if b_roi is not None else None,
            **tier_fills,
        })

    df = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"[backtest] wrote {len(df)} rows -> {OUT_CSV.relative_to(ROOT)}")
    print()

    # Summary
    print("=" * 70)
    print("STRATEGY A — Single 12¢ Floor")
    print("=" * 70)
    a_filled = df[df["A_filled"] == True]
    print(f"  Auctions tested: {len(df)}")
    print(f"  Auctions filled: {len(a_filled)} ({100*len(a_filled)/len(df):.1f}%)")
    if len(a_filled):
        print(f"  Win rate (filled & bracket won): {100 * (a_filled['bracket_wins']).sum() / len(a_filled):.1f}%")
        print(f"  Total capital deployed: ${a_filled['A_capital'].sum():,.0f}")
        print(f"  Total payout:           ${a_filled['A_payout'].sum():,.2f}")
        print(f"  Total P&L:              ${a_filled['A_pnl'].sum():,.2f}")
        roi_total = a_filled['A_pnl'].sum() / a_filled['A_capital'].sum()
        print(f"  Capital-weighted ROI:   {100*roi_total:.2f}%")
        print(f"  Mean per-auction ROI:   {100*a_filled['A_roi'].mean():.2f}%")
        print(f"  Median per-auction ROI: {100*a_filled['A_roi'].median():.2f}%")

    print()
    print("=" * 70)
    print(f"STRATEGY B — Spike Ladder {LADDER_TIERS_CENTS} cents (${CAPITAL_PER_AUCTION / len(LADDER_TIERS_CENTS):.0f}/tier)")
    print("=" * 70)
    b_active = df[df["B_capital"] > 0]
    print(f"  Auctions tested: {len(df)}")
    print(f"  Auctions w/ any tier filled: {len(b_active)} ({100*len(b_active)/len(df):.1f}%)")
    if len(b_active):
        print(f"  Win rate (any fill & bracket won): {100 * (b_active['bracket_wins']).sum() / len(b_active):.1f}%")
        print(f"  Total capital deployed: ${b_active['B_capital'].sum():,.0f}")
        print(f"  Total payout:           ${b_active['B_payout'].sum():,.2f}")
        print(f"  Total P&L:              ${b_active['B_pnl'].sum():,.2f}")
        roi_total = b_active['B_pnl'].sum() / b_active['B_capital'].sum()
        print(f"  Capital-weighted ROI:   {100*roi_total:.2f}%")
        print(f"  Mean per-auction ROI:   {100*b_active['B_roi'].mean():.2f}%")
        print(f"  Median per-auction ROI: {100*b_active['B_roi'].median():.2f}%")
        print()
        print("  Tier hit rates:")
        for c in LADDER_TIERS_CENTS:
            key = f"tier_{int(c*10)}"
            hits = df[key].sum()
            print(f"    {c:>5.1f}¢: {hits}/{len(df)} ({100*hits/len(df):.1f}%)")

    print()
    print("=" * 70)
    print("HEAD-TO-HEAD")
    print("=" * 70)
    print(f"  Total capital A: ${df['A_capital'].sum():,.0f}, B: ${df['B_capital'].sum():,.0f}")
    print(f"  Total P&L     A: ${df['A_pnl'].sum():,.2f}, B: ${df['B_pnl'].sum():,.2f}")
    a_roi = df['A_pnl'].sum() / df['A_capital'].sum() if df['A_capital'].sum() else 0
    b_roi = df['B_pnl'].sum() / df['B_capital'].sum() if df['B_capital'].sum() else 0
    print(f"  Capital-weighted ROI: A {100*a_roi:+.2f}%, B {100*b_roi:+.2f}%")
    winner = "B (ladder)" if b_roi > a_roi else "A (floor)"
    print(f"  Winner: {winner} (ROI delta: {100*(b_roi-a_roi):+.2f} pp)")
    return df


if __name__ == "__main__":
    df = backtest()
    sys.exit(0)
