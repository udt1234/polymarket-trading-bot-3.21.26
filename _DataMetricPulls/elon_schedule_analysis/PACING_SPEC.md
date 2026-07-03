# Elon Pacing — Unified Layering Spec (single source of truth)

Goal: every projection (Sheet formulas AND future bot Python) uses the SAME layered model. No drift.

Maintained alongside `LAYERING_HANDOFF.md` (signals research, 9 signals A-I), `analyze.py` + `analyze2.py` (data engines), and `predictive_distribution.py` (Tier-1 calibrated distribution prototype). When formulas change, update this file FIRST, then push to Sheet + Python.

Last updated: 2026-06-22 (post-9-signal + predictive-distribution updates).

---

## 0. The counting rule (locked, do not change without Sir)

### Window derivation — CRITICAL data fix
- The canonical `auctions` table's `start_utc / end_utc` are **TRADE-derived** (first / last trade). A "2-day" market's trade span is often 4-7 days. Using them to count tweets **overcounts by ~2x**.
- **Correct counting window** = parse the market DATE range from `auction_slug` / `title`
  (e.g. `elon-musk-of-tweets-april-4-april-6` → Apr 4 12:00 ET → Apr 6 12:00 ET)
  and count `counts_for_auction == True` posts in that NOON-ET window.
- Validated: Apr 4-6 → 66 posts, matches 65-89 bucket exactly.
- `winning_bucket` IS reliable for `confidence in (high, medium)` — the apparent mismatches were caused by the wrong (trade) window, not bad labels.

### Counts include / exclude
- Counts: originals + quotes + reposts + self-replies (`in_reply_to_user_id == 44196397`)
- Excludes: replies to other users (off-feed) + community reposts
- Live verified vs xTracker exact: Jun 18-20 = 46, Jun 16-23 = 126 (at verify), Jun 19-26 = 33, Jun 20-22 = 21

---

## 1. The 9 signals (A-I) with role assignments

| Signal | Confidence | What | Role in pacing stack |
|---|---|---|---|
| **A** Daily clock | HIGH | hour-of-day distribution (ET): twin peaks 1-2am + 1pm; sleep 5-10am; trough 6-7am | shape REMAINING |
| **B** Burst hazard | HIGH | `P(done\|silent s min) = 1/(1+EXP(-(-2.649+0.761*LN(s))))`; 32 min silence → 50% done | drives FINAL gate |
| **C** Bedtime anchor | HIGH | STOP time clusters ~3:40am ET (his START is the variable; corr(start,end)=-0.04) | drives FINAL gate |
| **D** Retweet partners | HIGH | top: @XFreeze 6.2%, @cb_doge 5.6%, @teslaownersSV 3.9%, @SpaceX 2.3%, @Starlink 1.5% | DISPLAY only (context) |
| **E** Cluster exhaustion | HIGH | 4.4 mean clusters/day at 90-min break; 79% of days ≥4 clusters. Once ≥5 clusters done → P(more) low | drives FINAL gate |
| **F** Heavy-morning + momentum | HIGH | P(heavy day \| heavy morning ET 6-12) = 93% vs 49% base; lag-1 autocorr 0.36 (yesterday weight ~0.4) | shape REMAINING |
| **G** Reply rate (POSITIVE) | HIGH in-window | corr(daily replies, daily main-wall) = +0.91. Heavy replying → HEAVY day. UP signal, never a brake | shape REMAINING |
| **H** Repost topic fingerprints | MED-HIGH | per-partner score; @SpaceX/@Starlink = 100% space = LAUNCH-EVENT markers; @dvorahfr 93% AI-Grok | DISPLAY only (context) |
| **I** End-anchored + routine gaps | HIGH | corr(start,end)~0; 2h daytime gaps are ROUTINE (~2.6/day). Single gap ≠ done | GUARD against false done |

### Critical role assignments (do not mix)
- **A + F + G** → shape the REMAINING-posts estimate
- **B + C + E** → drive the FINAL gate (all three must agree before declaring count locked)
- **D + H** → display-only context (NEVER let them move the projected number)
- **I** → guard: blocks a single 2h gap from triggering a false "done" call; forbids any "late start → late end" logic

---

## 2. Layer stack (Layer 0 → Layer 6) + Tier-1 predictive distribution

Built bottom-up. Each layer consumes the layer below.

