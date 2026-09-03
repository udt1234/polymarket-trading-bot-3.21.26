# Close-out audit: kelly_static_combo_2026-08-27

Scope: focused close-out on the single LOW finding from the re-audit (2026-08-27,
VERDICT PASS). Prior findings (fill_mode mislabel, B2 hindsight leak) already confirmed
fixed in the re-audit and NOT re-derived here per task brief.

Prior logs: audits/kelly_static_combo_2026-08-27.md (WARN),
audits/kelly_static_combo_2026-08-27_reaudit.md (PASS, one new LOW).
Script: kelly_static_combo_2026-08-27.py (mtime 18:53). Outputs: kelly_out/ (mtime 18:58).
Prereg: prereg/kelly_static_combo_2026-08-27.md (mtime 17:42, unchanged since last audit).

## VERDICT: PASS

The LOW finding (Elon fill-quality split existed only in the ledger CSV, never in prose)
is fixed, dynamically confirmed generator-resident, and accurate. No regression found in
either previously-fixed defect. Headline stays NO on every arm, both handles. White House
framing unchanged (BLOCKED, NOT evidence). Trump framing unchanged (BORROWED-CONFIG,
directionally consistent, not independent confirmation).

## Check 1: generator-residency (not just file-presence)

Grepped the script for the four claimed additions and located all in main():
- kelly_static_combo_2026-08-27.py:1199-1206: FILL-QUALITY SPLIT print block, inside
  the per-handle results loop (w() calls), computed from
  result[arms][kelly_full][0] via value_counts() at print time, not a hardcoded
  string.
- :1385-1401: out[label][fill_quality_split] dict built inside the RUN_META
  headline-builder function, same live value_counts() computation, independent of the
  print-block code path (two separate live computations of the same live data, not one
  computed value copy-pasted into two places).
- :1161-1168: HISTORICAL NOTE (the +63.25% resolution) as a w() block in section 1.
- :1141-1148: STUDY STATUS block as a w() block opening section 1.

Re-ran the full script end to end (python kelly_static_combo_2026-08-27.py, exit 0).
Diffed every ledger CSV, both regime-lag CSVs per handle, both train-selection-grid CSVs,
white_house_descriptive.csv, and SUMMARY_kelly_static_combo.md against the pre-rerun
snapshot: all nine files plus SUMMARY byte-identical (diff -q, zero output). All four
disclosures reappeared verbatim in the fresh SUMMARY (grep confirmed post-rerun, same
line numbers/content). This proves the disclosures are computed by code that runs to
completion every time, not artifacts of a one-off hand-edit to kelly_out/ that a future
run would silently erase, the exact failure mode flagged as a risk in the task brief.

## Check 2: byte-identical RUN_META claim, verified independently

Loaded both the pre-rerun and post-rerun kelly_static_combo_2026-08-27.run_meta.json,
recursively stripped every fill_quality_split key from both (the only key the builder
claims is new), and compared the remainder for structural equality in Python.
Result: EQUAL after stripping fill_quality_split = True, confirmed by full recursive
dict/list comparison, not a visual diff. Every other RUN_META field (all terminals, CIs,
n_flags, b2_hindsight, trial_count=41, n_auctions=53, calibration, borrowed_config,
white_house block) is untouched by this fix. Independently re-confirmed headline.trump
carries no sealed_l2 key at all (list of trump keys has no sealed_l2), consistent
with Finding 1's collapse holding.

## Check 3: accuracy of each disclosure's content, re-derived from raw ledger cells

14/6 split. Independently replicated the sealed_l2/sealed_proxy population boundary
from first principles (not by reading the script's own split arrays): pulled
l2_start_ms=1776109270430 from the RUN_META notes field, converted every Elon
span==sealed row's start_et to unix seconds, applied the exact boundary predicate
from the code (start_ts + 24*3600 >= l2_start_sec) by hand in a fresh script, and got
21 sealed_l2 rows and 3 sealed_proxy rows. Filtering to kelly_full_traded==True on the 21
sealed_l2 rows and counting kelly_full_fill_mode gives 14 l2_hardened, 6
mixed_l2_proxy, 0 proxy, n_traded=20: exact match to both the RUN_META
fill_quality_split block and the SUMMARY prose line (of 20 traded rows... 14 pure L2...
6 mixed_l2_proxy). This is a from-scratch re-derivation using only the ledger CSV and the
RUN_META-published l2_start_ms, not a re-read of the script's own arrays.

Mixed definition. RUN_META text: at least one leg in the row fell back to the
last-trade proxy price rather than the real order book. Matches the mechanism described
and independently verified in the prior re-audit (_reaudit.md lines 80-90): within a
mixed_l2_proxy row, the L2-priced leg(s) still use the hardened model, only the other
leg(s) fall back to canonical-close proxy. Accurate.

Auditor's assessment quote. RUN_META and prose both read: does NOT weaken PRIMARY,
the ROI loss magnitude dwarfs the ~1-2c proxy noise on the affected legs. This is a
faithful restatement of the prior re-audit's own conclusion (kelly_full pnl/auc CI =
-48.41 [-78.77, -18.63], nowhere near zero; a few cents of proxy noise on 6 of 20 rows
cannot plausibly flip that). Correctly attributed to 2026-08-27 re-audit in both
locations. Accurate, not overstated, not softened into a certainty it does not have (it
says dwarfs, not eliminates).

