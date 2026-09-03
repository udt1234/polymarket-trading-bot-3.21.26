# PRE-REGISTRATION: Post-Cadence Pattern Discovery
**Written 2026-07-26 BEFORE any model was fit or any sealed data was opened.**
Authored by the orchestrator. Built by `@backtest-builder`. Audited by `@backtest-auditor`.
This file is the receipt. The auditor MUST diff what was reported against what is declared here.

## Question
Do learnable patterns exist in Elon's and Trump's posting cadence that produce a **better bracket probability distribution than the market price** at the same timestamp?

Scope class: **(b) pure forecast-accuracy / calibration diagnostic.** No P&L is claimed. No fills are simulated. The money-check battery (Pass B fills/fees/maker-queue) does not apply; Pass A, C and D apply in full.

## Standing constraints
- All prior strategy conclusions are HISTORY (unverified) and may NOT be used to skip, narrow, or pre-judge any test. Report what the data says.
- Counting rule LOCKED: noon-ET window, market dates, originals + quotes + reposts + self-replies, no pure replies to others. Elon: `counts_main_feed == True`.
- Auction windows parsed from the market slug, NEVER from trade-derived `start_utc`/`end_utc` (those are ~2x wrong).
- THE WALL: no feature may read data with timestamp > decision time T.

## Data (exact paths, canonical only)
| Purpose | Path |
|---|---|
| Elon posts (clean X-API) | `_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet` (+ `_ext_to_2026-07-10`) |
| Trump posts | `_DataMetricPulls/canonical/posts/realDonaldTrump/*.parquet`, filter `counts_for_auction == True` |
| Auctions | `_DataMetricPulls/canonical/auctions/{handle}/*.parquet`, filter `confidence == 'high'` |
| Market prices | `_DataMetricPulls/canonical/prices/{handle}/*.parquet` (per-bracket hourly OHLC) |
| Incumbent model | `api/modules/shared/locked_pace.py` |

**Known data limits, declared up front:** Elon canonical/OSINT posts before 2025-09 are corrupted (dropped reposts/replies, ~2x undercount) and are EXCLUDED. Elon clean span is 2025-09-01 to 2026-06-27, 300 complete noon-ET days. No exogenous features (news, launches, court dates) exist in canonical, so none are tested. That is a stated gap, not a finding.

## THE WALL (fixed now, before any fitting)
| Handle | Train (learn) | SEALED (opened once, at the end) |
|---|---|---|
| Elon | through **2026-03-31** | **2026-04-01** onward |
| Trump | through **2025-12-31** | **2026-01-01** onward |

Every curve, scaler, threshold, calibration, cluster centroid and hyperparameter is fit on train only, or refit walk-forward. Leave-one-out is NOT walk-forward and is not accepted here.

## Targets (per the recommended composition)
1. **Daily count** = research substrate. 300 Elon days. Not tradeable, used to find structure and to build the daily predictive distribution.
2. **Elon 2-day auctions** = primary tradeable test. 68 auctions, median 10 brackets.
3. **Trump 7-day auctions** = independent confirmation. 52 auctions, median 11 brackets. Trump has NO 2-day market.
4. **Elon 7-day auctions** = reported, not leaned on. 80 usable auctions, median 26 brackets, thinnest cell.

The daily distribution is composed (convolved) up to the 2-day and 7-day window totals. A pattern must survive on both handles to be called real.

## Decision checkpoints (hours into the noon-ET window)
- 2-day: **6, 12, 24, 36**
- 7-day: **24, 48, 84, 120, 156**

## Methods declared (the full list, nothing added later)
| ID | Method | Constraint |
|---|---|---|
| M1 | Empirical conditional table P(bracket \| hours_in, count_so_far) | hierarchical shrinkage toward climatology; report raw cell counts |
| M2 | Shallow CART on final bracket | depth ≤ 4, min_samples_leaf ≥ 25, cost-complexity pruned by CV on train only |
| M3 | Day-shape clustering (KMeans/GMM, k = 3..8) on 24-dim normalized hourly vector | centroids fit on train only, then frozen |
| M4 | HMM on hourly counts, 2-4 latent states | transition matrix fit on train only |
| M5 | Discrete-time hazard (GBM), P(post in next 15 min) | features strictly ≤ T |
| M6 | Hawkes self-exciting process with circadian baseline | reuse `api/modules/shared/hawkes` if suitable |
| M7 | Composition: daily predictive distribution convolved to 2-day and 7-day totals | applies to M1 and M6 outputs |

## Features (all measured strictly at or before T)
count_so_far; hours_into_window; median inter-arrival gap so far; longest gap so far; gap variance; time of first post in window; max posts in any rolling 60 min; posts in last 1h / 3h / 6h; day of week at T; ET hour at T; prior window's final count; trailing 7-day mean daily count; share of quotes+reposts vs originals so far.

## Baselines (every method is scored against all four)
- **B1 Naive extrapolation:** `count_so_far / elapsed_fraction`. Table stakes.
- **B2 Climatology:** unconditional historical bracket frequency.
- **B3 Incumbent:** `locked_pace.py` (Kalman early + AccrualCurve late, blended, CAP 1.5x).
- **B4 MARKET:** implied bracket distribution from canonical prices at the same timestamp, normalized across brackets. **This is the only baseline that decides whether anything is tradeable.**

## Scoring
- **Log loss and Brier** over the full bracket distribution. Never threshold accuracy, never hit rate.
- **Reliability diagram** per method per checkpoint.
- **Headline is scored on the REMAINING count, not the final count.** Verified null: at hour 18 of a 1-day window, `count_so_far` alone already explains R2 = 0.76 of the final count with zero modelling, and 0.93 by hour 21. Report both, but the headline is skill over B1.
- **Skill score vs each baseline**, reported separately.
- **Effective n = distinct resolved auctions.** Never ticks, fills, or checkpoints.
- **Block bootstrap by auction** (by week for the daily substrate; daily counts autocorrelate at lag-1 rho = 0.44, so N_eff is about 39% of nominal). CI including zero means unproven.
- **Single-outlier jackknife**: drop the best auction, report whether the sign holds.

## Trial count
Declared upper bound: **7 methods x up to 9 checkpoints x 2 handles, plus hyperparameter grids**. The builder MUST log the exact realized trial count in RUN_META. Any winner gets a **held-out re-score on the sealed span**, which is the only accepted multiple-testing gate.

## Success criteria (fixed now, so they cannot move)
- **PRIMARY:** a method beats **B4 (market)** on sealed-span log loss, with a block-bootstrap CI excluding zero. Only this counts as a tradeable finding.
- **SECONDARY:** a method beats **B3 (locked_pace)**.
- **TERTIARY:** a method beats **B1 (naive)**. Failing this means the method does nothing at all.
- Beating B1 or B2 while losing to B4 is reported plainly as **"no tradeable edge."** That is a valid and expected outcome.
- A baseline that itself looks impossibly good is a red flag for a leak, not a triumph.

## Required outputs
1. `===RUN_META===` block via `_DataMetricPulls/pacing_backtest/run_meta.py::emit_run_meta`, declaring model_version, git_sha, headline, n_auctions, trial_count, scope, window_basis, data_paths.
2. **A per-row CSV**: one row per (handle, auction_slug, checkpoint_hours, bracket) carrying model probability, each baseline's probability, the market price, and the realized outcome. Every headline number must be recomputable from this file alone.
3. A summary markdown: what beat the market, what did not, what is too thin to call.

## Handoff
`@backtest-builder` builds against this file. `@backtest-auditor` then audits, and checks this pre-registration against what was actually reported. The builder does not certify its own result.
