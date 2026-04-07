# Backtest Implementation Spec — For Module Integration

## Truth Social Module (Trump)

### Strategy: Kelly 0.25x + Late Entry (75%)
**ROI: +184.6% across 17 auctions | Max loss: -$10 per $100 bankroll**

### What to implement

**1. Entry timing gate**
Do NOT place orders until 75% of the auction has elapsed.
```
if elapsed_pct < 0.75:
    return []  # no signals yet
```
For a 7-day auction: wait until ~day 5.25 (126 hours in).

**2. Kelly sizing (already exists in signals.py)**
Keep `kelly_fraction=0.25`. No changes needed.
The key: only buy brackets where `edge > 0.02` (model_prob - market_price).

**3. No signals needed**
Do NOT apply regime, DOW, or Hawkes modifiers to the projection.
The pacing ensemble alone (pace + bayesian + dow + historical + hawkes) is sufficient.
Adding signal modifiers on top double-counts information and hurts performance.

**4. No stop-loss needed**
Trump auctions with late entry are accurate enough (82.4% win rate without SL).
Adding SL30 only improves ROI from 184.6% to 188.6% — marginal.

### Changes to `truth_social/module.py`
```python
# In evaluate():
elapsed_pct = elapsed_days / total_days
if elapsed_pct < 0.75:
    return []  # wait for better pacing data

# Keep existing Kelly sizing unchanged
# Keep existing ensemble projection unchanged
# Do NOT multiply projection by signal_modifier
```

### Why it works
Late entry means the Bayesian pacing model has 5+ days of data.
At 75% elapsed, the projection is highly accurate.
Kelly only bets where there's real edge, so position sizes stay small.
Small positions = small losses when wrong (-$10 max vs -$100).

---

## Elon Tweets Module

### Strategy: Kelly 0.25x + 65% Entry + SL30 + Regime + Hawkes
**ROI: +41.8% across 81 auctions | Max loss: -$10 per $100 bankroll**

### What to implement

**1. Entry timing gate**
Wait until 65% of auction has elapsed (not 75% — Elon needs slightly earlier entry).
```
if elapsed_pct < 0.65:
    return []
```
For a 7-day auction: enter around day 4.5.
For a 3-day auction: enter around hour 47.

**2. Kelly sizing (already exists)**
Keep `kelly_fraction=0.25`. No changes.

**3. Regime detection modifier (ADD THIS)**
Compute regime from rolling daily post sums. Apply to projection:
```python
regime = detect_regime(rolling_daily_sums)
regime_mod = {
    "HIGH": 1.20, "SURGE": 1.10, "NORMAL": 1.0,
    "QUIET": 0.90, "LOW": 0.80
}.get(regime["label"], 1.0)
adjusted_projection = base_projection * regime_mod
```
Regime detection already exists in `regime.py` — just wire it into the Elon module.

**4. Hawkes burst modifier (ADD THIS)**
Detect posting bursts from recent 6-hour vs prior 6-hour activity:
```python
recent_6h = sum(counts[-6:])
prior_6h = sum(counts[-12:-6])
burst_ratio = (recent_6h / 6) / (prior_6h / 6) if prior_6h > 0 else 1.0

if burst_ratio > 2.5 and consecutive_nonzero >= 4:
    hawkes_mod = 1.15  # active burst
elif burst_ratio > 1.8 and consecutive_nonzero >= 3:
    hawkes_mod = 1.08
elif burst_ratio < 0.3:
    hawkes_mod = 0.92  # quiet period
else:
    hawkes_mod = 1.0

adjusted_projection *= hawkes_mod
```
Hawkes module exists in `hawkes.py`. Use `fit_hawkes_params()` for per-auction calibration.

**5. Stop-loss at 30% (ADD THIS)**
After entry, monitor each position. If a bracket's price drops 30% from entry:
```python
for bracket, position in positions.items():
    current_price = market_prices.get(bracket, 0)
    if current_price <= position["entry_price"] * 0.70:
        # Sell entire position at market
        sell_order(bracket, position["shares"], current_price)
```
This fires on ~40/81 auctions. Prevents holding losers to zero.

**6. Do NOT use DOW signal**
DOW averages destroy performance (-13.6% → from +29.8%). Remove any DOW weighting.

### Changes to `elon_tweets/module.py`
```python
# In evaluate():
elapsed_pct = elapsed_days / total_days
if elapsed_pct < 0.65:
    return []

# Add regime modifier
regime = detect_regime(rolling_daily_sums)
regime_mod = {"HIGH": 1.20, "SURGE": 1.10, ...}.get(regime["label"], 1.0)

# Add Hawkes burst modifier
hawkes_mod = compute_burst_modifier(hourly_counts)

# Apply to projection
adjusted_mean = base_projection * regime_mod * hawkes_mod
bracket_probs = bracket_probabilities(adjusted_mean, weekly_std)

# Existing Kelly sizing handles the rest
# ADD: stop-loss monitoring in the execution loop
```

### Why it works
Elon is much more volatile than Trump (39-1654 posts vs 87-252).
Regime detection catches his surge/quiet cycles (+3% ROI alone).
Hawkes catches his multi-day controversy bursts (+10% ROI alone).
Together they compound to +12% improvement.
Stop-loss prevents holding dead brackets through settlement.
65% entry (vs 75%) gives slightly earlier positioning, which matters
because Elon's shorter auctions (2-3 day) need faster reaction.

---

## Summary: What to change in each module

| Change | Trump | Elon |
|--------|-------|------|
| Entry gate | 75% elapsed | 65% elapsed |
| Kelly fraction | 0.25 (keep) | 0.25 (keep) |
| Regime modifier | ❌ Don't add | ✅ Add |
| Hawkes modifier | ❌ Don't add | ✅ Add |
| DOW modifier | ❌ Never | ❌ Never |
| Stop-loss 30% | Optional (+4%) | ✅ Required |
| Signal modifier stack | ❌ Remove/skip | ❌ Remove/skip |
