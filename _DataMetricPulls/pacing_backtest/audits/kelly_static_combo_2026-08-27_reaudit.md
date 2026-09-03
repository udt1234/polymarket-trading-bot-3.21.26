# Re-audit: kelly_static_combo_2026-08-27

Scope class (a): claims P&L. Pass B's fill/fee/cost battery binds in full.
Prior audit: audits/kelly_static_combo_2026-08-27.md (VERDICT: WARN)
Prereg: prereg/kelly_static_combo_2026-08-27.md (unedited, mtime 17:42, precedes script
edit 18:37 and output 18:39 -- correct chronology, no post-hoc rewrite).
Script: kelly_static_combo_2026-08-27.py. Outputs: kelly_out/.

## VERDICT: PASS

Both prior findings are confirmed fixed by dynamic verification, not just re-reading the
diff. The one number that changed materially (Trump B2_naive +63.25% -> -5.87%) is fully
traced, explained, and independently re-derived from raw ledger cells: it is the correct,
expected consequence of Finding 1's fix, not a new integrity problem and not a deleted
result. No fatal finding. One new LOW/informational finding (Elon's l2_hardened rows
split 14 pure / 6 mixed on re-inspection; disclosed in the ledger but not in any prose
output). Headline numbers for BOTH handles reproduce exactly, independently, from the raw
per-row ledger cells (not the script's own printed summary).

## The vanishing +63.25% -- traced and explained, not a red flag

Reproduced directly from `ledger_realDonaldTrump_7-day.csv`, B2_naive columns, all 29
sealed rows in chronological order (script's own per-row bankroll_before/after, cross-
checked against my own independent cost_paid/payout compounding):

- Row index 17 (`donald-trump-of-truth-social-posts-april-10-april-17`), the 18th sealed
  row: `B2_naive_bankroll_after` = **1632.523455**. This is bit-for-bit the old audit's
  reported "$1632.52, ROI +63.25%".
- The SAME continuous flat-10%-of-bankroll sequence continues, unbroken, for 11 more
  auctions and ends at row index 27 (`...-may-15-may-22`) with bankroll_after =
  **941.268694** = the new reported $941.27 / -5.87% ROI. Row 28 is `no_trade` and does
  not move the bankroll.

Conclusion: the old +63.25% was never a terminal result. It was a MID-SEQUENCE snapshot,
reported as if it were a completed span's terminal outcome, only because the old
(buggy) code artificially fragmented Trump's single n=29 sealed population into two
populations at a boundary (the global pmxt-archive start date) that has NOTHING to do
with Trump's own data reality (Trump has zero pmxt L2 rows anywhere, confirmed again
below). One flat-sizing naive-bracket strategy went up ~63% through 18 auctions, then
gave essentially all of it back plus a bit more over the next 11, netting -5.87% by
auction 29. That is ordinary path-dependent compounding behavior for a 10%-flat-stake
strategy on a single fixed bracket, not evidence of data loss. Every one of the 29 rows
is present in the new ledger (chronological, no gaps, no duplicate slugs) and the
b2_bracket selection (the fixed modal winner used throughout) is the same hindsight-
selected bracket as before (still flagged `b2_hindsight=True` in both the print and
RUN_META). Nothing was quietly deleted; the number that vanished was itself the artifact.

## Finding 1 (fill_mode mislabeling) -- CONFIRMED FIXED, dynamically verified

