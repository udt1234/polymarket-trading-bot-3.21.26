# Truth Social Module — Polymarket Bot Spec

## Purpose

Tracks Trump's Truth Social posting activity and generates trading signals for Polymarket's weekly "# of Truth Social posts" auctions. Outputs a projected post count, bracket probabilities, edge vs market, and Kelly-sized position recommendations.

## Auction Structure

- **Two overlapping series**: Tuesday-to-Tuesday AND Friday-to-Friday
- **Window**: Noon ET to noon ET (NOT midnight). Mar 17 12pm → Mar 24 12pm.
- **Brackets**: 0-19, 20-39, 40-59, 60-79, 80-99, 100-119, 120-139, 140-159, 160-179, 180-199, 200+
- **Resolution source**: xTracker post counter at `xtracker.polymarket.com`
- **Counts**: Main feed posts, quote posts, reposts. NOT replies (unless on main feed). Deleted posts count if captured within ~5 min.

---

## Data Sources

### 1. xTracker API (post counts)
- Base: `https://xtracker.polymarket.com/api`
- `GET /users/{handle}/trackings?platform=truthsocial` → list of active trackings
- `GET /trackings/{id}?includeStats=true` → hourly breakdown in `.data.stats.daily[]`
- Each entry: `{date: ISO8601, count: int, cumulative: int}`
- Labeled "daily" but actually hourly granularity
- **Dedup required**: Overlapping Tue-Tue and Fri-Fri trackings return the same hours twice. Dedup by `date + hour` key, keeping higher count.

### 2. Polymarket Gamma API (market prices)
- `GET https://gamma-api.polymarket.com/events?slug={slug}` → event with `.markets[]`
- Each market: `groupItemTitle` = bracket name, `outcomePrices` = JSON array [yesPrice, noPrice]
- Slug format: `donald-trump-of-truth-social-posts-{month}-{day}-{month}-{day}`

### 3. Polymarket CLOB API (live midpoints)
- `GET https://clob.polymarket.com/midpoint?token_id={tokenId}` → `{mid: float}`
- Token IDs from Gamma API: `markets[].clobTokenIds`
- More accurate than Gamma for live pricing. Use CLOB mid when available, fall back to Gamma.

### 4. Google News RSS (signal modifiers)
- Schedule signals: rallies, golf, travel, legal events
- News intensity: volume of Trump-related headlines
- Conflict signals: war, tariffs, indictments, executive orders
- Each signal type produces a modifier (0.5–1.5x) applied to projections

---

## Pacing Models

All pacing uses **noon-to-noon** boundaries matching Polymarket's auction window.

### Regular Pacing
Simple extrapolation. `(posts_so_far / elapsed_days) × 7`

### Bayesian Pacing
Blends historical weekly mean with observed pace. Early in the period, trusts history more. Late in the period, trusts observations more.

```
prior_weight = max(remaining_days, 0.5)
observed_weight = max(elapsed_days, 0)
bayesian = (prior_weight × hist_mean + observed_weight × current_pace) / (prior_weight + observed_weight)
```

Where `hist_mean` = Tue-Tue or Fri-Fri specific historical weekly average (from C4/D4).

### DoW + Hourly + Bayesian Pacing (most accurate)
The full model. Combines all three layers:

1. **Running total**: Count posts where `INT(date) + TIMEVALUE(time) >= startDate+0.5` and `< endDate+0.5`
2. **Project remaining hours**: For each hour from now until auction end:
   - Look up hourly average posts for that hour (historical avg across all data)
   - Scale by that day's DoW weight: `dowAvg[day] / overallDailyAvg`
   - Sum all remaining hour projections
3. **Raw projection** = running_total + projected_remaining
4. **Bayesian blend**: Same formula as above, blending raw projection with historical mean

**DoW averages** use exponential decay weighting (half-life = 60 days) so recent weeks count more. During non-NORMAL regimes, a 60/40 blend of regime-specific DoW averages and overall averages is used.

**Hourly averages** are computed from all historical hourly data: for each hour 0-23, average the post counts across all days.

---

## Projection Model (for bracket probabilities)

### Ensemble of 4 sub-models
Each sub-model produces a projected total. Weights shift based on how far into the period we are.

| Model | Default Weight | Early (<2d) | Late (<2d left) |
|-------|---------------|-------------|-----------------|
| Pace (linear extrapolation) | 30% | 10% | 50% |
| Bayesian (blended) | 35% | 35% | 30% |
| DoW-weighted (remaining days) | 20% | 20% | 15% |
| Historical (regime mean) | 15% | 35% | 5% |

Each model's projection is multiplied by the **signal modifier** from news/schedule analysis.

