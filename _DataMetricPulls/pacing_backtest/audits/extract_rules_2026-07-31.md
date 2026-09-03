# Audit: extract_rules_2026-07-29.py (rule-extraction pass over pattern_discovery_2026-07-26.py)

**Date:** 2026-07-31
**Scope class:** (b) pure forecast-accuracy / calibration diagnostic, descriptive sub-case (extraction, not a new study). Pass B fill/fee battery N/A. Pass A/C/D applied in full.
**Auditor:** @backtest-auditor

## VERDICT: WARN

No fatal finding. Headline number reproduces exactly. One material Class D finding not
disclosed anywhere in the artifact itself (headline lift is largely a restatement of the
parent study's own declared trivial null, not primarily a new 4-way interaction), plus two
low-severity disclosure gaps. Nothing here should be read as "the rule is fabricated" -- the
numbers are real and reproducible -- but the human-readable framing oversells the rule's
novelty versus what a one-line threshold already gets you at that same decision time.
**Reproduced headline number: YES.** Refit the elon_daily CART myself from
`pattern_discovery_2026-07-26.py::build_targets()` plus the exact frozen hyperparameters,
applied `clf.apply()`, filtered to leaf 7:
- train: n=44, hit=42/44=95.4545% (reported 95.5%) -- exact match
- sealed: n=41, hit=39/41=95.1219% (reported 95.1%) -- exact match
- lift_sealed = 0.9512195121951219 / 0.40229885057471265 = 2.3644599303135885 -- exact
  bit-for-bit match to RUN_META `top_rule_sealed_lift`.

## Findings

### [D] [MEDIUM] Headline "2.36x lift" is mostly the parent's own trivial null, not new discriminative structure -- not disclosed anywhere in the artifact
Evidence (recomputed against the reproduced train/sealed leaf-7 rows):
- Rows in leaf 7 are only evaluated at checkpoints 18/21 (06:00/09:00 ET next day). At that
  decision time, the parent's own disclosed trivial null is "count_so_far alone explains
  R2=0.764 (h18) / 0.856 (h21) of final count" (prereg-declared, per task context).
- A single-feature threshold rule fit on the SAME hour-18/21 pool (count_so_far <= 12,
  chosen to maximize train hit rate subject to n>=25 to match TREE_MIN_SAMPLES_LEAF) gets
  train hit=89.3% (n=28), sealed hit=100.0% (n=25) -- matching or beating leaf 7's 95.5%/95.1%
  using ONE condition instead of four.
- The tree's own coarse root split alone (count_so_far<=32.5, no other conditions) at the
  same hour gets only 45.2% (train) / 51.9% (sealed) -- so the extra conditions are not
  worthless, but the leaf's real edge over "a well-chosen single threshold at that same late
  hour" is small to negative on sealed data.
- Separately: the concern that the reported base_rate (23.1%/40.2%) is an "unconditional,
  diluted-across-checkpoints" denominator that inflates lift is NOT confirmed -- y is defined
  per calendar day (M.label_from_final), identical across all 5 checkpoint rows of that day,
  so the pooled base rate and a checkpoint-18/21-only base rate are mathematically identical
  (verified: both = 23.113%/40.230% exactly). This specific mechanism does not apply here --
  the correct rebuttal is the naive-baseline comparison above, not a base-rate-averaging
  artifact.
- Why it matters: a reader skimming decision_tree_elon_daily.txt or the RUN_META headline
  sees "4-condition rule, 2.36x lift, n=41 sealed" and could reasonably infer a genuinely new,
  multi-feature interaction was discovered. The more honest framing is "late in the window
  (06:00-09:00 ET the next day), a low running post count is already a near-deterministic
  signal of a low final count (the parent's own R2 0.764-0.856 finding) -- the tree's extra
  max_posts_60min conditions add modest, not dramatic, lift beyond that."
- Fix: add one line to decision_tree_elon_daily.txt / RUN_META notes stating the naive
  single-threshold comparison, or at minimum caveat that leaves gated on
  hours_into_window>16.5 inherit most of their accuracy from the parent's declared
  late-window R2 null.
### [C] [LOW] Rule-text phrasing implies a ~04:30 ET decision time; actual fixed checkpoints are 06:00/09:00 ET
Evidence: `format_condition()` (`extract_rules_2026-07-29.py:214-215`) renders
`hours_into_window > 16.5` literally as "hours into window > 16.5h".
Fix: have format_condition for hours_into_window snap to the nearest
evaluated checkpoint hour, or append the checkpoint-derived clock time inline.

### [D] [LOW] elon_2day rules carry no lag-1 autocorrelation n_eff caveat; daily rules do
Evidence: run_tree_extraction("elon_2day", n_eff_frac=None) (extract_rules_2026-07-29.py:309-310)
vs n_eff_frac=DAILY_N_EFF_FRAC for elon_daily (line 308). DAILY_N_EFF_FRAC=0.39 is correctly
sourced from prereg/pattern_discovery_2026-07-26.md:74 ("daily counts autocorrelate at lag-1
rho=0.44, N_eff about 39% of nominal") -- that prereg line is explicitly scoped to "the daily
substrate", so declining to reuse it for elon_2day (overlapping-window substrate, different and
unquantified autocorrelation) is the conservative/correct call, not a fabrication. But it does
mean ranked_rules.csv rows sourced from CART-elon_2day (e.g. M2-elon_2day-leaf7, n_sealed=67)
report a flagged/unflagged status purely off raw n, with no disclosed discount for the likely
autocorrelation in that substrate either. Non-fatal, since MIN_N_FLAG=30 already gates the
flagging: fix is cosmetic (an explicit note that n_eff is not quantified for this substrate)
rather than a computational one.
## What was checked and passed

- Headline rule coherence (Pass A, "the single most important thing to check"). Reproduced
  leaf 7's actual per-row count_so_far distribution from raw data (not present in the
  provenance CSV as shipped -- recomputed via M.build_features using the exact same call the
  script makes). TRAIN: count_so_far range 6-26, 0/44 rows violate (count_so_far >= 27 while
  predicted <27). SEALED: range 5-30, 2/41 rows violate (count_so_far=30, correctly scored as
  misses in the 95.1% hit rate, not silently miscounted -- those 2 rows have y=1, i.e. the
  tree's own miss accounting is honest). Verdict: the benign case. The count_so_far<=32.5
  split is a global tree-node threshold inherited from an ancestor that primarily separates
  OTHER leaves (leaf23/24 use it to route the 57+ bracket); leaf 7's own conditional data is
  concentrated far below 27 (median 13-14) because of the additional max_posts_60min/hours
  conditions. The leaf-to-outcome mapping is NOT defective; it is a modal/majority statistical
  rule (not a deterministic implication), and its stated hit rate (below 100%) already
  accounts for the handful of rows where a late burst pushed the day over the predicted
  bracket.
- Refit fidelity vs disclosed hyperparameters. Cross-checked every hardcoded constant
  (DAILY_M2_HP, DAILY_M3_K, DAILY_M4_STATES, DAILY_M5_HP, E2D_M2_HP, E2D_M4_STATES,
  TREE_MAX_DEPTH, TREE_MIN_SAMPLES_LEAF) against pattern_discovery_out/run_reaudit_fix.log
  lines 11 and 15, and pattern_discovery_out/summary.md lines 406-427 (Per-method estimator
  disclosure). Exact match on every value, both substrates.
- THE WALL. edges = M.make_bin_edges(finals_train, hp K) computed from finals_train only;
  clf.fit(Xtr, ytr) fit on train rows only; sealed rows scored with the SAME frozen edges
  (code comment confirms this is intentional, no leak). M3 centroids (fit_M3_centroids), M4
  HMM (fit_M4), M5 GBM (fit_M5) all called with daily_train/e2d_train only -- never
  daily_sealed/e2d_sealed. Train/sealed row sets in the persisted CSVs are disjoint by
  construction (span column, no unit appears in both). prior_final_fn/trailing_fn are
  imported unchanged from the already-4x-audited parent (not reimplemented) -- zero
  transcription risk.
- M3 H=1 tie-artifact claim (self-reported by the extraction). Traced predict_M3
  (pattern_discovery_methods.py lines 261-286): at eh=1, cent_partial is a single column, so
  cent_partial divided by its own row-sum equals 1.0 for every cluster with any nonzero
  centroid mass at hour 0, and partial_norm is also 1.0 whenever any posts occurred -- every
  cluster ties at dist=0, argmin silently returns cluster 0. Confirmed this is inherent to the
  ORIGINAL study's formula (unchanged, not introduced by the extraction), and confirmed the
  extraction's own H_GRID filtering (recall_df restricted to hours_elapsed greater than 1,
  extract_rules_2026-07-29.py lines 503 and 822) correctly excludes H=1 from every "first
  identifiable" claim.
- Honest negatives, verified not understated.
  - Archetype early-ID: sealed accuracy sits at or below the 25% (k=4) random baseline
    through hour 12 (13.5% to 25.0%), jumps to 59.3% / 89.7% / 92.0% at hours 15/18/21
    (rules_out/day_archetype_early_id_accuracy.csv). Train shows two mild exceptions above
    25% (H=1: 30.6%, H=12: 33.3%) -- the claim is accurate for the decision-relevant OOS
    metric and close on train; not overstated.
  - Hazard model: posts_last_1h feature importance = 0.6983 (hazard_curve.txt line 5) --
    matches the disclosed "about 70%" exactly.
  - elon_2day leaf 4: TRAIN hit=69.2%, SEALED hit=0.0% (decision_tree_elon_2day.txt lines
    38-41) -- exact match.
- Tiny-n discipline. ranked_rules.csv has 22 rows, 15 flagged n<30 (matches RUN_META
  n_rules_flagged_small_n=15). top_rule_by_sealed_lift_n_ge_30 is drawn from the
  n_sealed >= MIN_N_FLAG subset (extract_rules_2026-07-29.py lines 878-879) and correctly
  resolves to leaf7 (n_sealed=41). The tiny-n outlier (M2-elon_daily-leaf23, n_sealed=3,
  lift=14.5x) is the overall number-one row by raw lift but is surfaced SEPARATELY and
  explicitly labeled top_rule_unfiltered_WARNING_tiny_n -- cannot be mistaken for the
  headline. MIN_N_FLAG=30 is a stricter floor than the parent's SUCCESS_N_FLOOR=10
  (pattern_discovery_2026-07-26.py line 65, itself justified against the n=3 /
  25%-false-positive degenerate-CI problem) -- consistent in spirit, more conservative in
  practice, not a contradiction.
- No cherry-picking. All 13 elon_daily leaves and all 5 elon_2day leaves printed, including
  untestable ones (LEAF 12: n_sealed=0, elon_2day LEAF 8: n_sealed=0 -- both explicitly
  reported as "no sealed-span row ever reached this leaf"). All 4 M3 archetypes present in
  both day_archetypes.txt and ranked_rules.csv (cluster 0-3, with no additional filter beyond
  "cluster had at least one train day").
- No tradeability claim leaked. Grepped all of rules_out/ for profit, ROI, P&L, tradeability,
  dollar signs, buy, sell, bet, wager language -- the only hits are explicit disclaimers
  (no P&L, no fills, no tradeability claim attached to any rule; a descriptive property of
  shape structure, not a live bet), never an assertion of edge.
- No price-data dependency. FEATURE_NAMES and M5_FEATURE_NAMES
  (pattern_discovery_methods.py lines 40-53) contain zero price-derived fields -- all are
  post-count and timing features. The single "price" hit in pattern_discovery_methods.py is
  an unrelated comment about a different, unused-here baseline. Confirms the 2026-07-30
  canonical price-layer rebuild (winner-coverage going from 63.6% / 78.2% / 0.0% missing to
  0.0% missing on all three) is correctly irrelevant to this pass.
- File-scope compliance. By code inspection every write call in extract_rules_2026-07-29.py
  targets OUT_DIR (rules_out/) only -- no other write path exists in the file. git status is
  inconclusive on its own (everything in pacing_backtest/ is untracked, so it cannot
  distinguish "touched" from "never-committed"), so mtimes were used instead:
  pattern_discovery_2026-07-26.py, pattern_discovery_lib.py, pattern_discovery_methods.py,
  and prereg/pattern_discovery_2026-07-26.md all predate the extraction script's own mtime
  and were not modified by it. pattern_discovery_out/checkpoints and
  run_postcoveragefix_2026-07-31.log DO carry a same-day-later mtime, but this matches the
  task's disclosed concurrent "parent study re-run on repaired data" (separate process,
  confirmed by the log filename itself), not this script -- which, again, has no code path
  capable of writing there. combo_out/ and regime_out/ also show same-day mtimes, consistent
  with the disclosed two concurrent builder agents (bracket_combo_ev_2026-07-29.py,
  regime_discovery_2026-07-29.py) -- neither path is referenced anywhere in
  extract_rules_2026-07-29.py.
