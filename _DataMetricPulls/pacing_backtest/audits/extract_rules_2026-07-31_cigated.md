# Audit: extract_rules_2026-07-29.py -- CI-gated re-audit of the round-3 fixes (band search + bootstrap CI)

Date: 2026-07-31
Scope class: (b) pure forecast-accuracy / calibration diagnostic, descriptive sub-case
(extraction over an already-fit study). Pass B fill/fee battery N/A. Pass A/C/D applied in full.
Prior log audited: extract_rules_2026-07-31_frozen.md (WARN, 2 HIGH findings on the pre-fix artifact).
Auditor: @backtest-auditor

## VERDICT: PASS

No fatal finding. Both round-3 fixes (two-sided band search on the naive baselines;
auction-level bootstrap CI + 3-category CI-gated verdict) are implemented correctly and are
sound -- confirmed by independent, from-scratch dynamic verification, not by re-reading the
builder's own self-report. The result flip (4 point-estimate survivors to 0 CI-gated survivors,
4 UNPROVEN / 9 COLLAPSES / 1 UNTESTABLE) reproduces exactly and is not an artifact of a
too-strong baseline or a mis-specified bootstrap. Two LOW-severity findings are noted below --
neither changes any rule's verdict when tested dynamically, so neither blocks.

Reproduced headline number: YES. Independently reproduced the full 14-rule scorecard by
directly counting naive_verdict in the shipped ranked_rules.csv: 0 SURVIVES / 4 UNPROVEN / 9
COLLAPSES / 1 UNTESTABLE -- exact match to RUN_META's n_rules_survive_naive_baseline_CI_GATED=0
etc. Also independently re-derived (own bootstrap code, own RNG, same disclosed methodology) the
incremental-lift CIs for the two named rules:
- leaf9: shipped CI is 0.8048x to 1.6687x, P(lift<=1)=43.54% -- my own independent
  re-implementation of the SAME (disclosed) independent-per-side auction bootstrap: CI 0.805 to
  1.669, P=43.5%.
- leaf6: shipped CI is 0.7818x to 1.7755x, P(lift<=1)=41.05% -- my own re-implementation: CI
  0.782 to 1.776, P=41.0%.
Both match to within expected bootstrap-RNG noise.

## Findings

### [D] [LOW] leaf6's CI-widening is explained imprecisely as "a stronger comparator" -- the real driver is a much smaller comparator sample, not higher comparator accuracy
Evidence: reconstructed the OLD one-sided-only naive vs the NEW band naive on leaf6's real train
pool (Xtr, checkpoints [6,12,15,18,21]) and applied both to the real sealed pool:
- OLD (one-sided, from the prior frozen audit): threshold count_so_far<=3.0, sealed n=18
  auctions, hit=80.8%.
- NEW (band search, shipped): band [2,3], sealed n=8 auctions (naive_n_sealed in
  ranked_rules.csv), hit=80.0%.