| # | Layer | What it does | Status | Sheet cell | Python (future) |
|---|---|---|---|---|---|
| 0 | Raw post stream | qualifying posts inside noon-ET window | LIVE | `_Raw_Hourly` / `_Recent_Posts` | `pacing.load_window_posts()` |
| 1 | Linear pace | total / elapsed_frac | LIVE | inline AA21 LET | `pacing.linear_proj()` |
| 2 | Historical prior + momentum | mean of CLOSED prior + 0.4 weight yesterday (Sig F) | PARTIAL (no momentum) | AA21 `prior_arr` | `pacing.prior_with_momentum()` |
| 3 | Bayes blend | precision-weighted (Layer 1 + Layer 2) | LIVE | AA21 `posterior` | `pacing.bayes_blend()` |
| 4 | Clock-aware remaining (Sig A) | walk hours, sum expected rate per ET hour | PROPOSED | AA22 (NEW) | `pacing.clock_aware_remaining()` |
| 4.5 | Multipliers (Sig F + G) | morning_mult × reply_rate_mult on raw_projection | PROPOSED | AA22 (with mults) | `pacing.apply_multipliers()` |
| 5 | DOW weight | scale clock by DOW factor | PROPOSED (gated) | AA23 (NEW) | `pacing.dow_weight()` |
| 6 | 3-signal final gate (Sig B + C + E + I guard) | past 3am ET + P(done)>=0.7 + clusters≥5 → freeze at posts_so_far | PROPOSED | AA24 (NEW) | `pacing.count_final_gate()` |
| Tier-1 | Predictive distribution | non-uniform pace curve pf[h] = c/final on 2-day noon-ET windows; outputs full distribution per bracket | PROTOTYPE BUILT | NOT WIRED | `pacing.predict_distribution()` |

### Bracket Bayesian odds (current bug + fix)
- mu = top-of-stack projection (today AA21; target AA24 once layers 4-6 ship)
- **Current sigma = `MAX(mu*0.25, 8)` — BUG (~10x too wide near close)**
- **Fix: sigma = `SQRT(MAX(mu - posts_so_far, 1)) * 1.5`** (poisson-ish + overdispersion)
- **Floor at posts_so_far** (any bucket whose upper bound < posts_so_far → P=0)
- For Tier-1: bracket probabilities come directly from the predictive distribution histogram, not NORMDIST

---

## 3. Currently-active layers (running in Sheet TODAY)

### Layer 1 + 2 + 3 — AA21 Bayesian blend

```text
elapsed       = (NOW - start_local) / (end_local - start_local)
obs_proj      = total / elapsed_capped              [Layer 1]
prior_mean    = AVERAGE(prior CLOSED same-duration) [Layer 2 — NO momentum yet]
prior_std     = STDEV(prior) or prior_mean * 0.25
obs_var       = total * (1 - elapsed) / elapsed^2   (Poisson-ish)
prec_prior    = 1 / prior_std^2
prec_obs      = 1 / obs_var
posterior     = (prec_prior * prior_mean + prec_obs * obs_proj) / (prec_prior + prec_obs)
projection    = ROUND(posterior * G16_modifier * I16_modifier, 0)
```

Regime modifier toggles:
- `G16` / `G17`: manual regime override (high/low) — checkbox + scalar
- `I16` / `I17`: news/event uplift — checkbox + scalar
- Default both off → modifier = 1.0

### Bracket odds (AB26:AB35) — current buggy formula
```text
mu     = projection from AA21
sigma  = MAX(mu * 0.25, 8)        ← BUG
P(<X)  = NORMDIST(X, mu, sigma, TRUE)
P(L-H) = NORMDIST(H, ...) - NORMDIST(L, ...)
                                  ← NO floor at posts_so_far
```

### Display-only DOW table (B26:D35 on Elon 2-day card)
- Reads `_Raw_Daily` filtered by handle + DOW + window (D21 dropdown)
- Does NOT feed AA21

### CRITICAL — window source check
- `_Brackets!E:E` (start_iso) and `_Brackets!F:F` (end_iso) **MUST be slug-derived noon-ET**, NOT canonical `start_utc/end_utc` (which are trade-derived and 2x wrong).
- Verify in `Brackets.js`: if currently using canonical, FIX FIRST before any other Layer work — every downstream projection is off otherwise.

---

## 4. Proposed new layers — formulas

### Layer 2 enhancement (Sig F momentum)
```text
recent_daily_avg = AVERAGE of last 7 days posts
yesterday_total  = SUMIF(_Raw_Daily, yesterday)
daily_prior      = 0.6 * recent_daily_avg + 0.4 * yesterday_total
```
Weight 0.4 from lag-1 autocorrelation 0.36. Use `daily_prior` in place of bare `prior_mean` for the precision-weighted blend.