1. Independently re-queried `read_l2` (not just re-read the script's print) for the
   Trump token set of `donald-trump-of-truth-social-posts-april-14-april-21` (the first
   row the OLD ledger falsely labeled `l2_hardened`): `price_change` source=pmxt -> 0
   rows, `last_trade_price` source=pmxt -> 0 rows, `price_change` source=both -> 0 rows,
   across all 11 tokens. Confirms the code's own "L2 tokens indexed: 0" print for
   realDonaldTrump is correct, not merely self-reported.
2. Ledger re-inspection: `ledger_realDonaldTrump_7-day.csv`, all 29 sealed rows, every
   `*_fill_mode` column (checked kelly_full and B2_naive) shows only `proxy` or
   `no_trade` -- zero `l2_hardened`, zero `mixed_l2_proxy`. Trump's sealed span is now
   one honest n=29 proxy-only population, matching the builder's claim exactly.
3. The evidence-quality assert is LIVE, not decorative. Ran a standalone synthetic test:
   loaded the module directly, called `execute_arm()` with a crafted unit whose `bb_idx`
   has a valid pre-checkpoint bid (forcing `leg_price()` to return `"l2_hardened"`) but
   an EMPTY `lt_idx` passed in. Result: `AssertionError: fill_mode='l2_hardened' asserted
   for synthetic-test-slug but lt_idx is empty ... labeling bug.` The assert fires
   exactly as designed. Caveat: the check is at the handle-wide `lt_idx` truthiness
   level, not per-token; in practice this is fully redundant with the upstream
   `n_l2_tokens==0` gate in `run_group` since both derive from the same
   `build_l2_index()` call on the same token universe -- real, but a second layer of the
   same check, not an orthogonal one. Not a finding, just noted for completeness.
4. Elon's split is genuinely untouched. The new code path (`n_l2_tokens==0`) applies
   only to Trump; Elon (`n_l2_tokens>0`) takes the pre-fix branch, confirmed byte-
   identical by re-deriving Elon's headline numbers straight from `kelly_full_cost_paid`
   / `kelly_full_payout` in the ledger: terminal **31.8986**, exact match to RUN_META
   (31.89860361759413) and to the prior audit's independently-reproduced 31.8986.
5. New fact surfaced, verified, and assessed: of Elon's 20 traded sealed_l2 rows
   (previously reported as one undifferentiated "l2_hardened" bucket), the new granular
   label splits them **14 `l2_hardened` (pure) / 6 `mixed_l2_proxy`** (`value_counts()`
   on `kelly_full_fill_mode`, confirmed identical on `flat_B4` too). 14+6=20, matches
   the old audit's "n_traded=20" exactly.
   Does this weaken PRIMARY? The underlying dollar arithmetic for every Elon row is
   UNCHANGED (bit-for-bit identical terminal/max_dd/P(ruin)/bootstrap/calibration to the
   pre-fix numbers already independently reproduced in the prior audit). Only the label
   granularity improved. Within a `mixed_l2_proxy` row, the L2-priced leg(s) still go
   through the full hardened `maker_fill_l2` model (min-rest, strict through-fill, queue
   haircut); only the OTHER leg(s) in that combo fall back to the disclosed canonical-
   close proxy (mean bias +0.22c, 13.4% opposite-direction, sd~1.1c). Given the headline
   loss is enormous and the CI is nowhere near zero (kelly_full pnl/auc CI = -48.41
   [-78.77, -18.63], jackknife drop-best sign holds), a few cents of proxy noise on a
   subset of legs in 6 of 20 rows cannot plausibly flip the sign or the conclusion. This
   does NOT weaken PRIMARY's verdict. It IS a legitimate evidence-quality nuance that
   should have been surfaced in prose/RUN_META and currently is not (grepped
   SUMMARY_kelly_static_combo.md, stdout log, and RUN_META notes for "mixed_l2_proxy" --
   zero prose mentions, only present as a CSV column value). LOW severity: the data is
   fully present and auditable in the ledger (satisfies the prereg's "every headline
   must be recomputable from this file alone"), it just isn't called out for a reader
   skimming the summary.

## Finding 2 (B2 hindsight) -- CONFIRMED FIXED

- `b2_hindsight` now prints inline: Trump's B2_naive line in section 1 carries
  `*** HINDSIGHT-SELECTED BRACKET -- NOT achievable live, see B2_walkforward below ***`;
  Elon's does not (its `b2_hindsight=False`, TRAIN-selected on n=35). Confirmed both in
  `SUMMARY_kelly_static_combo.md` and in `run_meta.json`'s
  `headline.<handle>.<span>.b2_naive_hindsight` field for every sub-span (Elon
  sealed_l2/sealed_proxy = false, Trump sealed_proxy = true).
- B2_walkforward is genuinely zero-hindsight. Read `b2_walkforward_rows()`: uses
  `prior_idx = [j ... if units[j]["e"] < s_i]`, the identical WALL idiom already
  confirmed clean in the prior audit for `walk_forward_select`. Spot-checked the first 7
  Trump sealed rows: `B2_walkforward_traded=False` for every row where fewer than
  MIN_PRIOR=5 strictly-prior Trump auctions exist yet (n_prior_used 0,0,0,1,3,4,4 all
  correctly untraded), only starting to trade once the floor is cleared. No hindsight
  leak found.
- Independently reproduced Trump's `B2_walkforward` terminal from raw
  `B2_walkforward_cost_paid`/`_payout` columns: **290.389**, exact match to RUN_META
  (290.3889738187235).
- The gap between B2_naive (-5.87%, hindsight) and B2_walkforward (-70.96%, honest) is
  now visible side by side for every sub-span, exactly as the fix intended, and is
  informative: the hindsight leak in the naive baseline was worth roughly +65 points of
  ROI on Trump.

## Standing checks (re-verified, not just re-read)

- Trial count 41, verified by manually summing `trials_detail` keys/values in
  `run_meta.json`: 16 (Elon train-select grid) + 1 (Elon frozen ledger) + 7 (Elon
  sealed_l2 arms incl. new B2_walkforward) + 7 (Elon sealed_proxy arms) + 1 (Elon diag
  checkpoint) + 1 (Trump frozen ledger) + 7 (Trump sealed_proxy arms) + 1 (Trump diag
  checkpoint) = 41. Matches `trial_count: 41` exactly. The 44->41 arithmetic (-6 for
  Trump's now-collapsed sealed_l2's old 6 arms, +3 for the new B2_walkforward arm across
  Elon-l2/Elon-proxy/Trump-proxy) checks out against the old audit's 44-trial breakdown.
- RUN_META n_auctions = 53 = 24 (Elon: 21 sealed_l2 + 3 sealed_proxy) + 29 (Trump
  sealed_proxy). Verified by direct row count on both ledgers. This is a defined,
  documented scalar (code comment states it is "total SEALED auctions actually fed into
  a P&L simulation across both handles," not a claim of homogeneity), and the full
  nested per-population breakdown remains intact right next to it. Adequately disclosed,
  not misleading -- same resolution style as the prior audit's LOW finding on this exact
  field (previously null). LOW/informational, not a new defect.
- Elon fully unchanged, re-verified independently (not just diffed against my own prior
  log): recomputed terminal ($31.8986), max_drawdown (-96.8%), P(ruin) and bootstrap
  mean/median match RUN_META and SUMMARY bit-for-bit, and BOTH handles' calibration
  diagnostics (Elon |q-realized|=0.4217 vs |cost-realized|=0.0262; Trump 0.5073 vs
  0.0811) match the prior audit's independently-reproduced values to the same precision.
  Calibration is untouched by design: it reads off the single frozen selection `ledger`,
  never the fill_mode-split populations.
- Headline stays NO on both handles. Section 1's plain-answer text is unchanged in
  substance; every Kelly/flat/B2 arm on every sub-span with n>=SUCCESS_N_FLOOR still
  shows a loss; section 1b shows PRIMARY=False and SECONDARY=False on every eligible
  arm; TERTIARY=False for both handles. Nothing was tuned toward a positive.
- White House still BLOCKED, unchanged: n=4 resolved+covered windows, non-independent
  overlapping 7-day rolling windows, explicit "NOT evidence" language retained verbatim.
  Cannot be read as "also no."
- Trump keeps BORROWED-CONFIG labeling ("[BORROWED-CONFIG, not an independent control]"
  tag on its section header, plus the full disclosure sentence) and its now-withdrawn L2
  claim reads as "SEALED-L2 (hardened real fills): no auctions in this sub-span" -- a
  reader cannot come away thinking Trump has any hardened-fill evidence. Taken together
  with BORROWED-CONFIG (Trump's own hyperparameters were never independently selected),
  this data set gives no genuinely independent second handle: the study's real
  evidentiary weight rests on Elon alone. This exact framing is not printed as one
  sentence anywhere in the artifact, but every component fact needed to reach it
  (BORROWED-CONFIG, hindsight B2, zero L2 coverage, "not an independent control") is
  explicit in the output; stated here for the record.
- File scope respected. `git status` shows zero modifications to `pattern_discovery_*`,
  `regime_*`, `extract_rules_*`, `combo_out/`, `rules_out/`, or any other prereg's
  files. mtime chronology (prereg 17:42 < script 18:37 < outputs 18:39) shows no
  retroactive prereg editing.

## What was checked and passed (dynamically confirmed this pass)

- Live `read_l2` re-query for Trump tokens: 0 rows, both `source='pmxt'` and
  `source='both'`, confirming the fix's premise independently of the script's own print.
- Live synthetic-violation test of the evidence-quality assert: fires correctly.
- Independent bit-for-bit reproduction of BOTH handles' headline P&L (Elon kelly_full
  $31.8986; Trump kelly_full $74.2891; Trump B2_walkforward $290.389; Trump B2_naive
  $941.2686) straight from raw per-row `cost_paid`/`payout` ledger cells, not the
  script's own printed bankroll path.
- Row-by-row trace of the Trump B2_naive sequence proving the vanished +63.25% is a
  mid-path snapshot of the SAME continuous ledger, not a deleted or fabricated result.
- Elon's `l2_hardened`/`mixed_l2_proxy` split (14/6) verified by direct `value_counts()`
  on the ledger, cross-checked against the previously-confirmed n_traded=20 total.
- Trial count (41) verified by manual summation of `trials_detail`.
- `B2_walkforward`'s zero-hindsight construction verified by inspecting the WALL idiom
  and spot-checking the first 7 Trump rows' skip/trade behavior against MIN_PRIOR=5.
- File-scope and prereg-integrity chronology re-confirmed via `git status` + mtimes.

## What could NOT be checked

- Did not re-verify every one of the 29 Trump or 24 Elon rows' cost_paid/payout against
  a fresh from-scratch re-derivation of `leg_price()`/`maker_fill_l2()` from raw L2
  ticks (spot-checked the mechanism structurally in the prior audit; this pass
  reproduced the compounding arithmetic from the ledger's own per-row outputs rather
  than re-deriving each fill from tick data a second time).
- Did not re-run half-Kelly/quarter-Kelly bit-for-bit for every sub-span (spot-checked
  full-Kelly and one baseline arm per handle; same methodology applies, extrapolated).
- Did not exhaustively re-verify the assert's redundancy claim (that `n_l2_tokens==0`
  and `lt_idx` empty are always co-extensive) beyond code inspection; a case where
  `bb_idx` is non-empty but `lt_idx` is empty for a REAL handle was not observed in this
  data and was only exercised synthetically.

## What this result establishes now, and what it does not

Establishes (high confidence, independently re-verified this pass):
- The Finding-1 (fill-mode mislabeling) and Finding-2 (B2 hindsight leak) defects from
  the prior WARN are both genuinely fixed, not just relabeled -- confirmed by live data
  queries and a live code-behavior test, not by re-reading the diff.
- The apparent "loss of a profitable result" (Trump B2_naive +63.25%) is not a data-
  integrity problem: it is the correct removal of a false population boundary, verified
  row-by-row against the underlying ledger.
- Elon's PRIMARY result (recency-argmax Kelly combo loses badly, -96.81% ROI on the
  hardened sealed_l2 span, market well-calibrated vs realized outcomes, our recency
  estimate badly overconfident) is untouched by either fix and independently reproduces
  exactly. This remains the study's one genuinely independent, best-instrumented result.

Does NOT establish:
- Independent confirmation on a second handle. Trump's config is borrowed from Elon's
  TRAIN selection, its B2 naive baseline was hindsight-selected (now disclosed and
  honestly re-run), and it now carries ZERO hardened L2 evidence (the fake 11-row
  "l2_hardened" section has been correctly withdrawn). Trump is directionally
  consistent (also loses, under every arm) but this is, in substance, a one-handle
  study for the purpose of claiming independently-replicated evidence.
- Anything about White House (still blocked, n=4, descriptive only).
