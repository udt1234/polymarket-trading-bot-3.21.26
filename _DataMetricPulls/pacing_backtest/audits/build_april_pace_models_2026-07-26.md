# Audit: build_april_pace_models.py (7 walk-forward pace models, Elon April 16-18 2-day auction)

Date: 2026-07-26
Scope declared (RUN_META): accuracy-diagnostic (forecast-vs-truth), NOT a P&L/ROI claim. Scope-gate confirms Pass B (fills/maker/settlement) is N/A.

## VERDICT: WARN

No fatal leak or data-integrity bug survived dynamic confirmation. Headline reproduced exactly (byte-for-byte on all 931 cells + all 7 MAE/signed-error numbers). But the ranking itself is a single-auction anecdote and must not be quoted as validated. Two medium-severity hygiene findings below should be fixed before this pattern is reused at scale.

## Reproduced headline: YES (exact match)

Independent read-only re-derivation (own script, did not reuse build_april_pace_models.py's process) reading the same parquet sources plus a read-only Sheets fetch of A:B/F (inputs) and S2:Y135 (outputs already written):

| Model | RUN_META MAE | Reproduced MAE | RUN_META signed | Reproduced signed |
|---|---|---|---|---|
| Simple/Linear | 18.72 | 18.72 | +17.90 | +17.90 |
| Bayesian | 17.47 | 17.47 | +17.47 | +17.47 |
| DOW x Hourly | 16.11 | 16.11 | +16.11 | +16.11 |
| Gamma-Poisson | 17.22 | 17.22 | +16.87 | +16.87 |
| Empirical Nowcast | 26.65 | 26.65 | +25.12 | +25.12 |
| Bursty Nowcast | 14.24 | 14.24 | +12.81 | +12.81 |
| Inhomog. Poisson | 11.13 | 11.13 | +11.05 | +11.05 |

Diff vs the live sheet's S3:Y135 (already written): 0 / 931 cells mismatched.
Alignment guard (own repro): mismatches = 0/133, clamped_low = 0, clamped_high = 0 -- matches the script's own claim.
ACTUAL_FINAL independently recomputed from raw tweets = 77 (matches task spec + script assert).
N_PRIOR independently recomputed = 45 (matches script + RUN_META notes: mean 100.27, std 38.03 vs the script's claimed ~100.3/~38.0).

## Findings (most severe first)

**[D] MEDIUM -- single-auction anecdote, cannot be treated as a validated ranking.**
n_auctions=1. The 133 "rows" are NOT 133 independent observations -- they are correlated checkpoints of one realized path, and confirmed further degenerate: only 98 of the 133 row-timestamps are distinct (65 rows, 49%, share an exact same-second timestamp with 1-2 others, up to 3x duplication at a single instant). Recomputing the MAE table on the 98 deduplicated timestamps shifts every model's MAE by roughly 0.3-2.5 points (e.g. Inhomog. Poisson 11.13 -> 11.43, Empirical Nowcast 26.65 -> 29.13) though the ORDERING happens to survive. A block-bootstrap-by-auction CI or single-outlier jackknife (the normal Pass D confirmation tools) is mathematically impossible with n=1 -- there is no sampling distribution to bootstrap. Verdict: the "Inhomog. Poisson wins, Empirical Nowcast is worst" ranking is real for THIS one auction only and must not be generalized or used to pick a model until re-run across the full ~45-auction resolved 2-day panel (walk-forward per auction, each scored out-of-sample against auctions strictly before it). RUN_META already declares n_auctions=1 correctly (not misrepresented in the machine-readable footer) but the printed stdout lines ("lowest MAE (most accurate on average): Inhomog. Poisson") read as a general claim if quoted out of context -- recommend appending "(n=1 auction -- not a generalization)" inline to that print statement.
Fix: re-run this same per-row walk-forward methodology across every resolved 2-day Elon auction (n>=20, ideally all 45), each using only its own strictly-prior auctions for the walk-forward curves, then rank by mean MAE across auctions with a block-bootstrap-by-auction CI.

**[C] MEDIUM -- legacy pacing.py floor/weight logic is unit-mismatched when reused on an hours-scale window.**
bayesian_pace() / dow_hourly_bayesian_pace() (api/modules/shared/pacing.py:11-43) were written for a 7-day window in DAYS units, with prior_weight = max(remaining_days, 0.5) as a "never drop the prior below half a day" floor. build_april_pace_models.py:259-261 feeds these functions elapsed_h/remaining_h in HOURS and TOTAL_H=48 instead of days. The core blend ratio is scale-invariant (both numerator and denominator scale together), so this is NOT a WALL/leak violation -- confirmed by direct math: remaining_h = remaining_days * 24, ratio preserved. But the literal floor constant 0.5 is now "0.5 HOURS" instead of "0.5 DAYS," so the intended prior-retention safety net only engages in the last 30 minutes of the 48h window instead of the last 12 hours -- a real, silent behavior change vs what these functions do in their calibrated regime. Not fatal (these functions are legacy/unused in production -- confirmed via git log + grep, only referenced by this script and tests/test_pacing.py), but the T (Bayesian) and U (DOW x Hourly) columns are not doing exactly what their names imply if a reader assumes 7-day-calibrated behavior.
Fix: either scale the floor (max(remaining_h, 12.0) for an hours-based 48h call) or add a comment noting the floor is now effectively disabled for all but the final half hour.

**[A] LOW/INFO -- the alignment guard vs column F is circular, not independent.**
build_april_pace_models.py:220-229 aborts if reconstructed count_so_far != the tab's pre-existing column F. Confirmed via build_clean_backtest_tab.py:29-30: column F was ORIGINALLY populated using the exact same elon_backfill_2025-09_to_now.parquet + counts_main_feed filter + the identical obs() searchsorted function. The guard therefore proves "no drift since the base tab was built," not "the tweet-count reconstruction is independently ground-truth-correct." This is a reasonable design (there is no independent ground truth to check against short of a manual recount) but should not be read as stronger validation than it is.

**[A] INFO, not a violation -- non-canonical-path data source, verified deliberate.**
The script reads _DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet directly rather than canonical/posts/elonmusk/. Per project memory (elon_xapi_clean_data.md, lesson_canonical_lowdays_scrapegaps.md), this is the DOCUMENTED correct override: canonical/posts undercounts Elon roughly 2x pre-cutover (OSINT scrape gaps). Verified the parquet's counts_main_feed filter (original + quote + self-reply, excludes non-self replies and ALL reposts) matches the project's Elon xTracker counting rule (no pure replies, no reposts). No finding against this script.

**[C] INFO -- VALIDATED_PRIORS avoidance claim verified TRUE.**
git log --follow -- api/modules/shared/fair_value.py shows the file (and its VALIDATED_PRIORS = {"2-day": (60.0, 25.0), ...} constant) was introduced 2026-07-06 (commit dc40430), roughly 3 months after the April 16-18 2026 auction closed. Using it here would be a textbook global_fit leak per BACKTEST_RULES.md. The script correctly avoids it and recomputes the walk-forward prior (mean=100.27, std=38.03 from the 45 2-day auctions closing strictly before the target's start) -- independently confirmed identical. gamma_poisson_projection() itself (the pure math function) is imported and called unchanged, only its prior arguments differ from production. Clean.

**[C] INFO -- RUN_META provenance clean.**
model_version in the sidecar (ensemble-cap1.5+calibsigma.2026-07-11) matches locked_pace.MODEL_VERSION exactly -- no undeclared drift. scope="accuracy-diagnostic" and fills="N/A" are both accurate and correctly gate off the Pass B fill/efficiency battery. trial_count=1 is technically true (no hyperparameter sweep) but arguably undersells that 7 named models are being horse-raced on n=1 auction -- same statistical shape as a small multiple-comparisons problem. Recommend a future convention: an explicit n_models_compared field alongside trial_count.

**Walk-forward wall (Pass C) -- dynamically confirmed clean on every constant checked:**
- Prior windows: 45 used, all with end < S0 (independently re-verified: 0 prior windows with end>=S0 or start>=S0).
- hist_pts used for HOURLY_AVG/DOW_WEIGHTS: independently verified max(hist_pts) < S0 = True (229 walk-forward days, all before target start).
- No rolling(center=True), resample(, or fixed-freq= bar aggregation anywhere in the script -- this is event/row-driven off the base tab's own row timestamps, not bar-resampled.
- ACTUAL_FINAL (=77, independently confirmed) is read only in the final scoring block, never inside the per-row model loop.
- Surgical write confirmed by code inspection, not just docstring claim: the single batchUpdate call (build_april_pace_models.py:296-303) specifies exactly 3 ranges -- S1, S2, S{ROW_FIRST} -- all inside columns S-Y; the Sheets API values.batchUpdate cannot touch any other range by construction. Independently confirmed the pre-existing per-model text legend (columns roughly AV-AW) was NOT extended for the 7 new models, consistent with "S:Y only" -- further evidence nothing outside S:Y was touched.
- Two data-quality anomalies checked and found to be correct-not-buggy: (1) one prior auction (march-7-march-9) spans 47h not 48h -- this is the correct real-world elapsed time across the March 8 2026 US spring-forward DST transition, correctly handled by zoneinfo-aware datetime(...,tzinfo=ET) construction, not a bug; (2) one 2-day slug (arch-elon-musk-of-tweets-may-18-may-20) is unparseable and skipped -- its window is AFTER the target auction anyway (May > April), so it cannot have affected the walk-forward priors either way (not a survivorship-bias concern for this run).
- Canonical auctions/elonmusk 2-day rows used as priors: all 45 are confidence=high, resolution_status in resolved_yes / resolved_yes_gamma -- no unresolved/ambiguous/low-confidence auctions silently included.

## What was checked and passed
- Headline MAE/signed-error table for all 7 models: reproduced exactly via an independent read-only script (own parquet reads + read-only Sheets fetch, no reuse of the audited script's process).
- 133-row alignment guard: reproduced mismatches=0/133 independently.
- Walk-forward wall on every prior/curve (2-day prior windows, hourly/DOW rates, gamma-poisson prior mean/std): all confirmed strictly pre-target via direct recomputation, not just code reading.
- VALIDATED_PRIORS avoidance rationale verified against actual git history (not taken on the docstring's word).
- Surgical-write claim verified by inspecting the actual batchUpdate range list, and by confirming the adjacent legend area was untouched.
- Data source (elon_backfill parquet, counts_main_feed filter) verified against project canonical-data memory and cross-checked against the type/self_reply crosstab.
- RUN_META present, complete, and internally consistent with locked_pace.MODEL_VERSION (no silent locked-model drift).
- No future_data, same_period_aggregate, global_fit (on the target's own span), centered_window, or leaked_label pattern found in this script; ACTUAL_FINAL confirmed used for scoring only.

## What could NOT be fully checked
- Whether the pre-existing K-R columns in the same tab (Kalman, AccrualCurve, Ensemble, Ens+Cap1.5 LOCKED, Hawkes, Particle Filter, Finish Line, Kalman+Sleep) were themselves computed walk-forward for this same auction -- OUT OF SCOPE (different, unaudited script). Bonus context pulled for the record: on this same auction, "Ens+Cap1.5 (LOCKED)" scores MAE=21.89, worse than 5 of the 7 new candidate models -- interesting but not independently vetted here, and subject to the identical n=1 caveat.
- Whether HOURLY_AVG/DOW_WEIGHTS built from 229 days spanning Sept 2025-Apr 2026 are the right lookback length (a model-quality question, not a correctness/leak question -- out of this audit's mandate).
- True independent ground-truth verification of the tweet counts themselves (the alignment guard is circular, as noted above) -- would require a manual recount or a second independent scrape, neither attempted here.

## Bottom line for Sir
Do not quote "Inhomog. Poisson beats the other 6 pacing models" as a finding -- it beat them on exactly one auction, using overlapping/duplicated checkpoints, with no way to compute a confidence interval. The number is real and reproduces byte-for-byte, so nothing about model choice should be locked based on this alone. Before acting on it, re-run this exact walk-forward methodology across the ~45-auction resolved 2-day panel and re-check whether Inhomog. Poisson still wins on average with a bootstrap CI that excludes zero improvement over the current locked model.