### Layer 4 — Hour-of-day clock (Sig A)
Anchor: `hourly_avg_et` table (Sir-verified vs xTracker; 23/24 hrs within ±0.2). Lives in helper tab `_Clock_ET`.

```text
expected_remaining = SUM over each ET hour h between NOW and CLOSE of clock_rate[h]
                     (partial-hour scaling at bookends)
clock_aware_proj   = posts_so_far + expected_remaining
```

### Layer 4.5 — Heavy-morning + reply-rate multipliers (Sig F + G)
```text
morning_posts    = COUNTIFS(window posts where ET hour in [6,12))
morning_mult     = IF(morning_posts >= morning_heavy_threshold, 1.15, 1.0)

reply_share      = COUNTIF(posts, type="reply") / posts_so_far
reply_rate_mult  = IF(reply_share > reply_hot_threshold, 1.10, 1.0)

raw_projection   = (posts_so_far + expected_remaining) * morning_mult * reply_rate_mult
```
Tune thresholds in editable cells (NOT in formula).

### Layer 5 — Day-of-week weight (OPTIONAL, gated)
```text
hour_rate_dow = clock_rate[h] * (dow_rate[day_of_h] / 40.6)
```
Risk: double-counting if hourly already reflects avg DOW mix. **Recommend ship Layer 4 first; add Layer 5 only after backtest proves it helps.**

### Layer 6 — 3-signal final gate (Sig B + C + E with Sig I guard)
```text
silent_min        = (NOW - last_post_ts_et) * 1440
p_done            = 1 / (1 + EXP(-(-2.649 + 0.761 * LN(MAX(silent_min, 1)))))    [Sig B]
past_bedtime_et   = IF(AND(HOUR(NOW_ET)>=3, HOUR(NOW_ET)<9), 1, 0)                [Sig C]
clusters_done     = 1 + COUNTIF(posts_minutes_since_prior, ">90")                  [Sig E]
exhausted         = IF(clusters_done >= 5, 1, 0)                                   [Sig E]
count_final_conf  = MIN(1, p_done * IF(past_bedtime_et=1, 1.0, 0.6) * IF(exhausted=1, 1.15, 1.0))
final_projection  = IF(count_final_conf >= 0.7, posts_so_far, raw_projection)
```

Signal I guard is BAKED IN via the `past_bedtime_et * exhausted` requirement: a single 2h daytime gap cannot fire the gate on its own — needs BOTH bedtime AND cluster exhaustion to corroborate B's P(done).

Editable thresholds (helper cells, not buried):
- session-break: **90 min** (was 120; new Signal E calibration)
- count-final confidence: 0.70
- bedtime window: 03:00-09:00 ET
- sleep window: 04:00-09:00 ET
- morning-heavy threshold (tune)
- reply-hot threshold (tune)
- momentum weight: 0.40

---

## 5. Tier-1 — Predictive distribution (prototype validated)

**Source:** `predictive_distribution.py` + `PREDICTIVE_DIST_REPORT.txt`. Built on 111 clean 2-day noon-ET windows (Nov 2025+, final ≥ 8).

### Model
Non-uniform pace curve `pf[h] = count_by_hour_h / final_count` learned across all windows. Because windows are noon-ET anchored, hour h maps to a fixed clock position so the curve bakes Signal A in automatically. Prediction:

```text
final_hat_samples = c_observed / { pf[h] from other windows }
final_hat_dist    = histogram(final_hat_samples)           # full distribution, NOT a point
bracket_p[k]      = count(final_hat_dist falls in bracket k) / total samples
```

### Validation (leave-one-out vs naive c/f)
| Elapsed | 80% interval coverage | Median ratio error |
|---|---|---|
| 25% | 78% | 36% |
| 50% | 78% | 22% |
| 75% | 78% | 15% |
| 90% | 90% | 8% |

**Well-calibrated** (78-90% coverage matches the 80% interval). **Honest catch:** the model's POINT estimate roughly ties naive c/f because 2-day pacing is near-linear on average (two sleeps + two active blocks roughly cancel). The EDGE is the **calibrated distribution** and knowing **WHEN to trust it** — not a sharper point.

