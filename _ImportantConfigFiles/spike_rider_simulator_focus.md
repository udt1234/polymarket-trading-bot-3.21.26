# Spike Rider — Sell Rule Simulator Report

Generated: 2026-05-04T21:54:32.181833+00:00

## Parameters
- Module: `elon`
- Universe: focus brackets ['<40', '40-59', '160-179'] (16 auction-bracket pairs)
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
| multi_stage_2x_3x_5x | 13 | 62% | $+396.02 | +304.6% | +155.6% | +2007.0% | -42.0% | 27.8% |
| target_2x | 16 | 81% | $+353.89 | +221.2% | +97.0% | +2007.0% | -100.9% | -107.5% |
| target_3x | 16 | 50% | $+351.10 | +219.4% | +29.4% | +2007.0% | -101.6% | -152.4% |
| time_50pct_elapsed | 16 | 50% | $+19.60 | +12.3% | -4.1% | +145.5% | -87.5% | -56.7% |
| trailing_stop_30_min50 | 16 | 44% | $+61.69 | +38.6% | -7.7% | +620.0% | -100.9% | -151.5% |
| trailing_stop_25_min30 | 16 | 38% | $+41.45 | +25.9% | -18.2% | +620.0% | -100.9% | -159.8% |
| time_33pct_elapsed | 16 | 25% | $+6.80 | +4.3% | -20.6% | +297.0% | -49.5% | -37.2% |
| trailing_stop_40_min100 | 16 | 44% | $+35.95 | +22.5% | -22.7% | +620.0% | -101.4% | -157.4% |
| target_5x | 16 | 44% | $+393.65 | +246.0% | -98.6% | +2007.0% | -101.6% | -148.6% |
| buy_and_hold | 16 | 6% | $-134.80 | -84.2% | -100.5% | +155.6% | -101.6% | -186.8% |

## Winner: `multi_stage_2x_3x_5x`

- Total P&L: $+396.02 across 13 simulated trades
- Average return: +304.6%
- Median return: +155.6%
- Captured 27.8% of peak P&L on average

## Notes
- Buy-and-hold is included as the baseline rule (no sell trigger; exits at last snapshot).
- `%-of-peak captured` is realized_pnl / pnl-if-sold-at-peak, only counted when peak P&L > 0.
- Slippage and fees are applied on both legs; results are net.
- Equal weighting per (auction, bracket) — no position-sizing logic here.