The comparator's point-estimate accuracy is essentially FLAT (80.8% to 80.0%, a 0.8pp move, well
within noise) -- it did not get meaningfully "stronger" in the sense of predicting better. What
changed is that the band search chose a NARROWER interval, which more than halved the
comparator's own sealed sample size (18 to 8 auctions). A comparator built from 8 auctions has
much larger bootstrap sampling variance than one built from 18, and that is what widens the
incremental-lift CI from 0.81-1.44x to 0.78-1.78x -- confirmed directly: my own train-vs-sealed
degradation check (independent brute-force refit of both the band and a reconstructed one-sided
rule, applied to real sealed count_so_far) shows the band naive is NOT meaningfully more accurate
than a one-sided alternative would be at leaf4/leaf6 (band sealed hit 80.0% vs a one-sided
reconstruction's 80.8-82.6%, i.e. slightly WORSE, not better).
Why it matters: the artifact's own docstring/comment ("audit attributes the small gap to the band
search finding a stronger comparator") mischaracterizes the mechanism. This is not a numerical
error (every reported number is correct and reproduces), just a mislabeled cause. It is also
directionally CONSERVATIVE, not inflationary: a smaller-n comparator only widens the CI, which
makes SURVIVES (ci_lo>1.0) harder to reach, not easier -- so this mislabeling does not manufacture
a false negative, if anything it biases toward the more cautious UNPROVEN/COLLAPSES side.
Fix: correct the comment/notes text to say the band search's narrower selection shrinks the
comparator's own sealed sample, which is what widens the CI -- not that the comparator became more
accurate.

### [D] [LOW] Independent (not paired/joint) auction-level resampling is a defensible but undisclosed-as-a-choice methodology -- dynamically confirmed to not change any verdict, including for the one case with real population overlap
Evidence: the shipped bootstrap_incremental_lift_ci() draws two SEPARATE auction-level
resamples (rule side, naive side) independently, disclosed in the printed text as "independent
per side" (decision_tree_elon_daily.txt line ~905). I implemented an independent, from-scratch
PAIRED bootstrap (resample once from the common auction pool at the leaf's own checkpoints, then
compute both rule_hit and naive_hit from that SAME resample, preserving whatever correlation
exists between the two statistics) and ran it against the shipped independent method for every
rule where a defined CI exists and the rule/naive populations could plausibly overlap:
- leaf9-daily (rule/naive overlap: 0 of 42 rule rows also in the naive's 14 rows -- genuinely
  disjoint auctions): independent CI 0.805-1.669, P=43.5% vs paired CI 0.809-1.790, P=45.3%.
  Verdict unchanged (UNPROVEN either way).
- leaf6-daily (overlap: 1 of 113 rule rows -- effectively disjoint): independent CI 0.782-1.776,
  P=41.0% vs paired CI 0.786-1.834, P=39.8%. Verdict unchanged (UNPROVEN either way).
- leaf4-daily (overlap: 9 of 10 naive rows also in the rule -- substantial overlap, the case
  where paired resampling SHOULD matter most by theory): independent CI 0.820-1.913, P=28.3% vs
  paired CI 0.902-1.820, P=22.8%. The paired CI is visibly narrower here, as theory predicts for
  positively-correlated overlapping samples -- but the verdict is STILL unchanged (UNPROVEN
  either way, ci_lo stays below 1.0 under both methods).
- elon_2day-leaf7 (overlap: 14 of 20 naive rows -- also substantial): independent CI 0.701-1.342,
  P=61.2% vs paired CI 0.786-1.132, P=69.5%. Verdict unchanged (COLLAPSES either way,
  determined by the point estimate, which is identical under both methods).
Why it matters: this was the single concern most likely to overturn the "0 SURVIVES" headline
(the task's own framing). Dynamically confirmed NOT to: even in the one case with meaningful
rule/naive overlap where the paired method visibly narrows the CI (leaf4), the narrowed CI still
straddles 1.0. For the two headline leaves (6 and 9), the rule and naive populations are close to
disjoint auction sets by construction (the naive band search finds a DIFFERENT, narrow slice of
count_so_far than the leaf's own multi-condition membership), so independent resampling is close
to the textbook-correct choice there, not a source of bias.
Fix (non-blocking, forward-looking): document the independent-resampling choice as a deliberate
one, with the overlap-check above as supporting evidence; if this baseline apparatus is reused on
data with larger auction counts (where overlap and correlation could matter more), switch to the
paired/joint resample by default since it is the more statistically standard choice for two
selection rules applied to the same underlying pool and costs nothing when overlap is low.

## What was checked and passed (this round, all independently re-derived, not just re-read from the builder's self-report)
- Determinism: backed up the shipped rules_out/, ran two independent cold
  "python extract_rules_2026-07-29.py" invocations (31.5s and comparable), diffed each against the
  original with diff -rq: 0 differences, both times.
- Band-search algorithmic correctness (fit_naive_threshold / fit_naive_threshold_2d):
  instrumented a working copy of the script to capture every real call's exact (counts, y_bool,
  min_n) to result pair (14 one-feature calls, 11 two-feature calls -- the full set the real
  run actually made), then checked each against an independently-written, from-scratch reference:
  - 1D: true O(U^2) double-loop brute force, zero cumulative-sum tricks. 14/14 real cases match
    exactly (lo, hi, n_train, hit_train all bit-identical).
  - 2D: a structurally different decomposition (direct feature-1 masking + the already-verified
    1D primitive as the conditional inner search, not the shipped 2D histogram/cumsum). 11/11 real
    cases match exactly on the optimal (hit, n).
  - Synthetic stress: 500 random trials (duplicate-heavy integer count vocabularies, random
    min_n, n from 0-80) plus explicit edge cases (all-identical values, empty input, min_n at/above
    n) against the true 1D brute force: 0 mismatches.
- Train-only discipline of the naive fits: confirmed by code read (fit_naive_threshold with
  count_so_far_tr[mask_cp_tr] and ytr[mask_cp_tr]==modal_bin as inputs -- both arguments are
  _tr-suffixed arrays; the sealed arrays are only ever passed to apply_naive_threshold, never to
  the fit) and by direct inspection of the instrumented capture (the fit-time arrays captured
  during the real run are always sized to the TRAIN pool -- e.g. leaf6/leaf9's fit pool is 1060
  rows = the daily TRAIN row count, never touching the 435-row sealed pool).
- Naive-baseline overfitting risk (band search having more DOF than a one-sided cutoff):
  reconstructed a one-sided-only naive (the OLD baseline logic) alongside the new band naive on
  every real captured train pool, then applied BOTH to the real sealed pool. For the three
  middle-bin leaves sharing the [31,32] band (5, 7, and the headline 9), the band naive
  GENERALIZES ESSENTIALLY PERFECTLY (train 85.2% to sealed 85.7%, no overfitting), while a
  one-sided-only alternative for the same target badly UNDERFITS (finds a near-useless
  "count_so_far >= 23" threshold at 40.8% train hit) -- direct evidence the band-search fix is not
  itself manufacturing an artificially strong (or overfit) comparator for the leaf9 case the prior
  audit flagged. For leaf4/leaf6 ("<32" bin), the band naive shows a small (+3.7 to +5.2pp)
  train-to-sealed degradation, slightly worse than a one-sided reconstruction's (+0.7 to +2.6pp)
  -- but in the direction that makes the comparator WEAKER on sealed, not stronger, so this cannot
  be the source of a false-negative bias; see Finding 1 above.
- Confirmation of the specific leaf9 match: shipped output reports band=[31,32], sealed n=8
  auctions, hit=85.7% for leaf9. My independent brute-force re-derivation on the real captured
  data reproduces [31,32]/85.7% exactly, and it matches the prior audit round's own independent ad
  hoc probe ([31,32], 85.7% sealed) from a third, differently-coded implementation. Three
  independent code paths agree.
- n_sealed=1 disqualification: M2-elon_2day-leaf6 (n_sealed=1 auction) has incr_lift_ci_lo /
  incr_lift_ci_hi = NaN in ranked_rules.csv (bootstrap undefined at <2 auctions) and
  naive_verdict=UNPROVEN, never SURVIVES -- confirmed directly from the CSV and from
  naive_verdict_from_ci's logic (CI-is-None routes to the UNPROVEN branch, never the ci_lo>1.0
  SURVIVES branch).
- Scorecard, no cherry-picking: all 14 rules (11 CART leaves + 3 M3 clusters) appear in
  ranked_rules.csv and in both decision_tree_*.txt files, including every COLLAPSES, UNPROVEN,
  and the 1 UNTESTABLE row (M2-elon_2day-leaf8, n_sealed=0).
- No tradeability claim: grepped rules_out/ for profit/ROI/tradeability/buy/sell/wager/bet
  dollar-amount language; the only hit is an explicit disclaimer (a descriptive property of shape
  structure, not a live bet) in day_archetypes.txt, not a claim.
- R2 null figures unchanged despite a concurrent, unrelated regeneration:
  pattern_discovery_out/summary.md has a newer mtime (15:05 today) than the frozen
  run_dstfix_2026-07-31.log (13:30) and pattern_discovery_methods.py (13:35), confirming the
  coordinator's note that summary.md was regenerated concurrently for an unrelated reason.
  Directly grepped its live "Null-model check" section: R2 hour18=0.744, hour21=0.870 --
  unchanged, matches what RUN_META and the decision-tree caveat text cite.
- File scope: only extract_rules_2026-07-29.py's own outputs (rules_out/) were written by the
  real run. My own instrumentation ran from temporary copies outside the tracked script and was
  fully cleaned up (temp scripts deleted, one stray RUN_META sidecar it produced under an
  instrumented filename was deleted, diff -rq against a pre-audit backup of rules_out/ confirms
  0 differences after cleanup).
- RUN_META schema: model_version pulled from the locked_pace import (unchanged), git_sha
  present, scope/fills/trial_count=0 all correctly declared for a zero-search descriptive
  extraction, headline JSON's CI-gated counts match the CSV exactly.

## What could NOT be checked
- Did not brute-force-verify the 2D band search on fully synthetic random data (only real
  captured cases + the theoretically-justified outer-mask/inner-1D decomposition) -- the real-data
  coverage (11/11 exact matches) plus the fully brute-forced 1D primitive (which the 2D search
  reduces to) is judged sufficient, but a pure synthetic 2D stress test was not run due to
  quadratic-in-quadratic runtime cost of a naive reference on this machine.
- Did not re-verify M3 cluster naive fits' sealed-side train/sealed degradation (pool-capture was
  only added for CART leaves, since M3 clusters use a different, non-checkpoint-based pool
  construction) -- their 1D fit correctness IS covered by the real-data brute-force check above
  (indices 11-13 of the captured 1D calls), just not the overfitting-degradation cross-check.
