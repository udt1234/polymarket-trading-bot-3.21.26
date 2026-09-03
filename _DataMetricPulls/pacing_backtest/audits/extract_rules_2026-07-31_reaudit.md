# Re-audit: extract_rules_2026-07-29.py (naive-baseline fix pass)

**Date:** 2026-07-31 (re-audit of same-day earlier WARN)
**Scope class:** (b) pure forecast-accuracy / calibration diagnostic, descriptive sub-case
(extraction, not a new study). Pass B fill/fee battery N/A. Pass A/C/D applied in full.
**Auditor:** @backtest-auditor
**Prior log:** extract_rules_2026-07-31.md (VERDICT: WARN, 1 MEDIUM + 2 LOW)

## VERDICT: WARN

All three prior findings are RESOLVED and independently reproduced. No fabrication, no
rigged baseline, no re-selection, no scope creep, file-scope clean, fully deterministic
across two independent end-to-end re-runs. However, this deeper pass (specifically the
jackknife requested for finding #3) surfaced ONE new, previously-undisclosed MEDIUM finding:
the "reliable-n (n_sealed>=30)" language attached to 2 of the 3 named survivors counts
CHECKPOINT-ROWS, not resolved AUCTIONS -- the correct Pass D unit. True auction-level n for
leaf4 sealed is 16 (not 39) and for leaf15 sealed is 26 (not 47); both are below the
artifact's own declared reliability floor of 30 once counted correctly. This does not
reverse any conclusion (jackknife independently confirms the effect is not concentrated in
a handful of auctions) but the artifact currently overstates confidence in 2 of its 3
headline survivors. Not fatal: descriptive-only scope, no tradeability claim, direction of
effect independently confirmed robust. FIX before treating leaf4/leaf15 as equally solid to
leaf11.

**Reproduced headline number: YES**, by full independent re-derivation from raw data (not
just re-reading the CSV) -- re-imported pattern_discovery_2026-07-26.py::build_targets(),
refit the CART with the disclosed hyperparameters, rebuilt count_so_far via TWO
independent paths (via M.build_features AND directly via L.obs_count, 0 mismatches
across 1,207 train+sealed rows), reimplemented fit_naive_threshold/apply_naive_threshold
from scratch, and reproduced:
- leaf15: naive count_so_far<=36.0, train n=250 hit=40.4%, sealed n=146 hit=42.4658%,
  incremental_lift_over_naive=1.7035003431708993 -- exact bit-for-bit match to
  ranked_rules.csv / RUN_META top_rule_incremental_lift_over_naive.
- leaf4: naive count_so_far<=2.0, train n=32 hit=59.375%, sealed n=23 hit=73.913%,
  incremental_lift_over_naive=1.144796380090498 -- exact bit-for-bit match.
- Full 22-rule scorecard (5 survive / 15 collapse / 2 untestable) reproduced independently
  by reading ranked_rules.csv's beats_naive_sealed column and counting True/False/NaN --
  matches RUN_META n_rules_survive_naive_baseline=5 /
  n_rules_collapse_to_naive_baseline=15 / n_rules_untestable_naive_baseline=2 exactly.
- leaf7 (old headline)'s pre-existing numeric columns (n_train=44, n_sealed=41,
  train_hit_rate=0.9545454545454546, sealed_hit_rate=0.951219512195122,
  lift_sealed=2.3644599303135885) match the PRIOR audit's independently-reproduced values
  bit-for-bit, confirming the "bit-identical, only row order and new columns changed" claim
  for at least this row.
- Re-ran the ENTIRE script end-to-end a second time (fresh process, ~20s) and diffed
  ranked_rules.csv and decision_tree_elon_daily.txt byte-for-byte against the
  pre-rerun files -- IDENTICAL. Determinism confirmed directly, not inferred.

## Findings

### [D] [MEDIUM] (NEW) "reliable-n (n_sealed>=30)" for leaf4/leaf15 counts checkpoint-rows, not auctions -- true auction-n is below the declared floor and undisclosed
Evidence: joined rules_out/tree_elon_daily_sealed_rows.csv on leaf and counted
.slug.nunique():
- leaf4: n_sealed reported = 39 rows -> 16 unique auctions (2.4 rows/auction; a day can
  hit checkpoints 6/12/15 and land in the same leaf more than once).
- leaf15: n_sealed reported = 47 rows -> 26 unique auctions (checkpoints 18/21 both
  routing to the same leaf on the same day, in 21/26 cases).
- leaf11 (the third named survivor): 98 rows -> 50 unique auctions -- clears 30 by either
  accounting, genuinely reliable.
- MIN_N_FLAG=30 (extract_rules_2026-07-29.py:95) and flag_small_n
  (extract_rules_2026-07-29.py:388) are computed on n_tr/n_se, which are row counts
  (len(sub_tr)/len(sub_se), extract_rules_2026-07-29.py:360,367) -- flag_small_n is
  False for both leaf4 and leaf15, and RUN_META's notes field literally says "Two EARLY
  ... reliable-n (n_sealed>=30) elon_daily rules DO survive -- leaf4 ... leaf15" and calls
  leaf15's margin "the LARGEST reliable-n surviving margin in the whole set." Both claims are
  true only under the row-count convention; under the audit brief's own stated convention
  ("Effective-n = resolved AUCTIONS, never ticks/fills/checkpoints") neither leaf clears 30.
