# Crypto hourly Up/Down "last-seconds sweep" — backtest findings (2026-07-08)

Backtest-first evaluation of Sir's idea: in the final seconds of BTC/ETH/SOL/XRP
hourly Up-or-Down markets, buy the near-certain winner (>97%) to scalp 0.97→1.00.
Data: Gamma (400 resolved hourly markets, Jul 4-8) + pmxt tick L2 (96 markets, 24h).

## Verdict: do NOT build it live. Edge is thin, rare, fragile, adversely selected.

### Phase 1 — is the late favorite mispriced? (1-min bars, n=400)
- TAKER (lift the favorite at market price, ≥0.97): +$0.37/$100 at T-60s, **-$0.17/$100 at T-180s**. Efficient / dead. Confirms the KOL negative result + our efficient-market thesis.
- The favorite that dips to ≤0.98 in the FINAL MINUTE still won 100% (noise), but that same dip 3 min out LOSES (real flips). The edge, if any, lives only in the final ~60s. Sir's "last 3 seconds" instinct was directionally right.

### Phase 2 — real maker-fill sim on tick L2 (n=96, 24h, GENEROUS fills)
- **70% of markets have ZERO favorite-trades in the final 30s** — most of the time there is simply no seller to fill against near the close. Flow late = buying the winner UP to 0.999, not dumping it.
- Fill rate (rest a post-only bid, generous = any print ≤ bid):
  - bid 0.97: 1.1% (10s) / 5.7% (30s) / 10.6% (60s)
  - bid 0.99: 6.7% / 13.6% / 17.6%
- Win rate on fills: 100% in this window — BUT on 1-15 fills/cell, in-sample, one 4-day stretch. Not trustworthy as a win rate.
- EV/fill: +0.01 (bid 0.99) to +0.03 (bid 0.97). Expected profit ≈ **$0.20-0.32 per market at $100/bid**, generously.

### Why it fails the bar
1. **Rare fills:** you need a panic seller dumping a near-certain winner; that almost never happens (70% no late trades). Generous fills ignore queue position; real fills are LOWER — we sit behind co-located bots at 0.99 in the FIFO queue.
2. **Fat-tail ruin:** one late flip (a 0.97 fill that loses) = -0.97, erasing ~32 wins. The "100% win" is small-n; the strategy is one adverse fill from negative.
3. **Adverse selection by construction:** the rare seller dumping to you in the final seconds sometimes knows the candle is turning. This is the #1 maker risk our whole design warns about.
4. **Build cost vs payout:** needs a new crypto ingestion stack (spot feed + resolution clock) for ~cents/market with fat-tail downside.

### Reframe (what to do instead)
- Bank the one robust finding: final-60s dips on the near-certain winner are almost always noise that recovers.
- Higher-EV redirect: the PARKED cross-market reconstruction idea — player-prop / thin markets showed reversion +0.22 to +0.28 vs the ~0.01-0.03 here (≈10x the edge). That is where to point the effort.

Scripts: `phase1_efficiency.py`, `phase2_maker_fills.py` (durable, re-runnable; `phase2 N` = last N hours).