Row-18 / $1632.52 / $941.27 trace. SUMMARY text: bankroll_after on row 18 of Trump's
29-row ledger... ends at $941.27 / ROI -5.87%. This is the exact framing and the exact
two dollar figures independently reproduced in the prior re-audit (_reaudit.md lines
20-33, row index 17 = 18th row = $1632.523455, terminal row index 27 = $941.268694).
Spot-checked both terminal values in the fresh SUMMARY_kelly_static_combo.md
(B2_naive terminal=$941.27 ROI=-5.87%) and the HINDSIGHT-SELECTED BRACKET
flag is still attached to that same line. No drift.

One-handle framing. STUDY STATUS block correctly states Elon is the only genuinely
independent, best-instrumented result, Trump is directionally consistent but is NOT
independent statistical confirmation, names both reasons (BORROWED-CONFIG selection,
zero L2 coverage / proxy-only), and instructs the reader to treat Trump as a directional
sanity check, not a second independent data point. This is substantively the same
conclusion the re-audit reached in its own closing Does NOT establish section, now
moved from the auditor's log into the artifact itself, at the top of section 1 where a
skimming reader will see it before any Trump number.

## Check 4: framing judgment

STUDY STATUS sits as the first four lines a reader hits in section 1, before any ROI
number. It states the limitation as a directive (treat Trump as a directional sanity
check, not a second independent data point), not just a disclosed fact buried in a
footnote, this is a stronger placement than the LOW finding required, and a skimming
reader would have to actively skip four lines to miss it.

White House section (:985 comment, :1030-1033 verdict string, :1333 NOT evidence)
is untouched by this change set, confirmed by grep, identical line content to the prior
audit. It still reads as infeasible/blocked (BLOCKED: n=%d resolved+fully-covered
windows... NOT evidence), not as a second negative finding. A reader cannot mistake
WH descriptive-only for WH also disproven, the word BLOCKED and the explicit
no combo selection run on White House both survive verbatim.

## What was checked and passed

- All four disclosures located in main()'s code (not hand-edited into kelly_out/).
- Full script re-run end to end; all 9 CSV outputs plus SUMMARY.md byte-identical to the
  pre-rerun snapshot (diff -q, zero differences): confirms determinism and confirms
  the disclosures are computed live, not artifacts of a single prior run.
- RUN_META structurally identical before/after this fix once only the new
  fill_quality_split keys are stripped (full recursive dict comparison, not visual).
- 14/6/0 split re-derived from raw ledger cells plus the published l2_start_ms, from
  scratch, independent of the script's own internal arrays: exact match.
- Mixed-definition text, auditor-assessment quote, row-18 trace, and $1632.52/$941.27
  figures all checked against the prior re-audit's independently-established values:
  no drift, no softening, no new error introduced by the disclosure text itself.
- White House and Trump framing unchanged, confirmed by grep against the same line
  numbers/content as the prior re-audit.
- File scope: only kelly_static_combo_2026-08-27.py and kelly_out/ touched; prereg
  mtime (17:42) unchanged since the prior audit; git status shows no writes to any
  sibling study's files.

## What could NOT be checked (unchanged from prior audits, not reopened here)

- Did not re-derive every fill from raw L2 ticks a third time (structurally confirmed in
  audit #1, compounding arithmetic confirmed in re-audit #2).
- Did not re-verify half/quarter-Kelly bit-for-bit for every sub-span a third time.

## Plain-language close-out (for Sir, not just the record)

What this study establishes: the searched, Kelly-sized static-combo strategy loses badly
on Elon, the one handle with real order-book fills to test it against (-96.81% ROI,
sealed_l2, kelly_full). The reason is a real, independently-verified mechanism, not noise:
the market's price tracks realized outcomes to within a few cents, while the recency-
argmax combo-picker is badly overconfident, a textbook overfitting/winner's-curse signature
from searching hundreds of candidate combos each auction. A non-searched baseline (a single
bracket picked once, not re-picked every auction) also lost money on Elon, which extends
the finding beyond just the searched version of the idea.

What it does not establish: that Trump independently confirms this. Trump runs on
borrowed hyperparameters (never independently selected) and has zero real order-book data
for its tokens, so its entire result is proxy-priced. It points the same direction (also
loses, on every arm) but should be read as a sanity check, not a second data point. White
House was never tested for profit and remains genuinely open, not a third failure: too few
independent windows existed to run the simulation at all.

Bottom line: do not build or fund this strategy on Elon or Trump. Do not treat White House
as disproven, it is untested. If Sir wants a White House verdict, that needs its own,
separately pre-registered study once more resolved, non-overlapping windows exist.