- This is exactly the anti-pattern named in the task brief ("the single most common way a
  noise result is dressed as signal"), now present in the NEW naive-baseline scorecard that
  was added specifically to fix the prior audit's overselling concern -- an unintentional
  regression of the same underlying discipline in a different place.
- Mitigating: I independently jackknifed both leaves at the auction level (leave-one-slug-out
  on the sealed pool) and the sealed hit rate is stable -- leaf4 ranges 83.3%-89.2% (full
  84.6%), leaf15 ranges 71.1%-75.6% (full 72.3%) -- no single auction drives the result, so
  the SIGN of the finding is not an artifact of the row/auction conflation. But the
  CONFIDENCE label ("reliable-n") attached to these two rules is inflated relative to what a
  reader would reasonably infer from "n_sealed>=30."
- Why it matters: a reader who trusts "n_sealed>=30 = reliable" (the artifact's own stated
  bar) will treat leaf4 and leaf15 as equally solid to leaf11, when leaf4 in particular rests
  on 16 independent day-observations in the sealed span -- above the harsh n>=10 floor from
  lesson_tiny_n_ci_degenerate.md but well short of what "reliable" should mean here, and
  well short of what the artifact's own MIN_N_FLAG=30 convention promises.
- Fix: add an n_sealed_auctions (distinct-slug count) column next to n_sealed in
  ranked_rules.csv and the leaf-text blocks; gate flag_small_n/"reliable-n" language on
  the auction count, not the row count; explicitly caveat leaf4 (16 auctions) and leaf15 (26
  auctions) in the RUN_META notes alongside leaf11 (50 auctions, genuinely clears 30).

## What was checked and passed (all 7 requested checks + the 3 original findings)

1. Naive baseline fairness (was the MEDIUM). FIXED, verified 3 independent ways: (a)
   full from-scratch reimplementation of fit_naive_threshold/apply_naive_threshold
   reproduces leaf4 and leaf15 naive threshold/direction/train-hit/sealed-n/sealed-hit/
   incremental-lift bit-for-bit; (b) code inspection confirms the search pool is
   dftr.checkpoint_hours.isin(cps_tr) -- ALL units at that leaf checkpoints, not the
   leaf own row subset (non-tautological, per instruction 1a); (c) both directions (LE,
   GT) are genuinely iterated in the loop (extract_rules_2026-07-29.py:284), confirmed by
   leaf11 naive resolving to GT and leaf4/leaf15 to LE; (d) sensitivity test relaxing
   min_n from 25 down to 10 and to 1 for leaf4/leaf15 -- the leaf STILL beats even a more
   aggressive/overfit unconstrained naive threshold in every case tested, so the n>=25 floor
   is not silently protecting the leaves by excluding a threshold that would have won
   (instruction 1c cleared); (e) count_so_far cross-checked via an independent direct call
   to L.obs_count(post_ts, s, T) bypassing M.build_features entirely -- 0 mismatches
   across 1207 combined train+sealed rows.
2. Two-feature (count + max_posts_60min) adversarial baseline. Built independently (not
   part of the shipped script -- an audit-only probe): a 2D grid search over
   (count_so_far threshold x direction) AND (max_posts_60min threshold x direction), same
   pool/checkpoints, train-fit/frozen/sealed-applied, min_n=25 on each combined mask. This is
   a strictly more powerful (higher-df) adversary than the shipped 1-feature naive. Result:
   leaf4 still beats it on sealed (rule 84.6% vs 2-feat-naive 73.9%, matching the 1-feature
   result almost exactly since the search landed on nearly the same split). leaf15 still
   beats it (72.3% vs 66.7%, narrower than the 1.70x vs the 1-feature naive but still a real
   beat). leaf11 2-feature naive found a degenerate combo (train n=25 exactly at the floor,
   sealed n=5) that is itself a demonstration of the exact overfitting risk this whole
   methodology exists to catch -- not informative either way for leaf11, but not a failure of
   leaf11 either. Net: this REINFORCES, not undermines, the task hypothesis in item 2 --
   burst intensity (max_posts_60min) carries real information beyond running count, and 2 of
   3 survivors hold up against a deliberately harder bar.
3. leaf15 late-window largest-margin jackknife. Leave-one-slug-out on all 26 unique
   sealed auctions: hit rate ranges 71.1%-75.6% (full 72.3%) -- NOT concentrated in any
   single auction. Same check on leaf4 (16 auctions: 83.3%-89.2%, full 84.6%) and leaf11 (50
   auctions: 21.1%-24.2%, full 23.5%) -- all stable. No single-outlier-driven result for any
   of the three survivors. (This same check is what surfaced the row-vs-auction n gap above.)
4. leaf11 23.5% absolute hit rate. Confirmed decision_tree_elon_daily.txt:90 prints
   hit_rate=23.5% in the same line as lift=1.70x and the naive comparison line prints
   SEALED n=129 hit=18.6% ... incremental_lift_over_naive=1.26x immediately below -- a
   reader sees the raw 23.5% directly, cannot mistake the 1.26x ratio for a good absolute
   rate. Same transparency confirmed in RUN_META early_rules_surviving_naive_baseline_n_ge_30
   JSON block (sealed_hit: 0.2347 printed next to incremental_lift_over_naive: 1.2615).
5. Bit-identical claim plus determinism. leaf7 six pre-existing numeric columns match the
   prior audit independently-reproduced values exactly (see Reproduced section above). Ran
   the full script twice end-to-end (fresh interpreter each time); ranked_rules.csv and
   decision_tree_elon_daily.txt are byte-for-byte identical across runs -- determinism
   verified directly, not assumed.
6. No re-selection. WALL_ELON reused via PD.WALL_ELON unchanged
   (extract_rules_2026-07-29.py:111). All 8 hardcoded hyperparameter constants
   (DAILY_M2_HP, DAILY_M3_K, DAILY_M4_STATES, DAILY_M5_HP, E2D_M2_HP,
   E2D_M4_STATES, TREE_MAX_DEPTH, TREE_MIN_SAMPLES_LEAF) unchanged from the values the
   prior audit verified against run_reaudit_fix.log. fit_naive_threshold min_n
   parameter reuses TREE_MIN_SAMPLES_LEAF=25 (no new hyperparameter introduced). No leaf or
   archetype dropped -- all 13 elon_daily leaves, 5 elon_2day leaves, and 4 M3 archetypes
   printed (loops have no filtering, confirmed by code read plus output leaf-count match to
   RUN_META n_cart_leaves_elon_daily=13/n_cart_leaves_elon_2day=5). Grepped every output
   file in rules_out/ for profit/ROI/P&L/tradeability/buy/sell/bet/wager/dollar-amount
   language -- the only hit is the pre-existing explicit no-P&L-no-fills-no-tradeability
   disclaimer in RUN_META fills; nothing new introduced.
7. File scope. Grepped every write call in the 1233-line script (write_text, to_csv,
   mkdir) -- all 13 write calls target OUT_DIR (rules_out/) exclusively, no other write path
   exists. Dynamically confirmed: pattern_discovery_2026-07-26.py (mtime Jul 29 19:05),
   pattern_discovery_lib.py (Jul 26 12:04), pattern_discovery_methods.py (Jul 29 18:03),
   prereg/pattern_discovery_2026-07-26.md (Jul 26 11:21) all predate this re-audit session
   and were confirmed unchanged after my two full re-runs of the extraction script.
   combo_out/ (mtime 12:12) and regime_out/ (mtime 12:28-12:31) reflect the disclosed
   concurrent builder-agent activity from earlier today and were re-checked unchanged after
   my re-runs -- no cross-contamination.
- Old headline preserved for diffability. top_rule_by_sealed_lift_n_ge_30,
  top_rule_sealed_lift=2.3644599303135885, and
  top_rule_by_sealed_lift_COLLAPSES_TO_NAIVE_BASELINE=true all present unchanged in RUN_META
  -- leaf7 old number was not quietly deleted, exactly as required.
- Scorecard placement. n_rules_survive_naive_baseline=5,
  n_rules_collapse_to_naive_baseline=15, n_rules_untestable_naive_baseline=2 in RUN_META
  match the independently-recomputed beats_naive_sealed value_counts on ranked_rules.csv
  exactly (5 True / 15 False / 2 None across 22 rows).

## What could NOT be checked
- Did not re-verify the underlying pattern_discovery_2026-07-26.py walk-forward study own
  n=87/n=198 accounting convention for auctions vs rows -- out of scope for this re-audit
  (that script was audited previously; the row-vs-auction gap found here is specific to this
  extraction script single-shot pooled-checkpoint tree fit, a different construction).
- Did not re-verify hmmlearn/sklearn cross-machine floating-point reproducibility beyond
  what two same-machine re-runs show (same limitation noted in the prior log).
- Did not audit combo_out/ or regime_out/ (concurrent, different scripts, not requested).

## Recommendation
Fix the one new MEDIUM (auction-n disclosure for leaf4/leaf15) before this artifact is cited
as a case where three rules survive the naive-baseline test, including a strong late-window
rule (leaf15, 1.70x), without qualification. With that caveat added, this is otherwise a
clean, honestly self-critical, fully reproducible extraction pass with a real (not
fabricated) fair adversarial test built in. It does NOT mean any of these rules are
tradeable, profitable, or should inform sizing -- this remains a pure descriptive
interpretability artifact over an already-answered "does anything beat the market" question
(prereg answer: no). Surviving the naive baseline means this leaf extra conditions carry
information beyond a single running-count threshold, out of sample, on n auctions as small
as 16 for leaf4 -- nothing more.
