# Audit: extract_rules_2026-07-29.py (fresh audit, post-DST-fix / frozen data layer)

Date: 2026-07-31 (fresh audit -- prior two logs, extract_rules_2026-07-31.md and
extract_rules_2026-07-31_reaudit.md, are SUPERSEDED per the coordinator's own supersession
notice; old leaf4/leaf7/leaf11/leaf15 identifiers no longer exist and were not reconciled
against, per instructions)
Scope class: (b) pure forecast-accuracy / calibration diagnostic, descriptive sub-case
(extraction over an already-fit study). Pass B fill/fee battery N/A. Pass A/C/D applied in
full.
Auditor: @backtest-auditor

## VERDICT: WARN

No fatal finding. Every reported number reproduces exactly from an independent from-scratch
refit (not just re-reading the shipped CSV), determinism is confirmed directly (re-ran the
script and diffed the entire rules_out/ directory byte-for-byte against the shipped copy: 0
differences), hyperparameters are confirmed against the parent's own ground-truth log (not
just the extraction script's self-report), THE WALL holds, file scope is clean, and there is
no cherry-picking and no tradeability claim.

However, two NEW (this-round) Class D findings, both HIGH severity, undercut the central
conclusion the naive-baseline apparatus exists to support (N rules carry real information
beyond a simple running-count threshold):

1. The lone reliable-n (n_sealed>=30 auctions) survivor, leaf6, has an incremental-lift-vs-
   naive whose auction-level bootstrap CI straddles 1.0 (no edge) -- the point estimate 1.041x
   is not distinguishable from noise at this n. The artifact never computes or discloses this
   CI; the jackknife it does print is of the raw hit rate, not of the comparison against the
   naive baseline, so it cannot and does not detect this.
2. leaf9 (1.451x, the single largest margin) is literally nothing but a two-sided band on
   count_so_far (posts so far greater than 32.5 AND less-or-equal 44.5, no other feature).
   Both shipped naive baselines (1-feature and 2-feature) can only ever search ONE-SIDED
   thresholds -- confirmed by direct code inspection, which only ever compares "<= v" or
   "> v", never a band on the same feature. A one-sided threshold is structurally unable to
   isolate an interior (middle) ordinal bin as well as a band can, so leaf9 "beating" it is
   close to mechanical, not a sign of extra discriminative information. Dynamically confirmed:
   an ad hoc two-sided band search on count_so_far ALONE (same TRAIN-fit/frozen/sealed-applied
   discipline, min_n=25) finds the interval [31,32] and scores 85.7% sealed (n=8 auctions) --
   within about 5 points of leaf9's own 90.5% (n=17 auctions), using the identical single
   feature. The 2-feature "harder" adversary does not fix this either (it still only combines
   two one-sided cuts on two DIFFERENT features, never a band on one), which explains why
   leaf9 -- which has zero relationship to max_posts_60min -- still clears the burst-aware bar:
   it is the same structural blind spot, not independent validation.