- RUN_META present and compliant. model_version equals ensemble-cap1.5+calibsigma.2026-07-11,
  matching locked_pace.MODEL_VERSION by construction (run_meta.py pulls it directly from the
  import, not a literal). scope correctly labeled descriptive/extraction. fills correctly set
  to N/A with justification. trial_count=0 correct (zero hyperparameter search performed).
  top_rule_sealed_n and top_rule_sealed_lift both reproduced exactly.
- n_train/n_sealed reproduction. elon_daily: 212/87 reproduced exactly (RUN_META notes
  explain the 212 vs the parent's stricter walk-forward-scoring subset of 198, arithmetic
  checks out: 212 minus 198 equals 14, which equals 2 blocks of 7 days, matching the
  disclosed reason). elon_2day: 38/28 reproduced exactly, matches disclosed run.
  DAILY_BRACKETS assert (extract_rules_2026-07-29.py lines 137-138) passes and matches the
  disclosed run's brackets exactly.

## What could NOT be checked
- Did not independently re-verify the parent study's own R2=0.764/0.856 trivial-null figure
  from scratch (treated as given per task framing and prior 4x-audited parent); used it only
  as the comparison anchor for the naive-baseline check above.
- Did not verify hmmlearn/sklearn version pinning reproduces bit-identical HMM/GBM fits
  across machine/environment (only re-ran the CART, which is what the headline number depends
  on, plus spot-checked the HMM/hazard numeric outputs against the script's own printed
  values -- did not independently refit M3/M4/M5). Low risk: these are standard sklearn and
  hmmlearn estimators with random_state pinned, and none of the three honest-negative claims
  verified (archetype accuracy, hazard feature importance, elon_2day leaf 69.2 to 0.0) depend
  on environment-sensitive floating point beyond what is already printed in the shipped output
  files.
- Did not confirm the two concurrent builder agents' outputs (combo_out/, regime_out/) are
  themselves sound -- out of scope for this audit (different scripts, not requested).
