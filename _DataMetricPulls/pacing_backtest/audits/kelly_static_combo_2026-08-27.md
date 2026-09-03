# Audit: kelly_static_combo_2026-08-27

Scope class (a): claims P&L.
Prereg: _DataMetricPulls/pacing_backtest/prereg/kelly_static_combo_2026-08-27.md
Script: _DataMetricPulls/pacing_backtest/kelly_static_combo_2026-08-27.py
Outputs: _DataMetricPulls/pacing_backtest/kelly_out/

## VERDICT: WARN

Reproduced headline number: YES (exact match, see below). No fatal finding overturns
the study's PRIMARY (Elon) conclusion. One HIGH-severity confirmed defect invalidates
the "hardened real fills" evidence-quality claim for Trump specifically (does not flip
Trump's sign either, since Trump loses under both the fake-l2 and real-proxy slices).
One MEDIUM undisclosed hindsight leak in a Trump baseline. Neither is fatal to the
headline "NO" answer, but both must be fixed before Trump is re-quoted as "hardened."

## Headline reproduction (independent, from raw ledger CSV, not the script's own printout)

Elon sealed_l2 kelly_full: reported terminal $31.90 (ROI -96.81%). Recomputed row-by-row
from ledger_elonmusk_2-day.csv (trailing_hit_rate_q, combo_cost_p, kelly_f_star,
kelly_full_cost_paid, kelly_full_payout) applying f*=(q-p)/(1-p), Darwin's-Rules caps
(20% sweep / 50% single), and sequential bankroll compounding: $31.8986. Exact match.
Every stake_frac and bankroll_before/after cell matched the script's own ledger to <1e-6.

Max drawdown -96.8%: reproduced by hand from the compounded path (peak stays at $1000,
trough $31.90 -> -96.81%). P(ruin<10%)=97.2% and terminal_boot mean/median (41.0/34.4):
reproduced bit-for-bit via an independent reimplementation of bankroll_bootstrap_paths
(same seed 20260827, block=3, n_boot=2000) run against the raw ledger stake/pnl columns,
not by re-running the script.

Calibration diagnostic (the study's central mechanism claim) reproduced exactly for BOTH
handles straight from ledger CSVs: Elon mean_q=0.5522, mean_cost=0.1566, mean_realized=
0.1304 -> |q-realized|=0.4217 vs |cost-realized|=0.0262 (market better calibrated).
Trump mean_q=0.6978, mean_cost=0.2716, mean_realized=0.1905 -> |q-realized|=0.5073 vs
|cost-realized|=0.0811. Both match RUN_META and SUMMARY to 4+ decimal places.

Trial count 44 verified by summing RUN_META's trials_detail: 16 (4x4 Elon-only TRAIN
grid) + 2 (frozen ledgers) + 2 (diagnostic 6h checkpoints) + 24 (6 arms x 2 sub-regimes x
2 handles) = 44. Exact.

385-candidate-combo claim verified by combinatorics: Elon's ladder is confirmed 10 rungs
(stdout), C(10,1)+C(10,2)+C(10,3)+C(10,4) = 385.

## Findings

[CLASS B] [HIGH] Trump "sealed_l2 (hardened real fills)" label is false. Zero pmxt L2
rows exist for Trump 7-day tokens.
Evidence: stdout prints "L2 tokens indexed (best_bid stream): 0" for realDonaldTrump.
Directly queried read_l2(tokens=[...], source='pmxt', event_types=['price_change']) for
the token set of donald-trump-of-truth-social-posts-april-14-april-21 (the FIRST row the
ledger labels fill_mode=l2_hardened) and got 0 rows on both source='pmxt' and
source='both'. All 11 Trump rows labeled l2_hardened show cost_paid == stake_dollars
to the penny (perfect 100% fill on every single one), unlike Elon's genuinely hardened
rows where 4/20 show partial fills from the queue-haircut mechanic.
Root cause, kelly_static_combo_2026-08-27.py execute_arm(), around line 589:

  fill_mode=("mixed" if combo is None else
             ("l2_hardened" if T_ms >= L2_START_MS else "proxy")),

This derives the label from a TIME comparison against the global pmxt-archive start
(2026-04-13), not from the actual leg_mode leg_price() used per leg. Since bb_idx/lt_idx
are empty for Trump, leg_price() silently falls through to the proxy path for every
Trump leg (the DOLLAR figures are therefore still the same 100%-fill proxy computation
used everywhere else, not corrupted), but the ledger claims 11 of 29 Trump rows used the
stricter min-rest/depth-cap/strict-through-fill model when none of them did. This
violates the prereg's explicit line: "Where real L2 exists... use it and say so. Where
it does not, label every P&L number proxy-based." It also artificially splits Trump's
single n=29 sealed population into two block-bootstrap populations (fake-l2 n=11,
real-proxy n=18) on a false basis, weakening statistical power on each without cause.
Why it matters: does NOT flip any sign (Trump loses money in both mislabeled slices,
Kelly arms lose to B1/B4 either way) but a reader who trusts "hardened real fills" as
stronger evidence than "proxy, disclosed noise floor" is being misled for 38% of Trump's
sealed rows. Combined with the already-disclosed DEVIATION #1 (borrowed W/cap config),
Trump has now failed on a SECOND, previously undisclosed axis of "independent control"
integrity.
Fix: derive fill_mode per row from the actual leg_mode values leg_price() returned (e.g.
"l2_hardened" only if every priced leg used the L2 path), re-run, and Trump's sealed
span will almost certainly collapse into a single honest n=29 proxy-only span. Re-audit
after the fix before quoting any Trump "hardened" number.

[CLASS C] [MEDIUM] B2 naive-modal baseline for Trump is hindsight-selected and never
disclosed in any output.
Evidence: run_group() computes b2_hindsight = len(train_idx) == 0 (True for Trump, since
TRAIN=0 forces b2_pool = list(range(len(units))), i.e. the modal winning bracket is
picked using the FULL population, including sealed/future auctions). This flag is
stored on res["b2_hindsight"] but never read again anywhere in main()'s
printing/RUN_META code, and there is no b2_hindsight column in the ledger CSV. Confirmed
by grep: zero occurrences of "hindsight" in SUMMARY_kelly_static_combo.md.
Consequence: Trump's B2_naive is the single most profitable line in the entire study
(sealed_proxy terminal $1632.52, ROI +63.25%) and it got there partly by picking its
bracket with knowledge of outcomes the WALL is supposed to forbid it from seeing. The
SECONDARY criterion ("beats B2 & B4") for Trump is being scored against a leaked
baseline without a caveat, though this does not manufacture a false negative for Kelly
(a leaked-easier B2 makes SECONDARY harder to pass, not easier, so it doesn't inflate
the strategy's apparent unprofitability, it just means the comparison itself isn't a
fair test for Trump).
Fix: surface b2_hindsight next to every Trump B2_naive number, or exclude Trump from the
B2 secondary comparison entirely given TRAIN=0.

[CLASS C] [LOW] RUN_META top-level n_auctions is null.
Confirmed: kelly_static_combo_2026-08-27.run_meta.json has "n_auctions": null even
though every sub-span (elon.sealed_l2.n=21, elon.sealed_proxy.n=3, trump.sealed_l2.n=11,
trump.sealed_proxy.n=18) carries its own n/n_flag inside headline. Self-disclosed by the
builder per the task brief. Root cause: run_meta.py::emit_run_meta's schema expects one
scalar n_auctions; this study genuinely has 4+ heterogeneous populations plus a WH
descriptive n, so there is no single honest scalar to put there. Not fatal: every number
was independently recoverable and reproduced from the nested headline structure. Shared
schema gap, not specific misreporting by this script.

[CLASS D] [LOW/informational] Section 4 print-order could visually mislead on which
checkpoint the "naive reading" line refers to.
Code computes naive_confirmed from regime_stats_24 (the PRIMARY 24h checkpoint, correct
choice) but prints it immediately after the 6h DIAGNOSTIC block in the text output (loop
prints 24h block then 6h block, then the single naive_confirmed line after the loop). A
fast reader could misattribute it to 6h. The underlying regime_lag_confirmed / TERTIARY
value used everywhere else is unaffected, purely a display-ordering nit.

## What was checked and passed (dynamically confirmed, not just read)

- Headline P&L, max drawdown, P(ruin<10%), terminal-bootstrap mean/median: independently
  recomputed from raw ledger data with a from-scratch reimplementation, matched to the
  script's own output to <1e-6 / bit-for-bit (bootstrap, same seed).
- Calibration diagnostic (the mechanism claim underlying "NO"): recomputed independently
  for both handles from ledger CSVs, exact match. This is the decisive, non-circular test
  (uses realized future outcomes, not a re-derived argmax) and it is genuinely decisive:
  market cost sits within 2.6-8.1 cents of realized hit rate; the recency-argmax q is off
  by 42-51 points. Confirms the winner's-curse diagnosis is real, not asserted.
- Original regime-lag test (gap_recency vs gap_allhistory of the SAME argmax-selected
  combo) correctly self-diagnosed as tautologically circular by the builder. Confirmed
  the diagnosis is sound (a combo chosen for high recent hit rate will structurally show
  gap_recency > gap_allhistory regardless of any real market lag). The replacement
  decisive test (forward calibration against realized outcomes, an independent ground
  truth) is NOT circular and correctly drives TERTIARY=False for both handles.
- Per-auction WALL: spot-checked elon-musk-of-tweets-april-13-april-15. n_prior_used=10
  matches min(W=10, 37 true-prior auctions)=10 by manual count from the ledger's own
  start/end timestamps; the immediately-adjacent auction whose end timestamp exactly
  equals this auction's start is correctly EXCLUDED (strict "<") from the trailing pool.
  No boundary leak.
- Zero-edge control: uses the identical execute_arm/fill pipeline as every real arm (only
  the combo-selection step is randomized), so it cannot be artificially harsh or lenient
  relative to the real arms, structurally a fair integrity check. All 4 sub-results show
  CI including zero. Clean.
- Trump TRAIN=0 infeasibility (DEVIATION #1): confirmed via stdout ("TRAIN=0 SEALED=29")
  and canonical data (11-bucket 7-day ladder does not exist before 2026-02-06); the
  BORROWED-CONFIG label is present on every Trump section checked in SUMMARY and RUN_META.
- White House infeasibility (DEVIATION #2): reproduced from white_house_descriptive.csv.
  9 L2 windows, exactly 4 with a computable winner (post-backfill coverage ends
  2026-07-10, correctly cutting off the later 5 windows), all 4 landing >=180 as claimed,
  correctly labeled "NOT evidence" given n=4 < SUCCESS_N_FLOOR=10 and overlapping windows.
- Kelly formula and sign: f*=(q-p)/(1-p) independently recomputed and matched for every
  sealed Elon row; f* never floored to a positive minimum (untraded/no-edge rows
  correctly stake 0).
- Darwin's-Rules bankroll caps (20% sweep / 50% single-leg) verified applied exactly in
  every reproduced row.
- Maker-only / no taker fee needed: leg_price() explicitly returns (None,None) rather
  than crossing the visible ask (post-only reject, not a fictional fill), confirmed by
  code read; consistent with the "MAKER-ONLY. Zero maker fee." RUN_META fills string.
- Elon's L2-hardened fill mechanic independently confirmed REAL: 4 of 20 sealed_l2
  traded rows show cost_paid strictly less than stake_dollars (partial fills from the
  queue-haircut/depth-cap mechanic acting on genuine last_trade_price prints), proves the
  hardened model actually binds for Elon, unlike the Trump mislabeling above.
- File scope / prereg integrity: prereg file mtime (17:42) precedes script mtime (18:12)
  precedes output mtime (18:14), correct chronology, no evidence of post-hoc editing.
  git status shows no writes to pattern_discovery_*, regime_*, extract_rules_*,
  combo_out/, rules_out/ from this run.

## What could NOT be checked

- Did not re-pull the raw pmxt L2 tick stream and hand-verify every one of Elon's 21
  fills from first principles; confirmed the mechanism structurally (partial fills
  present, formula matches) rather than exhaustively re-deriving each fill.
- Did not re-audit the canonical auctions/prices parquet tables' own row-level
  correctness (winner labels, bucket parsing) beyond the prior PASS audit
  (audits/bracket_combo_ev_2026-07-31.md) this study inherits data from.
- Did not re-derive the WH post-backfill parquet's tweet counts from raw data; took the
  reported n=4/9 and coverage window at face value after confirming the CSV output
  matches.
- Half-Kelly and quarter-Kelly ruin/drawdown figures were not bit-for-bit re-derived for
  every arm (only kelly_full was fully independently reproduced); same methodology
  applies so this is a spot-check extrapolation, not exhaustive per-arm verification.

## What this result establishes, and what it does not

Establishes (high confidence, independently verified):
- The specific tested strategy, a per-auction, argmax-over-~385-combos,
  10-auction-window, Kelly-sized ladder-combo bet, loses badly on Elon's real
  hardened-fill sealed span, and the reason is a genuine, independently-confirmed
  winner's-curse/overfitting artifact (market cost tracks realized hit rate to within a
  few cents; the recency-argmax estimate does not). This is Elon's PRIMARY,
  best-instrumented result and it holds up.
- Even a non-per-auction-searched baseline (B2, TRAIN-selected ONCE on Elon, not
  re-picked every auction) also lost money on Elon (-86.29% ROI, sealed_l2), which is
  additional, non-circular evidence against Sir's literal hypothesis for Elon
  specifically, not just the searched/Kelly-sized version of it.
- The calibration finding (market cost roughly equals realized hit rate within 2.6-8.1
  cents) is arguably the strongest single piece of evidence here: it says the market is
  NOT systematically underpricing any particular bracket, searched or not, which is a
  more direct answer to "is there free money in the ladder" than the P&L simulation
  alone.

Does NOT establish:
- That Trump independently confirms the same conclusion with equal strength. Trump was
  already flagged BORROWED-CONFIG (no independent hyperparameter selection); this audit
  additionally found its "hardened real fills" section is mislabeled proxy data, and its
  B2 baseline is hindsight-selected. Trump should be read as directionally consistent
  (also loses) but NOT as independent statistical confirmation until the fill_mode fix
  and a re-audit.
- Anything about White House. Sir's WH hypothesis (180-200+ modal) was explicitly
  BLOCKED for P&L (n=4 resolvable windows, non-independent, below SUCCESS_N_FLOOR=10)
  and only a descriptive distribution was reported. "4/4 landed >=180" is directionally
  suggestive but is NOT evidence of anything tradeable, this remains genuinely untested,
  not "also no."
- That a literally-fixed, never-reselected, pre-committed single bracket (chosen purely
  a priori, with zero historical selection of any kind) is unprofitable. B2 is the
  closest proxy tested (TRAIN-selected once for Elon, not re-optimized per auction) and
  it also lost, which is suggestive, but a truly zero-selection arm was never isolated
  as its own line. Given the calibration evidence, it is unlikely such an arm would fare
  better, but that specific claim was not directly tested.
