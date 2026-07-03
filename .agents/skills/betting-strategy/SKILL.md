---
name: betting-strategy
description: Load when working on position sizing, Kelly Criterion, risk management, ensemble weights, regime detection, or signal modifier logic. Triggers on files in api/modules/*/signals.py, api/modules/*/projection.py, api/services/risk_manager.py.
---

You have deep knowledge of prediction market betting strategy.

## Core Rules (NON-NEGOTIABLE)
- **Kelly Criterion** is the default sizing method — fractional Kelly at 0.25x
- **Max position size**: 15% of portfolio per bracket
- **Portfolio exposure cap**: 50% total
- **Minimum edge threshold**: 2% before placing any order
- **ALL orders are limit orders** — NEVER market orders
- **Settlement decay**: Reduce position size as auction approaches end

## Ensemble Weights (5 models)
```
Early (<25%):  pace=low, bayesian=high, dow=med, historical=high, hawkes=regime
Mid (25-75%):  pace=med, bayesian=high, dow=med, historical=low, hawkes=regime
Late (>75%):   pace=high, bayesian=med, dow=low, historical=min, hawkes=regime
Hawkes: 15% in SURGE/HIGH regimes, 8% in NORMAL/LOW
Calibration: +/-20% based on per-model Brier scores
```

## Kelly Fraction by Regime
| Condition | Kelly Fraction |
|-----------|---------------|
| Default | 0.25 |
| Volatility > 1.0 | 0.20 |
| Volatility > 1.5 | 0.15 |
| TRANSITION regime | 0.10 |

## Risk Checks (all 15 must pass before any order)
Circuit breaker, edge (2%), Kelly validation, position cap (15%), daily loss (5%),
weekly loss (10%), drawdown (15%), portfolio (50%), single market (15%),
correlated (30%), duplicate, cross-module, settlement decay, spread, liquidity

See references/risk-rules.md for detailed check logic.
