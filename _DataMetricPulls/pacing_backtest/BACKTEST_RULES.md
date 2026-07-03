# Backtest Rules — read before writing or trusting any backtest in this folder

A backtest that secretly uses future data ("look-ahead bias") shows a gorgeous 80%+ win rate and then loses live. It does not throw an error. The better the bug, the better the fake number looks. Every script here must pass these checks.

## The wall (the only rule that matters)
At the exact moment a strategy makes a decision, it may use ONLY data that existed at that moment. Nothing from later. The outcome (winning_bucket, final count, resolution price) is for SCORING ONLY, never an input.

**The one question, asked of every feature:** at this exact decision point, would the bot really have known this? If "no" even once, that feature is a leak.

## 5 leak patterns (checklist)
1. **future_data** — at checkpoint `cps`, reading `obs(cps..e)`, the window's FINAL count, an `i+1` bar, or `price_at(t)` with `t > cps`.
2. **same_period_aggregate** — a feature using the window total / a daily close / the final count that only finishes forming after the decision.
3. **global_fit** — any curve / table / threshold / scaler (share curves, diurnal multipliers, calibration, mean/std, min/max) fit on the WHOLE dataset including the future, then used to score auctions inside that window. Refit walk-forward.
4. **centered_window** — `rolling(center=True)` or any smoothing that pulls in future bars. Use causal `ewm`/`rolling` only.
5. **leaked_label** — the outcome used as a feature, or to select/filter which decision to make.

## The shapes that make leaks nearly impossible
```python
# walk-forward wall: code physically cannot see data[t+1]
for t in range(start, end):
    history = data[:t]
    decision = strategy(history)
    outcome  = data[t]        # revealed AFTER the decision
```
Correct idioms already used in this repo:
- `priors = [p for p in sel if p['e'] < s]`  — only auctions that ENDED before this one starts.
- seasonal / hour-of-day profile built from `post_ts[:searchsorted(post_ts, s)]` — posts before auction start only.
- decision inputs = `obs(s, cps)` and `price_at(slug, b, cps)`; `winner` / `actual` used only to score.

## Leave-one-out is NOT walk-forward
LOO drops the test point but still uses FUTURE points to fit the shared parameter. Fine for stationary-shape research validation; for any LIVE accuracy or ROI claim, use expanding-window walk-forward.

## Gut checks
- A backtest that looks too clean is suspect, not genius. A real edge is small and ugly.
- If a signal separates winners from losers almost perfectly, recompute every feature using only pre-entry data and see which "edges" survive.
- Have a ruthless skeptic re-audit the backtest; the author (human or AI) won't catch the leak while rooting for it.

## Status (audited 2026-06-29)
CLEAN: trade_sim, finish_line_test, bracket_hit_backtest, calibration_test, market_pacing_test, seesaw_v3, arb_test.
FIX (global_fit): accrual_model (share curve), particle_filter (diurnal mult) — rebuild walk-forward.
NOTE: predictive_distribution + backtest_noovd_calibrated use LOO; reversion_study conditions on `burst_after(t)` (forward-looking) on a single tiny window.