Neither finding is fatal: this remains a pure descriptive/interpretability pass with no P&L or
tradeability claim, every raw number is real and reproducible, and the underlying facts (leaf
membership, hit rates, n's) are all correct. What is wrong is the CONFIDENCE the SURVIVES /
beats-naive binary verdict conveys for these two specific leaves, which the artifact states as
settled facts rather than as a mechanically-inflated margin (leaf9) and a statistically
unproven one (leaf6).

Reproduced headline number: YES, by full independent re-derivation (not just re-reading the
CSV) -- reimported pattern_discovery_2026-07-26.py build_targets(), refit the CART from raw
data with the disclosed hyperparameters (K=3, ccp_alpha=0.01636, max_depth=4,
min_samples_leaf=25), reproduced the exact tree structure (export_text byte-identical to
decision_tree_elon_daily.txt) and ALL SIX elon_daily leaves' n_train/n_sealed (auction-count)/
hit_train/hit_sealed bit-for-bit:
- leaf4: n_tr=42 n_se=22 hit_tr=83.33% hit_se=89.19% -- exact match
- leaf5: n_tr=73 n_se=45 hit_tr=52.89% hit_se=16.30% -- exact match
- leaf6: n_tr=83 n_se=41 hit_tr=80.09% hit_se=84.07% -- exact match (the n_sealed>=30 headline)
- leaf7: n_tr=145 n_se=44 hit_tr=48.02% hit_se=55.97% -- exact match
- leaf9: n_tr=91 n_se=17 hit_tr=50.29% hit_se=90.48% -- exact match
- leaf10: n_tr=59 n_se=7 hit_tr=96.38% hit_se=100.0% -- exact match

The scorecard (14 rules total, 4 survive / 9 collapse / 1 untestable, 10/14 flagged small-n)
reproduces exactly by independently counting ranked_rules.csv's beats_naive_sealed and
flag_small_n columns against RUN_META. The three named daily survivors' n_sealed/hit/
incremental-lift/jackknife numbers in the task brief (leaf6: 41/84.1%/1.041x/83.3-88.0%; leaf9:
17/90.5%/1.451x/89.5-95.0%; leaf4: 22/89.2%/1.080x/87.5-94.3%) all match ranked_rules.csv
exactly, row for row.

## Findings

### [D] [HIGH] leaf6's incremental-lift-over-naive is not distinguishable from no-edge at auction-level bootstrap -- the artifact's only reliable-n survivor rests on an unproven margin
Evidence: independent auction-level bootstrap (5,000 resamples, resample leaf6's own 41 sealed
auctions and the 87-auction naive comparison pool independently with replacement, same naive
threshold count_so_far<=3.0 the shipped script fit):
- Reported point estimate: incremental_lift_over_naive = 1.0409 (sealed hit 84.1% vs naive
  80.8%, n=41 auctions vs n=18 auctions).
- Bootstrap 95% CI on incremental_lift_over_naive: [0.81x, 1.44x] -- straddles 1.0 (no
  incremental edge) comfortably. P(incremental_lift <= 1.0) = 40.5%. Median of the bootstrap
  distribution = 1.035x.
- Bootstrap 95% CI on the absolute hit-rate difference (rule minus naive): [-17.6pp, +26.9pp]
  -- straddles zero.
- The artifact's own jackknife (leave-one-auction-out) only ranges leaf6's raw sealed hit rate
  (83.3%-88.0%), which is stable in isolation but says nothing about whether the DIFFERENCE
  from the naive baseline is real, since the naive baseline is drawn from a different (larger,
  overlapping) population with its own sampling variance that the shipped jackknife never
  touches. beats_naive_sealed is a raw point comparison (rule_hit_sealed greater than hit_se)
  with zero significance/CI machinery anywhere in the script.
- Why it matters: leaf6 is the ONLY rule in the entire 14-rule table that clears the artifact's
  own n_sealed>=30-auction reliable floor, and it is the script's own headline
  (top_rule_by_incremental_lift_over_naive_n_ge_30 in RUN_META). A reader is told this rule
  SURVIVES (beats naive on sealed) as a settled binary fact; the actual margin is a
  coin-flip-adjacent 3 percentage points on 41 auctions, and a fair uncertainty estimate places
  no edge comfortably inside the plausible range.
- Fix: bootstrap (or otherwise CI) incremental_lift_over_naive / the hit-rate difference at the
  auction level for every rule, not just the raw hit rate; report the CI alongside
  beats_naive_sealed rather than a bare boolean; for leaf6 specifically, relabel from SURVIVES
  to survives on point estimate, CI includes no-edge, per the audit brief's own Pass D
  convention (if CI includes zero, the edge is unproven, label the CLAIM -- not the code -- as
  noise until more data).

### [D] [HIGH] leaf9's 1.45x margin is largely a structural artifact of the naive baseline's one-sided-only search, not evidence of a discovered multi-feature interaction -- undisclosed anywhere in the artifact
Evidence:
- leaf9's rule is "posts so far greater than 32.5 AND posts so far less-or-equal 44.5" --
  verified via sklearn.tree.export_text (decision_tree_elon_daily.txt lines 36-40) that this
  leaf involves NO feature other than count_so_far; it is the tree's own two-cut interval on a
  single continuous variable, produced because the modal target for that interval is the
  MIDDLE ordinal bin (32-50 of 3 bins).
- Code inspection: fit_naive_threshold and fit_naive_threshold_2d only ever construct masks
  from "<= v" or "> v" on each feature -- there is no code path anywhere in the script that
  searches a two-sided band (lo <= x <= hi) on a single feature. Grepped rules_out/ for
  band/two-sided/interval: zero hits -- this limitation is not disclosed anywhere in the
  shipped output.
- Dynamic confirmation: built an ad hoc two-sided band search on count_so_far ALONE, identical
  discipline (TRAIN-only fit on the same non-tautological checkpoint pool, min_n=25, frozen,
  applied to sealed). Optimal train band = [31, 32] (n=27 train auctions, hit=85.2% train).
  Applied to sealed: n=8 auctions (14 rows), hit=85.7% -- within about 5 points of leaf9's own
  90.5% (n=17 auctions), using the SAME single feature the naive baseline already had access
  to, just searched as a band instead of a half-line. This demonstrates the discriminating
  power leaf9 exhibits is essentially fully explained by count_so_far's own band-shaped
  relationship to the middle bin, not by anything the tree discovered beyond what a fair
  single-feature test would already show.
- This also answers the task's item 4 (why does leaf9, which has zero relationship to
  max_posts_60min, still clear the 2-feature harder adversary?): because
  fit_naive_threshold_2d combines two one-sided cuts on two DIFFERENT features, it inherits
  the exact same blind spot for a single-feature band -- adding a second feature that leaf9
  doesn't use does nothing to fix the band-vs-half-line asymmetry. So leaf9 beats a
  burst-aware baseline is not independent confirmation; it is the same defect showing up
  twice.
