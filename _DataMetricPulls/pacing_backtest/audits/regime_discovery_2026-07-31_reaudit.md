# Re-audit: regime_discovery_2026-07-29.py (post-fix run, 2026-07-31 13:02-13:05)

**Auditor run date:** 2026-07-31. **Scope class:** (b) pure forecast-accuracy/calibration diagnostic + descriptive rule discovery. No P&L, no fills -- Pass B fill/fee battery does not apply.

Prior audit: `regime_discovery_2026-07-31.md` (VERDICT: WARN, 5 findings: F1 DST bug, F2 missing B5, F3 missing jackknife, F4 undisclosed sub-floor slice, F5 undisclosed base-rate shift). This re-audit checks whether @backtest-builder's claimed fixes are real, not just claimed.

**VERDICT: PASS**

No fatal finding. Every headline number reproduces exactly (bit-for-bit, not just to 4dp) from the regenerated per-row CSVs or by re-running the source functions directly against real data. All five prior findings are substantively resolved and independently re-verified by dynamic execution, not accepted on the builder's prose. Adversarial testing surfaced two new LOW-severity items (a residual, much-smaller DST edge case; a CI-proximity framing nuance) -- both disclosed below, neither changes any verdict, neither is a fabricated or misreported number.

## Reproduced headline number: YES (all, exact match)

| Headline | RUN_META | Independently recomputed |
|---|---|---|
| Q1 elon R1 sealed skill vs clim | 0.1741796060520638 | 0.17417960605206387 (from q1_r1_markov_rows.csv) |
| Q1 elon R4 sealed skill (shape vs lag1) | -0.0819947416521057 | -0.0819947416521057 (from q1_r4_trajectory_shape_rows.csv) |
| Q2 PRIMARY S2 vs B4 sealed skill | -0.031237467759081358 | -0.03123746775908137 (from q2_per_row.csv, block=7) |
| Q2 PRIMARY CI | [-0.06577718814215623, +0.00024155734330050135] | [-0.06577718814215625, +0.00024155734330051824] |
| Q2 TERTIARY S2 vs B1 sealed | (summary) +0.1333 CI[+0.0741,+0.1926] | +0.13327646572994342 CI[+0.0741,+0.1926] |
| Q2 TERTIARY S2 vs B2 sealed | (summary) +0.5038 CI[+0.4310,+0.5686] | +0.503808565077336 CI[+0.4310,+0.5686] |
| Context B4 vs B1 sealed | (summary) +0.1645 CI[+0.0870,+0.2439] | +0.1645139334890248 CI[+0.0870,+0.2439] |
| S4 formal sealed lift / jk-dropbest | -0.40141467727674623 / -0.46551724137931033 | reproduced by re-running s4_formal_burst_rule directly: identical to full precision |
| S4 literal sealed n_big / LOO | n=8, med 19.5, LOO range [15.0,24.0], 4/8 erase | reproduced by re-running s4_literal_calendar directly: identical |
| S3 checkpoint-0 sealed lift / jk | +0.0210 -> +0.0078, sign holds | reproduced by re-running s3_gap_rule directly: identical |
| B5 elon_2day sealed skill vs market | -0.36690407883775406 CI[-0.5641,-0.1081] n=27 | reproduced by re-running build_r1_market_baseline + r1_markov directly: identical |
| B5 price-admissible count | 65/66 | 65/66 (independently re-derived) |
| Trial count 63, by-method | 22/6/3/20/6/5/1 | independently re-summed: 22+6+3+20+6+5+1=63, matches |
| RUN_META model_version | ensemble-cap1.5+calibsigma.2026-07-11 | matches locked_pace.MODEL_VERSION exactly -- no drift |

## The five prior findings -- checked against real re-execution, not prose

**F1 (DST-anchoring bug, Class A MEDIUM) -- SUBSTANTIALLY FIXED, one small residual found.**
Independently re-implemented BOTH the old buggy `d += 86400` accumulation and the new per-day `pd.Timestamp(cur_date, tz=ET) + pd.Timedelta(hours=12)` localization from scratch (not imported from the script) and ran both over the exact same span (ELON_CLEAN_START to ELON_CLEAN_END):
- OLD logic: 126 consecutive days anchored at 11:00 ET instead of noon, 2025-11-02 to 2026-03-07 -- exact match to the prior audit's finding.
- NEW logic: only 2 residual days remain mis-anchored: **2025-11-02** (start lands at 11:00 ET, 25h block) and **2026-03-08** (start lands at 13:00 ET, 23h block) -- i.e. exactly the two calendar dates ON WHICH a DST transition occurs. Root cause: `pd.Timestamp(cur_date, tz=ET) + pd.Timedelta(hours=12)` adds an ABSOLUTE 12-hour duration to a midnight-localized instant, which is not wall-clock-preserving when the transition falls between midnight and noon of that date. This is the same bug class as before, reduced from a 126-day persisting drift to a 2-day, non-persisting, single-day edge case (0.9% of the 212 TRAIN days, vs ~59% before).
- Blast radius: both residual dates fall inside TRAIN (before WALL_ELON=2026-04-01); SEALED remains fully clean, consistent with the builder's claim.
- The code comment's claim that "DST transitions correctly yield a 23h/25h block instead of drifting" is not fully accurate -- the block IS 23h/25h, but one of its two boundaries is not actually at noon ET on the transition date, which is a different and much smaller defect than what was claimed fixed.
- Cross-check that the fix is genuinely LIVE (not a no-op): Q1 R1/R4 numbers reproduce bit-for-bit identical to the pre-fix run (they never touch DailySeries, confirmed by grep -- DailySeries appears only at lines 608/643 in the Q2 section), while the Q2 TERTIARY numbers shift very slightly from the "before" table in the task (+0.1348->+0.1333, +0.5069->+0.5038) -- exactly the signature you'd expect from a TRAIN-window fix that changes which days/content feed the B1-B4/S2 hyperparameter selection and weekly refits. Both halves of this cross-check are internally consistent and independently confirm the fix is live and correctly scoped.
- Verdict on F1: resolved for its stated purpose (no SEALED headline was ever at risk, and now the TRAIN-side drift is reduced ~60x). New finding below (residual DST edge) is the honest, smaller replacement.