### Distribution fitting
For each sub-model's projected mean, compute bracket probabilities using a **blend of two distributions**:
- 40% Normal distribution: `CDF(high, mean, std) - CDF(low, mean, std)`
- 60% Negative Binomial: better for count data, handles right skew

Standard deviation is scaled from weekly historical stdev: `scaledStd = weeklyStd × (totalDays / 7)`, floored at 10.

Final ensemble probability per bracket = weighted sum across all 4 models. Normalized to sum to 1.

---

## Regime Detection

Rolling 7-day sums over all historical data. Z-score of the 3 most recent rolling sums vs all:

| Z-Score | Regime |
|---------|--------|
| > 1.5 | HIGH |
| > 0.5 | SURGE |
| -0.5 to 0.5 | NORMAL |
| < -0.5 | QUIET |
| < -1.5 | LOW |
| Cross threshold + slope > 0.5 | TRANSITION |

Regime affects:
- DoW averages (regime-specific blend)
- Kelly fraction (reduced during TRANSITION/high volatility)
- Historical mean used in Bayesian pacing

---

## Kelly Criterion Sizing

```
edge = model_prob - market_price
odds = (1 - market_price) / market_price
full_kelly = model_prob - (1 - model_prob) / odds
sized_kelly = full_kelly × kelly_fraction × confidence_adjustment
```

**Kelly fraction** (quarter-Kelly base):
- Default: 0.25
- Volatility > 1.5: 0.15
- Volatility > 1.0: 0.20
- TRANSITION regime: 0.10

**Confidence adjustment**: `(0.5 + 0.5 × (1 - min(volatility, 2) / 2))`

**Position cap**: 15% max per bracket.

**Signal output**:
- Kelly > 1%: BUY
- Kelly < -0.5%: AVOID
- Otherwise: PASS

---

## Signal Modifiers (News/Events)

Scraped from Google News RSS every hour. Three signal types scored and averaged over the auction period:

**News intensity**: headline count in 24h
- \>80: +15%, >50: +8%, <15: -5%

**Conflict score**: keyword matching (war/strike = 3, tariff/sanction = 2, tension = 1)
- \>15: +20%, >8: +10%, >3: +5%

**Schedule events**:
- Rally/speech: +15%
- Legal (court/indictment): +20%
- Golf: +5%

Combined modifier (0.5–1.5x) is applied to all projection means.

---

## Output Contract

The module should expose these values for the bot to consume:

```json
{
  "period": {
    "type": "tue-tue",
    "start": "2026-03-17T12:00:00-04:00",
    "end": "2026-03-24T12:00:00-04:00",
    "elapsed_days": 6.2,
    "remaining_days": 0.8
  },
  "counts": {
    "running_total": 88,
    "regular_pace": 100,
    "bayesian_pace": 103,
    "dow_hourly_bayesian_pace": 111
  },
  "regime": {
    "label": "NORMAL",
    "zscore": -0.46,
    "trend": "STABLE",
    "volatility": 0.8
  },
  "bracket_probabilities": {
    "0-19": 0.0001,
    "20-39": 0.0012,
    "40-59": 0.0089,
    "60-79": 0.0456,
    "80-99": 0.1523,
    "100-119": 0.2890,
    "120-139": 0.2645,
    "140-159": 0.1456,
    "160-179": 0.0589,
    "180-199": 0.0234,
    "200+": 0.0105
  },
  "market_prices": {
    "80-99": 0.38,
    "100-119": 0.33,
    "120-139": 0.13,
    "60-79": 0.06
  },
  "signals": [
    {
      "bracket": "100-119",
      "edge": 0.041,
      "kelly_pct": 0.025,
      "action": "BUY"
    }
  ],
  "signal_modifier": 1.08
}
```

---

## Key Implementation Notes

1. **Always use noon-to-noon** for period boundaries. `startDate + 0.5` and `endDate + 0.5` in date math.
2. **Dedup hourly rows** before any counting. Key = `YYYY-MM-DD|HH`. Keep the row with higher count.
3. **Two active periods** exist simultaneously (Tue-Tue and Fri-Fri). Run the full pipeline for both.
4. **Hourly data from xTracker** comes as dates with time strings like "12:00 PM". Parse to 24h integer for math.
5. **CLOB midpoints** are preferred over Gamma prices for edge calculation. Gamma is the fallback.
6. **Calibration logging**: After each auction resolves, log Brier score and log loss for model evaluation. Use this to adjust ensemble weights over time.
7. **Wallet**: `0x2eEF3A18bC771827aF0649a81aA54148A8E8eAca` for trade history pulls.
8. **Rate limiting**: 300ms between xTracker calls, 500ms between Gamma calls, 1s between CLOB history calls.