- Why it matters: leaf9 is the largest-margin (most impressive) of the three named daily
  survivors, and the artifact's own language ("these carry information beyond running-count
  AND beyond burst-intensity alone, individually") overstates what was actually shown for this
  specific leaf. This is exactly the concern the audit brief flagged as potentially the most
  important finding in the pass (item 2), and it is confirmed, not merely suspected.
- Fix: add a two-sided band-search naive baseline (mirrors fit_naive_threshold but searches
  lo<=x<=hi pairs on the same single feature) for any leaf whose rule is itself expressible as
  an interval on one feature; disclose the one-sided-only limitation of the existing baselines
  explicitly in the naive-baseline caveat text; do not describe a leaf that beats only a
  one-sided baseline as carrying information beyond running-count when the leaf itself is
  nothing but running-count, banded.

### [D] [LOW] "4 survive" headline count in RUN_META's top-level dict is not itself annotated with how many clear the n>=30 reliability floor, though the fact is recoverable from the notes field and both per-tree text files
Evidence: n_rules_survive_naive_baseline equals 4 sits in RUN_META's headline JSON with no
accompanying n>=30 breakdown at that exact field. The information IS present two places
downstream: (a) decision_tree_elon_daily.txt line 104: "Of the 3 1-feature survivors, 1 also
clear the n_sealed>=30 AUCTION reliability floor... leaf6"; decision_tree_elon_2day.txt line
88: "Of the 1 1-feature survivors, 0 also clear... none" -- together showing only 1 of 4
survivors is reliable-n; (b) RUN_META's own notes field states the reliable-n top rule
separately. The n=1-auction M2-elon_2day-leaf6 survivor also correctly shows
flag_small_n=True and an explicit "insufficient distinct auctions (n=1) -- undefined at n<2"
jackknife line, so it is not silently hidden. This is a genuine but minor presentation gap,
not a fabrication: a reader who only reads the top-level headline JSON (not the notes field or
the two text files) could walk away thinking "4 solid rules" when only 1 clears the artifact's
own reliability bar.
Fix: add an explicit n_rules_survive_naive_baseline_reliable_n_ge_30 field next to
n_rules_survive_naive_baseline in the headline dict.