**F2 (B5/MARKET baseline, Class C MEDIUM) -- FIXED.**
Implemented at lines 176-227, wired into r1_markov/run_q1 at 298/590, called only for elon_2day per prereg scope. Re-ran build_r1_market_baseline + market_probs_to_tercile directly: reproduces n_admissible=65/66 and sealed skill=-0.3669 CI[-0.5641,-0.1081] n=27, jackknife sign holds, exactly. Reuses L.load_prices/L.market_bracket_probs (the trusted, unmodified primitives; price_at uses searchsorted(...,'right')-1, causal, no look-ahead). Reallocation-robustness probe: built an independent alternative reallocation (assign each Polymarket bracket's full probability to whichever tercile bin contains the bracket's midpoint, instead of the shipped uniform-integer-mass-overlap approximation) and re-scored: skill=-0.4332 CI[-0.6721,-0.1187] n=27 -- same sign, same "CI excludes zero, negative" conclusion, similar magnitude. The B5 finding (R1 Markov loses to the market) is not an artifact of the reallocation method. Scope disclosure present in "What this does NOT show" (not scored for trump_7day, not scored anywhere in Q2, both explicitly justified).

**F3 (missing jackknife on S3/S4, Class D MEDIUM) -- FIXED.**
Re-ran s3_gap_rule, s4_formal_burst_rule, and s4_literal_calendar directly against real data (not from CSV, from the live functions) and got jackknife outputs identical to what the prior audit computed by hand as an out-of-band check: S3 checkpoint-0 sealed +0.0210->+0.0078 (sign holds), S4 formal sealed -0.4014->-0.4655 (sign holds, strengthens), S4 literal sealed LOO n=8 median range [15.0,24.0] with 4/8 single-day drops erasing the gap. These are now first-class artifact outputs (q2_s3_literal_2h.csv for the literal-threshold table; S3/S4-formal jackknife lands in the table DataFrames embedded in summary.md), not something only the auditor could reconstruct.

**F4 (undersized sealed slice with no sentinel, Class D MEDIUM) -- FIXED.**
s4_literal_calendar now emits below_success_floor=bool(n_big < SUCCESS_N_FLOOR) (True for sealed n=8) and a full sealed_loo diagnostic + sealed_corroboration_note sentinel string, both printed verbatim into summary.md ("SEALED corroboration slice sentinel: noise (n=8, below success floor..."). The bolded Verdict (c) prose now explicitly states the FORMAL test (n=13, floor-clearing) carries the claim and the literal test only "corroborates the direction, it does not independently prove it." Matches the fix claim exactly.

