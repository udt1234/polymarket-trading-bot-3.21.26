# Backtest Results — 2026-04-07

## FINAL WINNERS

### Trump: Kelly 0.25x + Late entry (75%) — No signals
- **ROI: +184.6%** | Win rate: 64.7% | Max loss: -$10 | Avg P&L: $18.46/auction
- Across 17 completed auctions (Jan 16 — Mar 31, 2026)

### Elon: Kelly 0.25x + 65% entry + SL30 + Regime + Hawkes
- **ROI: +41.8%** | Win rate: 58.0% | Max loss: -$10 | Avg P&L: $4.18/auction
- Across 81 completed auctions (Nov 21, 2025 — Apr 3, 2026)

### Equal-weight alternatives (higher absolute $ per auction)
- **Trump:** Equal + Late + SL40 → +46.8% ROI, $46.75/auction, -$80 max loss
- **Elon:** Equal + 65% + SL30 + Regime + Hawkes → +14.3% ROI, $14.26/auction

## Tests Run (chronological)

| # | Test | Key Finding |
|---|------|-------------|
| 1 | Basis cover (sell at 2x) | Kills upside, only covers basis 5/17 Trump, 8/81 Elon |
| 2 | Entry timing | Later = better. Trump +37% late vs +10% early |
| 3 | Stop-loss | 30% SL nearly doubles Trump ROI, flips Elon to breakeven |
| 4 | High-odds hedge | Never triggers — condition too strict |
| 5 | Late + SL combos | Trump: Late+SL40 = +46.8%. Elon: 65%+SL30 = +12.3% |
| 6 | Kelly criterion | Trump: +184.6% ROI. Elon: +29.8% ROI. Max loss -$10 |
| 7 | Price-based (MR/momentum) | No improvement on Kelly strategies |
| 8 | Signal modifier (crude) | Hurts — double-counts pacing data |
| 9 | Kelly fraction sweep | 0.15x through 1.0x identical (engine normalizes) |
| 10 | Signal stack (regime/DOW/hawkes/vol) | DOW kills performance. Regime+Hawkes helps Elon +12% |

## Signal Stack Detail (Test 10)

### Trump: signals hurt or do nothing
No signals remains best at 184.6% ROI.

### Elon: Regime + Hawkes = +41.8% (up from 29.8%)
| Signal Combo | ROI | vs Baseline |
|-------------|-----|-------------|
| Regime + Hawkes | **+41.8%** | **+12.0%** |
| Hawkes only | +39.8% | +10.0% |
| Regime only | +33.0% | +3.2% |
| No signals | +29.8% | — |
| DOW only | -13.6% | -43.4% |

## Posting Pattern Insights
- **Trump Sundays:** 33% of bottom-10% days. Reliable low-post predictor.
- **Trump spikes:** Market crashes, military threats → 3-8x post surges.
- **Elon bursts:** Multi-day clusters (Dec 4-8: 348-558/day). Controversy-driven.
- **DOW signal is poison** in backtesting — too blunt for auction-level decisions.
