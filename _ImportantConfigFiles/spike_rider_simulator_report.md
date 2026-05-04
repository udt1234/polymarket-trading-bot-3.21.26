# Spike Rider — Sell Rule Simulator Report

Generated: 2026-05-04T21:47:23.378574+00:00

## Parameters
- Module: `elon`
- Universe: all (auction, bracket) pairs with 3+ snapshots (211 auction-bracket pairs)
- Entry size: $10.00 per trade
- Fee: 2.0% per leg
- Slippage: 5.0% per leg
- Bracket filter: all
- Entry price band: [0.02, 0.40]

## Entry rule
Buy at the first snapshot of every (auction, bracket) where price is between 0 and 1.

## Results

| Rule | Trades | Win % | Total P&L | Avg return | Median return | Max return | Min return | Avg %-of-peak captured |
|------|-------:|------:|----------:|-----------:|--------------:|-----------:|-----------:|-----------------------:|
| multi_stage_2x_3x_5x | 109 | 78% | $+2,575.16 | +236.3% | +155.6% | +2007.0% | -42.6% | 39.0% |
| target_2x | 211 | 52% | $+1,348.22 | +63.9% | +75.3% | +2007.0% | -101.9% | -235.9% |
| trailing_stop_25_min30 | 211 | 35% | $+42.36 | +2.0% | -18.5% | +817.0% | -101.9% | -209.3% |
| time_33pct_elapsed | 211 | 31% | $-281.98 | -13.4% | -27.2% | +367.9% | -100.2% | -79.5% |
| trailing_stop_30_min50 | 211 | 35% | $+184.75 | +8.8% | -27.9% | +2293.2% | -101.9% | -238.8% |
| time_50pct_elapsed | 211 | 33% | $-297.91 | -14.1% | -40.6% | +510.3% | -101.2% | -141.1% |
| trailing_stop_40_min100 | 211 | 35% | $+165.89 | +7.9% | -99.8% | +2293.2% | -101.9% | -263.1% |
| target_3x | 211 | 40% | $+1,610.77 | +76.3% | -100.6% | +2007.0% | -101.9% | -251.0% |
| target_5x | 211 | 29% | $+1,669.82 | +79.1% | -101.1% | +2007.0% | -101.9% | -263.3% |
| buy_and_hold | 211 | 13% | $-434.68 | -20.6% | -101.3% | +2293.2% | -101.9% | -283.2% |

## Winner: `multi_stage_2x_3x_5x`

- Total P&L: $+2,575.16 across 109 simulated trades
- Average return: +236.3%
- Median return: +155.6%
- Captured 39.0% of peak P&L on average

## Notes
- Buy-and-hold is included as the baseline rule (no sell trigger; exits at last snapshot).
- `%-of-peak captured` is realized_pnl / pnl-if-sold-at-peak, only counted when peak P&L > 0.
- Slippage and fees are applied on both legs; results are net.
- Equal weighting per (auction, bracket) — no position-sizing logic here.