- Did not independently re-verify the full pattern_discovery_2026-07-26.py walk-forward pipeline
  beyond what the prior audit round already checked (R2 null, hyperparameter disclosure,
  DAILY_BRACKETS) -- out of scope, treated as previously-audited ground truth per task framing.
- Did not test paired-vs-independent bootstrap sensitivity for every one of the 14 rules, only
  the 2 headline UNPROVEN leaves (6, 9) plus one additional UNPROVEN leaf (4) and one COLLAPSES
  leaf with real overlap (2day-leaf7) -- chosen specifically to cover the highest-overlap and
  highest-stakes cases; the remaining rules are COLLAPSES-by-point-estimate (unaffected by CI
  method) or UNTESTABLE (CI undefined regardless of method).

## What a PASS here establishes -- read this before citing the negative result
This PASS means: no rule in this artifact demonstrates out-of-sample discriminative power
beyond count_so_far (or count_so_far + max_posts_60min), at this sample size (n=87 sealed
daily auctions / n=28 sealed 2-day auctions), and with this specific naive-baseline construction
(train-fit band-or-one-sided threshold, CI-gated at the 95% level). That is NOT the same claim
as "no such structure exists." Specifically:
- At n=87 sealed auctions (41 in leaf6, 17 in leaf9), a genuine, real, moderate edge (say, a true
  incremental lift of 1.1x to 1.3x) could easily fail to clear a 95% CI-excludes-1.0 bar just from
  sampling noise -- the CI widths observed here (0.78-1.78, 0.80-1.67) are wide enough to be
  consistent with a real, smaller edge that this study is simply underpowered to detect, not only
  with a true null.
- The naive baseline itself is a specific, disclosed choice (single- or dual-feature band/threshold
  search). A rule could still encode real structure that this particular baseline construction
  is not the right adversary to isolate.
- This is a CI-gated, one-shot, extraction-only pass over a fixed sealed span. It is not a
  pre-registered, held-out replication on new data, and the task's own framing (n<10 auctions
  means "noise until more data") generalizes here: n in the 17-45 auction range per rule is small
  enough that "not proven" is the honest label, not "proven absent."
Bottom line: cite this as "this specific battery of checks found no rule that clears a
statistically defensible bar at this sample size" -- not as "these rules are worthless" or "there
is no exploitable structure in the underlying process." The distinction matters for anyone deciding
whether to invest further data collection into this line of inquiry versus abandoning it.