## What was checked and passed
- Determinism, verified dynamically (not assumed). Backed up the shipped rules_out directory,
  re-ran extract_rules_2026-07-29.py fresh (cold interpreter, full pipeline including the
  token-to-price coverage check and full build_targets call), and ran diff -rq against the
  pre-existing directory: 0 differences across all 17 files. Independently confirms the
  builder's own byte-identical-across-two-cold-runs claim rather than trusting the self-report.
- Hyperparameter fidelity, verified against ground truth, not the script's self-report.
  Grepped pattern_discovery_out/run_dstfix_2026-07-31.log lines 11 and 15 directly: daily
  M2 K=3 ccp_alpha=0.01636, M3_k=3, M4_states=4, M5 n_estimators=50 max_depth=2; elon_2day
  M2 K=4 ccp_alpha=0.0, M4_states=4, M5 n_estimators=50 max_depth=2. Exact match to the
  DAILY_M2_HP, DAILY_M3_K, DAILY_M4_STATES, DAILY_M5_HP, E2D_M2_HP, E2D_M4_STATES constants
  hardcoded in extract_rules_2026-07-29.py, and exact match to the stale-to-correct table in
  the task brief (K 4 to 3, ccp_alpha 0.0 to 0.01636, M3_k 4 to 3, M4_states 3 to 4 for daily).
  Confirms the builder genuinely diffed against the fresh log rather than re-selecting.
- R2 null figure. Grepped pattern_discovery_out/summary.md line 23 directly: R2 of count so
  far predicting final count, Elon daily hour18 is 0.744, hour21 is 0.870. Exact match to what
  decision_tree_elon_daily.txt and RUN_META cite. Confirmed the stale 0.764 and 0.856 values
  appear ONLY inside the explicit supersedes disclosure sentence, never as a live conclusion.
- Determinism of the parent's two cold reruns. Diffed run_dstfix_2026-07-31.log against
  run_pass2.log. Only the load and total runtime wall clock lines differ; every substantive
  line (hyperparameters, R2 null, skill numbers) is byte-identical. Confirms the parent's
  frozen-data-layer claim independently.
- Headline reproduction, from raw data, not the CSV. Reimported build_targets, refit the CART
  with the disclosed hyperparameters, reproduced the exact tree topology (export_text
  byte-identical) and all six elon_daily leaves n and hit numbers exactly (see Reproduced
  section). Also independently reproduced the elon_2day-leaf6 n_sealed=1 survivor and its
  undefined jackknife status.
