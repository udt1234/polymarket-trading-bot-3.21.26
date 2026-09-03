# Re-audit: pattern_discovery_2026-07-26 (post-cadence pattern discovery, scope class b)

Auditor: @backtest-auditor. Date: 2026-07-29 (re-audit after FAIL).
Prior audit (FAIL/BLOCK): `_DataMetricPulls/pacing_backtest/audits/pattern_discovery_2026-07-26.md`
Pre-registration: `_DataMetricPulls/pacing_backtest/prereg/pattern_discovery_2026-07-26.md` (mtime 2026-07-26 11:21, unchanged since original run - confirmed not edited to match results)
Fresh run: completed 17:41, runtime 1920s, full cold recompute (all 4 checkpoints re-computed 17:07-17:41 on 2026-07-29, none stale from the 07-26 run)
Outputs: `pattern_discovery_out/{per_row.csv, pattern_discovery_2026-07-26.run_meta.json, summary.md}`, pre-fix outputs preserved at `pattern_discovery_out/_prefix_backup_2026-07-26/`

## VERDICT: WARN

The prior FATAL (Finding 1, B4 admissibility) is CONFIRMED FIXED by independent reproduction, not just re-reading the disclosure text. The corrected headline ("no tradeable edge on any target") is real and reproduces exactly from `per_row.csv`. No new fatal finding. Two new non-fatal findings surfaced during this re-audit (one Medium, one Low) that were not part of the original FAIL and are not present in the builder's change list; neither invalidates the headline, but both should be closed before this is treated as fully settled.

## Reproduced headline number: YES

Independently rebuilt `compute_skill_table`'s aggregation from scratch in a standalone script (not copy-pasted from the runner) and ran it directly against `per_row.csv`:

| target | n_full (mine / reported) | n_b4_admissible (mine / reported) | B1 vs B4 skill (mine / reported) | PRIMARY beats-B4 (mine / reported) |
|---|---|---|---|---|
| elon_2day | 28 / 28 | 19 / 19 | -0.3722 / -0.3722 | none / none |
| trump_7day | 20 / 20 | 20 / 20 | -0.7279 / -0.7279 | none / none |
| elon_7day | 19 / 19 | 3 / 3 | n/a (flag only) | none / none |

Also recomputed B3 vs B4 for elon_2day sealed: -0.3359 (mine) vs -0.3359 (reported), exact match. All three `primary_success_*_beats_B4` RUN_META flags reproduce as `"none"` from an independent script, matching the emitted JSON exactly.

Critically, my independently-recomputed B1-vs-B4 = -0.3722 for elon_2day sealed is the same number the prior FAIL audit's own dynamic sign-flip probe produced by hand on 2026-07-26 ("hardened -0.3722"). The fixed pipeline now reproduces the auditor's own hardened ground truth automatically, in production code, rather than requiring a manual override. That is the strongest possible confirmation available.

## Findings (most severe first)