### Pace-curve table (mean + 10/90 percentile, for sheet use)
| h | ET clock | Day | pf_mean | pf_p10 | pf_p90 |
|---|---|---|---|---|---|
| 6 | ~18:00 | day 1 | 0.14 | 0.04 | 0.24 |
| 12 | ~00:00 | day 2 | 0.24 | 0.09 | 0.40 |
| 18 | ~06:00 | day 2 | 0.39 | 0.21 | 0.55 |
| 24 | ~12:00 | day 2 | 0.51 | 0.33 | 0.69 |
| 30 | ~18:00 | day 2 | 0.64 | 0.43 | 0.82 |
| 36 | ~00:00 | day 3 | 0.73 | 0.53 | 0.89 |
| 42 | ~06:00 | day 3 | 0.88 | 0.73 | 1.00 |
| 48 | ~12:00 | day 3 | 1.00 | 1.00 | 1.00 |

### Sheet wiring (Tier-1 ready)
- New helper tab `_PaceCurve` — 48 rows (one per window hour) × cols `[h, et_clock, pf_mean, pf_p10, pf_p90]`
- New cell `AA26` (PROPOSED): central distribution-mean projection = `count_observed / pf_mean[current_h]`
- Bracket odds use distribution: `P(bucket) = mass of final_hat_dist falling in bracket`
- v2 (later): condition pace curve on live burst-state (Signals B/C/E) for late-window sharpening — that is the path to BEATING naive

---

## 6. Inconsistencies, questions, decisions

### Inconsistency 1 — Sir's hourly table vs HANDOFF Signal A shares
Same shape, 4 hours diff ≥0.4 (hrs 02, 03, 09, 22). Cause: HANDOFF data through 2026-06-12; Sir's table appears refreshed.
**Decision:** USE Sir's table (validated vs xTracker). Mark HANDOFF Section 1 STALE for exact pcts (shape valid). Re-derive together on next canonical refresh.

### Inconsistency 2 — HANDOFF says DOW is "essentially flat"; Sir's table shows 21% spread
HANDOFF: *"Day-of-week is essentially flat (weekend only ~1.5pp lighter). Do not build heavy DOW logic."*
Sir's table: Mon 37.5 → Fri 43.7, spread = 7.6 posts/day (21% of min). NOT flat.
**Decision:** override HANDOFF. Use Sir's DOW table as Layer 5. Gate-keep behind Fri verification.

### Inconsistency 3 — Fri "not correct" in Sir's DOW (-3.1 vs xTracker)
vAI: 43.7 vs xTracker: 46.79 (-6.6%). Likely cause: noon-ET window boundary OR stitched-source artifact.
**Q3 (open):** use xTracker 46.79 directly, OR keep vAI's 43.7 with 1.07x Fri uplift scalar?

### Inconsistency 4 — Session-break threshold
HANDOFF Section 1 originally said 120 min. Updated HANDOFF Section 3 + Signal E says **90 min** (matches the 4.4 clusters/day median). Use 90.

### Q4 — Layer 5 (DOW) on top of Layer 4 (clock): double-count risk?
Hourly already averages 40.6/day across all DOWs. Multiplying by DOW factor risks double-count.
**Decision:** start with Layer 4 only. Add Layer 5 only after backtest proves it helps. On 7-day windows DOW averages out anyway.

### Q5 — sigma collapse when gate fires?
When `count_final_conf >= 0.7` → final_projection = posts_so_far. **Should sigma also collapse to 0.5** so bracket odds peg ~100% on the bucket containing posts_so_far? **Open.**

### Q6 — auto-regime detect (high/low/normal)?
Today: manual G16/I16 checkboxes. Candidate auto rule:
```text
recent_daily = AVG last 7 days
historical   = AVG all-data daily
regime_ratio = recent_daily / historical
   > 1.20: HIGH → scale clock by 1.20
   < 0.80: LOW  → scale by 0.80
   else: NORMAL
```
**Decision:** ship Layer 4 first. Add auto-regime later as Layer 4.6 (after multipliers).

### Q7 (NEW) — window source bug?
Are `_Brackets!E:E / F:F` slug-derived (correct) or canonical-derived (broken, 2x overcount)? Must verify before anything else lands. Critical.

### Q8 (NEW) — Tier-1 vs Layer 4-6 first?
Two parallel paths:
- **Path A (incremental):** ship σ-fix → Layer 4 → Layer 4.5 multipliers → Layer 6 gate. Each step a sheet-only formula.
- **Path B (jump to Tier-1):** wire the predictive-distribution histogram directly, skip the Layer 4-6 piecemeal build.