- n-unit correctness (the prior round's fix). Independently recomputed n_train and n_sealed as
  unique-slug counts per leaf from a from-scratch refit and got the exact same auction counts
  as ranked_rules.csv reports (for example leaf6: 83 train, 41 sealed auctions, not the
  216/113 checkpoint-row counts). This confirms the auction-vs-row fix from the prior audit
  round is genuinely applied, not just relabeled. flag_small_n counted directly from
  ranked_rules.csv: 10 flagged, 4 not, matches RUN_META n_rules_flagged_small_n=10 exactly.
- THE WALL. finals_train and edges are built from daily_train only; clf.fit(Xtr, ytr) is
  train-only; sealed rows are scored with the SAME frozen edges (no re-fit); M3 centroids, M4
  HMM, and M5 GBM are all fit on daily_train / e2d_train exclusively (verified by argument
  passing at each call site). daily_train/daily_sealed and e2d_train/e2d_sealed are
  constructed by a single wall-date split -- disjoint by construction, no unit can appear in
  both. build_targets, WALL_ELON, CHECKPOINTS, make_prior_final_fn, and build_daily_brackets
  are imported and called unchanged from the parent, zero reimplementation risk.
- No cherry-picking. n_rules_total equals 14, which is 6 elon_daily leaves plus 5 elon_2day
  leaves plus 3 M3 clusters, matching the RUN_META leaf/cluster counts exactly. Every leaf is
  printed including untestable ones (elon_2day LEAF 8, n_sealed=0, explicitly labeled as no
  sealed-span row ever reaching this leaf).
- No tradeability claim, no profit-and-loss language. Grepped all of rules_out for
  profit, ROI, tradeability, dollar amounts, buy, sell, wager, bet -- zero hits except the
  explicit RUN_META fills disclaimer stating no P and L, no fills, no tradeability claim
  attached to any rule.
- File scope. All 13 write calls (write_text and to_csv) in the 1,568-line script target
  OUT_DIR (rules_out) exclusively, confirmed by grepping every write call site. Dynamically
  confirmed by mtime: the parent script and its dependencies all predate this audit session
  and remained byte-unchanged after the extraction script's re-run.
- No hardcoded stale checkpoint-clock text. Grepped for the old sixteen-point-five-hour
  pattern the task said had been replaced with a generic reference: zero hits. The current
  caveat text correctly instructs the reader to check each leaf's own printed checkpoints
  rather than pattern-matching a hardcoded threshold.
- RUN_META schema. model_version (ensemble-cap1.5+calibsigma.2026-07-11) is pulled
  automatically from the locked_pace MODEL_VERSION import, not a literal, so it cannot
  silently drift. git_sha (c762636) matches current HEAD. scope, fills, and trial_count=0 are
  all correctly and honestly declared for a zero-hyperparameter-search descriptive extraction.
  The sidecar JSON correctly targets rules_out, not the emit_run_meta default.
- Selection discipline. No select_M1/select_M2-style function is called anywhere in this
  script -- all hyperparameters are hardcoded constants sourced from the disclosed log, never
  searched.

## What could NOT be checked
- Did not independently re-verify the parent study's full walk-forward pipeline beyond the
  specific R2-null and hyperparameter-disclosure lines checked above (out of scope: a
  separate, previously-audited script; this audit treats its frozen, twice-cold-reproduced log
  as ground truth per task framing).
- Did not bootstrap every one of the 14 rules' incremental lift, only leaf6 (the sole
  reliable-n survivor) and the leaf9 band-structure probe. A full pass would likely surface
  similarly wide CIs for leaf4 (n=22) and the collapsed rules, but the task's explicit asks
  were leaf6 and leaf9 specifically, and those were the two that most needed dynamic
  confirmation.
- Did not verify hmmlearn or sklearn cross-machine floating-point reproducibility beyond a
  same-machine re-run.
- Did not audit combo_out or regime_out (different, concurrent scripts, not in scope).

## Recommendation
Do not cite three daily rules survive the naive baseline, or leaf9 beats a burst-aware
adversary, as evidence of a genuinely new, multi-condition discriminative pattern without the
two caveats above: leaf6's margin is statistically unproven at this n (bootstrap CI spans no
edge), and leaf9's margin is almost entirely explained by the naive baseline's inability to
search bands on a single feature, given that leaf9 is not, in fact, a multi-feature rule at
all. This does not reverse the descriptive facts (the leaves, hit rates, and structure are all
real and reproducible); it reverses the interpretation that beats naive was intended to
support. Fixing the naive baseline to include a band search, and adding a bootstrap CI on the
incremental-lift metric, would let this artifact's own stated purpose (distinguishing real
structure from a trivial threshold) actually hold for its strongest two claims.