### [CLASS A, prior FATAL] RESOLVED - B4 admissibility gate is implemented correctly and verified by independent recompute
Where fixed: `pattern_discovery_2026-07-26.py:1076-1081` (post-hoc `b4_admissible` column, derived from B4's own winner-row `market_price`, NaN iff never priced) and `:701-756` (`compute_skill_table` uses `ll_unit_b4`, filtered to admissible `(auction_slug, checkpoint_hours)` keys before the per-auction mean, for every pair where `baseline == "B4"`, and the full sample otherwise).

Verified, not just read:
- Zero rows exist where `b4_admissible=True` but `market_price` is NaN or `model_prob<=1e-5` (checked all 4,084 admissible B4 winner-rows programmatically); the defaulted-to-1e-6 contamination the original FAIL flagged is gone from every admissible comparison.
- Zero rows exist where `b4_admissible=False` but `market_price` is NOT NaN; the flag is derived correctly in both directions.
- Checked B4's own probability construction for a partial-coverage example (8/9 brackets priced): the 8 priced brackets carry their RAW market price unchanged (e.g. winner bracket model_prob == market_price == 0.153846 exactly), and only the single unpriced bracket gets the 1e-6 default. B4 does NOT renormalize its distribution over the priced subset, so admissibility does not backdoor-inflate the market's apparent confidence in the winner. This closes a possible Finding-5-style renormalization concern before it became one.
- Diffed the full `per_row.csv` against `_prefix_backup_2026-07-26/per_row.csv`: B1, B2, B3, M1, M2, M4, M7(M1), and B4's own `model_prob` are 100% byte-identical row-for-row between the pre-fix and post-fix runs (0 rows differ, to the last bit). The fix touched exactly what it claimed to touch and nothing else in the non-M6 methods.
- `n_auctions_full` and `n_auctions_b4_admissible` are reported side-by-side in every headline line of `summary.md` and as sibling keys in the same RUN_META JSON block; confirmed no line anywhere quotes a bare `n=` that could be mistaken for the market-comparison sample size, and `elon_daily`'s `n_auctions_b4_admissible=0` is stated explicitly (not omitted) with zero B4 pairs appearing in that section at all.

Verdict on Finding 1: CLOSED. This was the sole reason for the prior FAIL and it is fixed correctly.

### [CLASS D] MEDIUM (new) - the "NO TRADEABLE EDGE" headline is not scoped to the subset it was actually tested on, and the excluded subset shows a directionally different signal
The B4-admissibility fix is the right thing to do (you cannot score a market comparison where the market never priced the outcome), but dropping those auctions is not statistically inert. Recomputed, for `elon_2day` sealed, the average model-vs-B1 skill split by admissibility group:

| group | n auctions | B1 raw logloss | M1 vs B1 skill | M6 vs B1 skill |
|---|---|---|---|---|
| admissible (used for headline) | 19 | 1.121 | -0.061 | +0.079 |
| excluded (winner never priced by market) | 9 | 1.698 | +0.266 | +0.289 |

On the 9 auctions the market never priced the eventual winner (invisible to the PRIMARY/B4 test by construction), the naive baseline itself does noticeably worse (1.698 vs 1.121 nats) and the models beat naive extrapolation by a wider margin than on the admissible subset. This is exactly the shape you'd expect if the excluded auctions are the thin/illiquid-bracket cases, which is also precisely where a real informational edge (if one exists) would matter most, because it's the corner the market doesn't reach.

This does NOT flip the "no beats-B4" finding for the tested subset (B4 genuinely cannot be scored on the excluded 9; the fix was still correct to drop rather than default them). But `summary.md`'s "NO TRADEABLE EDGE" line for `elon_2day`/`elon_7day` reads as an unqualified claim, and a reader who doesn't carry the n_full vs n_admissible distinction all the way through could walk away believing "no edge, full stop" when the honest statement is "no proven edge on the actively-traded ~68% of auctions; the study is silent, not clean, on the ~32% the market never priced, where naive-vs-model gaps are larger." Given this project's own standing rule ("a baseline that itself looks impossibly good is a red flag, not a triumph") the mirror-image discipline applies here: an accidentally-too-narrow comparison set is also worth a flag, not silent acceptance.

Fix: add one sentence to the `elon_2day`/`elon_7day` sections of `summary.md` stating the admissible-vs-excluded model-lift asymmetry above, so "no tradeable edge" is read with its correct scope.

### [CLASS C] LOW (new) - shared global RNG across M5 and M6 means an M6-only bugfix silently perturbed M5's Monte-Carlo output, undocumented
`pattern_discovery_methods.py:29`: `RNG = np.random.default_rng(20260726)` is a single module-level generator consumed by both `predict_M5_sim` (line 457, `RNG.binomial(...)`) and `_hawkes_thin_sim` (lines 603/610, M6's Ogata thinning). The Finding-3 fix changes how many random draws `_hawkes_thin_sim` consumes per call (the whole point of the fix: simulations that used to run away to ~1500 events now stop around ~85-100, consuming far fewer draws). Since the two methods share one RNG stream, this shifted every subsequent M5 draw for the rest of the run.

Confirmed by diff: M5's `model_prob` differs on 6,588 of 21,871 rows (max abs diff 0.79) between pre-fix and post-fix runs, even though M5's own code (`fit_M5`/`predict_M5*`) is untouched; this is not disclosed anywhere in the builder's change list (which names only Findings 1/2/3).

Checked whether this changes any conclusion: no. M5 vs B1 for elon_2day sealed went from skill=-2.7196 (pre-fix) to -2.6816 (post-fix): same sign, same order of magnitude, both losing badly and consistent with M5's established pattern of losing everywhere in both this run and the prior audit. The RNG cascade is real but benign here.

Why it still matters: a shared RNG object means the next single-line fix to any Monte-Carlo method will again silently perturb an unrelated method's numbers. That breaks the "diff the ledger to confirm only the declared fix changed" audit technique used throughout this re-audit (it worked this time only because I checked verdict-stability by hand; it would not scale to a smaller, more marginal effect). Fix: give each Monte-Carlo method its own seeded generator (e.g. `np.random.default_rng(20260726 + <method-specific offset>)`), not one shared stream.

### [CLASS D] Confirmed resolved - M6 (Hawkes) miscalibration was a real, reproducible bug, and the fix lands in a plausible (not suspiciously good) place
Code review of `_hawkes_thin_sim` (`pattern_discovery_methods.py:563-617`): this is now a textbook-correct Ogata modified thinning algorithm. `R` (self-excitation accumulator) is decayed to the candidate time on every iteration whether the candidate is accepted or rejected (previously only decayed on acceptance, the confirmed bug), and the Ogata upper bound `lam_bar = mu*mult_max + alpha*R` uses `mult.max()` over the whole candidate window rather than the current-hour multiplier, which is a valid bound since `R` is provably non-increasing absent an accepted event. History seeding (`R0` built from real events up to `T` only) remains causal.

Independently recomputed mean log-loss per method for `elon_2day` sealed directly from `per_row.csv`:
B1: 1.307   B2: 1.688   B3: 1.180   B4: 4.620 (contaminated full-sample; 0.749 on admissible-only)
M1: 1.263   M2: 1.480   M4: 1.181   M5: 3.988   M6: 1.160   M7(M1): 1.191   M7(M6): 1.003

M6's mean log-loss is now 1.16, squarely competitive with B1/B3/M1/M4, not suspiciously good (it doesn't win the headline anywhere) and nowhere near the old 12.19. This is the correct shape for "a bug that made a real-but-unremarkable model look catastrophic is now fixed to look unremarkable," not "a bug fix that conveniently produced a new winner." Old backup's `M6 vs B4` for elon_2day sealed was -7.5116 (matches the FAIL audit's own quoted number exactly); new run's is -0.2929, both directionally the same (M6 still loses to B4) but by a plausible margin instead of an absurd one.