Tier-1 is more powerful but needs a `_PaceCurve` helper tab + ARRAYFORMULA hist machinery in sheet. Recommendation: **Path A first** (sheet-native, low-risk) **THEN Tier-1 as a separate "Calibrated Distribution" tab** once Path A is verified.

---

## 7. Sheet cell registry

7-day card (Elon — replicate same shape for 2-day + monthly + other handles):

| Cell | Layer | Purpose | Status |
|---|---|---|---|
| Z21 | 0 | posts_so_far (from `_Brackets!G`) | LIVE |
| AA21 | 1+2+3 | current linear + Bayesian projection | LIVE |
| AA22 (NEW) | 4 + 4.5 | clock-aware + multipliers | PROPOSED |
| AA23 (NEW) | 5 | clock + DOW (gated default OFF) | PROPOSED |
| AA24 (NEW) | 6 | 3-signal gate; picks AA22 or posts_so_far | PROPOSED |
| AA25 (DROPDOWN) | meta | Active projection: AA21 / AA22 / AA24 | PROPOSED |
| AA26 (NEW) | Tier-1 | calibrated distribution mean | PROPOSED |
| AB26:AB35 | bracket odds | uses dropdown-selected μ + fixed σ | PROPOSED (needs σ-fix) |

Helper tabs:
- `_Clock_ET` (NEW) — 24 rows: ET hour → avg posts/hr
- `_DOW_ET` (NEW) — 7 rows: day → avg posts/day
- `_Hazard` (NEW) — silence min → P(done) lookup (from q2_continuation_hazard.csv)
- `_Partners` (NEW) — partner → topic + is_event_marker (from q4_retweet_partners.csv + Sig H)
- `_PaceCurve` (NEW, Tier-1) — 48 rows × pf_mean, pf_p10, pf_p90
- `_Pacing_Sources` (NEW) — pins which data source feeds each layer

---

## 8. Python parity (bot-ready)

```python
# api/modules/elon_tweets/pacing.py
def project_count(posts_so_far, window_start_et, window_end_et, now_et, *,
                  prior_mean, prior_std, yesterday_total,
                  clock_table=CLOCK_ET, dow_table=None,
                  last_post_et=None, morning_posts=0, reply_share=0.0,
                  use_tier1=False) -> dict:
    """Returns: {linear, bayes, clock_aware, with_multipliers, gated, distribution, sigma, projection, bracket_probs}.

    Mirror of Sheet formulas in PACING_SPEC.md sections 3-5.
    use_tier1=True returns the full predictive distribution + per-bracket probs.
    """
    ...

def count_final_gate(posts_so_far, p_done, past_bedtime, clusters_done) -> tuple:
    """Returns (count_final_conf, final_projection)."""
    ...

def predict_distribution(c_obs, h_now, training_pf_matrix) -> ndarray:
    """Tier-1: returns array of final_hat samples (the full distribution)."""
    ...
```

Each layer is a separate function so unit tests can feed canonical closed-auction inputs and assert projection error vs actuals.

---

## 9. QA checks (run after any layer change)

1. **Window correctness:** Apr 4-6 window reconstructs to 66 posts (matches 65-89 bucket).
2. **Clock shape:** Signal A 24-share table from analyze.py matches `_Clock_ET` tab.
3. **P(done) monotonicity:** p_done strictly increases in silence, passes ~50% at 32 min.
4. **Cluster median:** clusters_done over full day should land at ~4 (90-min break). 8+ → break threshold too small.
5. **Reply correlation:** corr(daily replies, daily main-wall) should be POSITIVE (~+0.9) on full-fidelity window. Negative → reply/main split is wrong.
6. **Predictive coverage:** Tier-1 80% interval coverage should land 78-90% across elapsed levels.
7. **Final-gate sanity:** on a known completed window, after +30 min past last post + after 3am ET + `exhausted=1`, `final_projection` should equal true final within ±2.
8. **Window source:** confirm `_Brackets!E:E/F:F` are slug-derived noon-ET (not canonical trade-derived).

---

## 10. Change log

| Date | Change |
|---|---|
| 2026-06-22 | Initial spec. Layers 1-3 in Sheet. Layers 4-6 + bracket-odds fix designed. |
| 2026-06-22 (PM) | Rewrote for 9-signal (A-I) architecture with role assignments. Added Layer 4.5 (multipliers from Sig F+G), Sig E cluster gate, Sig I guard. Added Tier-1 predictive distribution prototype + validation. Flagged window source check (Q7) as critical pre-req. |