**F5 (undisclosed base-rate shift, Class A LOW-MEDIUM informational) -- FIXED.**
compute_base_rate_shift (line 650) is called fresh in main() and its output is the FIRST content section of summary.md ("Data note -- Elon's activity level itself shifted between TRAIN and SEALED"), computed this run (44.2->30.7, matches the run's own log line and RUN_META headline field elon_mean_daily_posts_train_vs_sealed). Confirmed by code read that its only consumer is the summary-text formatting block -- it feeds no threshold, no bin edge, no model selection anywhere in the script (grep for base_rate_shift/brs shows it used only in write_summary).

## New findings from this re-audit (adversarial dynamic testing)

[Class A] [LOW] Residual DST-anchoring imprecision on the two literal transition dates (not fixed by the 2026-07-31 patch).
Evidence: independent from-scratch re-implementation (see F1 above) shows 2025-11-02 and 2026-03-08 still open 1 hour off noon ET (11:00 and 13:00 respectively) because the fix adds pd.Timedelta(hours=12) (absolute duration) to a midnight-localized pd.Timestamp, which is not wall-clock-safe across the exact transition instant.
Why it matters: both dates are TRAIN-only (before WALL_ELON=2026-04-01), affect 2 of 212 TRAIN days (0.9%), and do not change any reported headline (verified: Q1 numbers that never touch DailySeries are bit-identical to pre-fix; Q2 numbers that do use DailySeries shift only slightly, consistent with the bulk of the drift being fixed). Not fatal, does not change any verdict.
Fix: localize noon directly (e.g. pd.Timestamp(f"{cur_date} 12:00:00", tz=ET) or .replace(hour=12) on the ET-localized midnight) instead of midnight + Timedelta(hours=12).

[Class D] [LOW] Q2 PRIMARY verdict prose does not flag how close the CI sits to a formal LOSES.
Evidence: skill=-0.0312, CI=[-0.06578, +0.00024] -- the upper bound is one part in ~4,000 from crossing zero into a formally significant loss. success_line() returns the same word ("unproven vs B4 (CI includes zero)") regardless of how close the CI sits to a boundary, so the prose reads identically to a comfortably-neutral result. The exact numbers ARE printed in the same sentence (nothing is hidden), and the machine-readable RUN_META.headline.q2_primary_beats_hmm = false is unambiguous, so no automated "lock this model" gate would be misled. Human readers skimming the word "unproven" could take more comfort than the number supports.
Why it matters: this is exactly the "reproduced-but-invalid can read as reassuring" risk the audit brief asks to guard against, even though scope (b) exempts this from the Pass-B fill/fee battery -- it's a Pass-D statistical-honesty framing issue, not a wrong number.
Fix: no code change needed; add one explicit sentence to future writeups when a headline CI sits within about 1% of its own width from a boundary ("this is a hair from a formal loss, treat the point estimate as the operative signal, not the CI-inclusion label").

[Class C] [LOW, informational, not this builder's fault] Stale line-number reference in the DailySeries docstring.
Evidence: the comment at lines 619-621 cites "pattern_discovery_2026-07-26.py::DailySeries (lines 96-104)" as still buggy. Independently read that file: its DailySeries (now at lines 113-138) uses add_days_et() (line 101, pd.DateOffset(days=n) on an ET-localized timestamp, explicitly commented "NEVER ts_unix + n * 86400") -- i.e. it has ALREADY been independently fixed, by a different code pattern than this script's fix, presumably by the concurrent builder noted in the task brief. File-boundary rule respected: regime_discovery_2026-07-29.py never imports or writes to pattern_discovery_2026-07-26.py; this is a stale comment, not an out-of-scope edit.

## What was checked and passed
- All headline numbers in the reproduction table above, reproduced exactly (not approximately) from per-row CSVs or live re-execution of the actual scoring functions.
- DST fix confirmed LIVE via a two-part cross-check: Q1 (never touches DailySeries) is bit-identical pre/post-fix; Q2 (uses DailySeries) shifts by a small, fix-consistent amount.
- B5 sign and "LOSES to market" conclusion confirmed robust to an independently-built alternative tercile-reallocation method.
- Jackknife additions on S3/S4-formal/S4-literal reproduced exactly by re-running the live functions, matching the prior audit's hand-computed out-of-band numbers.
- F4 sentinel and F5 disclosure confirmed present, accurate, freshly computed, and feed no downstream model/threshold/gate.
- Trial count 63 independently re-summed from the by-method breakdown and confirmed logically invariant to the DST fix (candidate-list lengths, not data values, drive the count).
- THE WALL: B5 uses the pre-existing causal price_at/market_bracket_probs primitives (searchsorted 'right'-1, no look-ahead); jackknife additions are post-hoc diagnostics on already-sealed-scored results, no leak; no new hyperparameter or threshold was re-selected on anything but TRAIN in this re-run.
- Prereg file (prereg/regime_discovery_2026-07-29.md) mtime (11:44:38) predates the re-run (13:02-13:05) and its content (WALL dates, SUCCESS_N_FLOOR=10, B5 scope text) matches what the script/summary reference -- not edited to match results.
- File scope: regime_discovery_2026-07-29.py writes only to regime_out/; imports (read-only) pattern_discovery_lib.py/pattern_discovery_methods.py; never touches pattern_discovery_2026-07-26.py. That file's own DST fix (confirmed present, different code pattern) is independent, concurrent work per the task brief, not an out-of-boundary edit by this builder.
- RUN_META present, model_version matches locked_pace.MODEL_VERSION exactly -- no locked-model drift.
- Sanity cross-checks: classification-metrics n=348 = 87 sealed days x 4 checkpoints (exact); B1 sealed accuracy/logloss at the earliest checkpoint (0.540/1.211) matches q2_accuracy_by_hour.csv exactly.

## What could NOT be checked
- Whether fully eliminating the newly-found 2-day residual DST edge (see finding above) would change any TRAIN-side sweep argmax (X_frozen, p75, ridge alphas, HMM n_states, K sections) -- not re-run with a fully-corrected DailySeries; judged low-risk given the tiny (2/212 day) perturbation and explicitly flagged as a follow-up, not executed here.
- R2 (ACF/PACF/periodogram) was not independently re-derived this pass (code-read only, unchanged from the prior audit, not part of any success criterion).
- q2_reliability_*.csv calibration diagrams were not individually re-scored (presence and non-empty confirmed, contents not statistically re-derived).