### [CLASS D] Confirmed resolved - trial_count now includes M6/M7(M6) correctly on both cold and warm runs
Code review of `main()` (`pattern_discovery_2026-07-26.py:1024-1063`) and `_run_checkpointed` (`:970-999`): `_trial("M6")` / `_trial("M7(M6)")` calls sit in `main()`, strictly outside the `n0`/`by0` snapshot window that `_run_checkpointed` pickles per target. This means they fire exactly once per target every time `main()` runs, regardless of whether that target's rows came from a fresh compute or a cache hit, confirmed by inspecting the snapshot boundaries, not just trusting the comment. Arithmetic check: 32+38+4+12+8+4+24+3 = 125, matching `trial_count` in RUN_META exactly. `M6:4` (once per target) and `M7(M6):3` (auction targets only, correctly excluding elon_daily) both check out against the call sites.

## What was checked and passed (full re-verification, cold recompute)

- Reproduction: all three `primary_success_*_beats_B4` flags independently recomputed as "none" from `per_row.csv` using a standalone script (not the runner's own code, to avoid circular trust). Exact match.
- Token->price coverage (Pass A): same underlying gap as before (Elon 63.6%/78.2% winner-missing, Trump 0%), now correctly consumed downstream instead of defaulted. Confirmed programmatically: 0 admissible rows have a NaN/defaulted winner price; 0 inadmissible rows have a real price.
- B4 non-renormalization: spot-checked a partial-coverage row; B4 uses raw market prices for priced brackets (no renormalization over the priced subset), so admissibility gating cannot artificially flatter or deflate the market's apparent skill.
- Surgical-fix diff: B1/B2/B3/M1/M2/M4/M7(M1)/B4-model_prob are byte-identical pre- vs post-fix (0 of ~22k rows each differ); the fix touched only what it claimed.
- THE WALL / causality: `priors = [p for p in units if p["e"] < u["s"]]` (auction-level) unchanged; `fit_M6(priors, post_ts, u["s"])` and `_circadian_mult(..., before_ts=u["s"], lookback_days=120)` both look backward from `u["s"]` only, confirmed by reading the fix's surrounding code, not assumed from the prior pass.
- Noon-ET window parsing: `pattern_discovery_lib.py` mtime unchanged since 2026-07-26 12:04 (before this fix round); not touched, previously-cleared verdict stands.
- model_version drift: RUN_META "ensemble-cap1.5+calibsigma.2026-07-11" == `locked_pace.py:22 MODEL_VERSION` exactly. No drift.
- WALL dates / checkpoints: WALL_ELON=2026-04-01 ET, WALL_TRUMP=2026-01-01 ET, CHECKPOINTS_2DAY=[6,12,24,36], CHECKPOINTS_7DAY=[24,48,84,120,156], all match the pre-registration exactly, unchanged constants.
- Block-bootstrap-by-auction + single-outlier jackknife: code unchanged (`block_bootstrap_ci`/`jackknife_drop_best`), block_size=7 for elon_daily / 1 for the three auction targets per the pre-registration's stated rho=0.44 daily-autocorrelation adjustment; jackknife sign-flip results are printed and honestly reported (e.g. multiple "SIGN FLIPS on dropping best auction" entries retained, not hidden).
- Thin-sample disclosure: `elon_7day` sealed n_auctions_b4_admissible=3 and `elon_daily`'s (both spans) n_auctions_b4_admissible=0 are both stated plainly in RUN_META and `summary.md`'s "too thin to call" section, not silently omitted.
- Multiple testing: 125 trials against n=19-20 admissible auctions for the PRIMARY criterion. The PRIMARY/SECONDARY/TERTIARY criteria are each a single pre-registered comparison (not an argmax-over-125 selection), and the finding is negative (market beats or ties every method, with several CIs entirely below zero rather than merely "unproven"); this exposure profile is a Type-II (underpowered) risk, not a Type-I (spurious-discovery) risk, and is honestly labeled as such.
- Prereg integrity: `prereg/pattern_discovery_2026-07-26.md` mtime is 2026-07-26 11:21, before both the original run and this fix round; not edited to match results.
- Cold-recompute integrity: all 4 `checkpoints/*.pkl` files timestamped within the declared 17:07-17:41 run window on 2026-07-29; confirms this was genuinely a full recompute, not a reuse of stale pre-fix cached rows for M6/M7(M6).

## What could NOT be checked

- Did not re-verify `fit_M2`/`select_M2`/`fit_M4`/`select_M4`/`fit_M5`/`select_M5` internals beyond confirming their output rows are byte-identical to the pre-fix run (strong indirect evidence their code is untouched, but did not re-read every line of those functions in this pass; the original audit already reviewed the hyperparameter caps and those are unchanged files).
- Did not re-derive why the Elon canonical/prices winner-token gap is 63.6%/78.2% at the root-cause (canonical-data-layer) level; this remains an open item flagged in the prior audit as out of scope for this backtest's own code, and is unchanged by this fix round.
- Did not exhaustively diff every one of the ~225k rows' B2/B3/M2/M4/M7(M1) values by hand beyond the aggregate byte-identity check (0 rows differ); treated the programmatic full-column diff as sufficient rather than re-deriving each formula from scratch a second time.
- Did not re-run the script myself end-to-end (a second 1920s cold run would re-derive the same `per_row.csv`; reproduction was done from the emitted ledger per the audit protocol's first-class path).
