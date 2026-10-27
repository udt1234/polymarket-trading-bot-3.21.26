# Audit: pure_maker_momentum_scalp.py (2026-10-27)

- Auditor: @backtest-auditor (log written by main session; auditor's own write was permission-denied)
- Script: `_DataMetricPulls/pacing_backtest/pure_maker_momentum_scalp.py`, branch `claude/polymarket-momentum-backtest-2IDby`, commit f1a8d85
- Run: 2026-10-27T19:18Z, default args, 49s, exit 0
- Data: `canonical/_raw_imports/api_trades_v2` (300 files; `whale_analysis` absent, silent fallback) + `canonical/auctions`

## VERDICT: FAIL

Headline (+1.114 spec) reproduced exactly from the ledger, and invalid.

| mode | total | ex-rebate | fills |
|---|---|---|---|
| spec | +1.114 | -4.446 | 347 |
| hardened | -4.936 | -4.936 | 334 |
| control_spec | +3.136 | -13.164 | 927 |
| control_hardened | -15.630 | -15.630 | 889 |

## Findings, most severe first

1. **[B] FATAL: headline is 100% booked maker rebate.** Spec total +1.114 = spread +14.63, rebate +5.56, resolution -19.076 (lines 57, 153, 156, 289). Per-fill rebate is forbidden as P&L under project rules. At a 100% pool share the per-share ceiling is 0.0014 to 0.0044, but the script credits 0.01 per leg.
2. **[B/D] FATAL to the claim: loses net of rebate, refuted (not merely unproven).**
   - Ex-rebate CI is [-8.19, -0.56] by auction and [-8.27, -0.51] by calendar week (55 clusters). Negative in 2024, 2025 and 2026.
   - Six re-run variants range from -3.0 to -4.7: latency 2s and 5s, side-aware entry, side-aware entry with strict exit, 0.01-tick floor, and strict plus latency plus side.
   - The cause is structural. 0 of 138 resolution holds won, because a winner runs through the +0.07 sell first. The payoff is capped at +0.07 against a mean loss of 0.138, so break-even needs 66.4% target hits; the run saw 60.2%.
3. **[B] HIGH: the script's "CONTROL PROFITABLE -> FILL MODEL IS FANTASY" verdict is a rebate artifact.** Lines 393-395 test `total>0`, which includes the rebate. Control ex-rebate is -13.164 (-0.0142 per fill, CI excludes zero). The control is a negative-edge benchmark and proves nothing about fill realism.
4. **[B] HIGH: fill rate misstated.** The 4.87% divides by all breakouts, but 6419 of 7122 were skipped as busy. The true per-order touch fill rate is 49.4% (347/703), or 46.5% strict. Optimistic: no queue model.
5. **[B] MEDIUM: fill realism gaps, all pushing results down.** 11.4% of trigger fills are exact-price touches with no queue. Latency is zero. The `side` column is ignored, and 14.1% of fills come from buyer-initiated prints.
6. **[B] MEDIUM: tick validity.** Line 133 rounds entries to a 0.001 grid, and 62.2% of spec entries are off the 0.01 grid. Tick history is unavailable (UNVERIFIED). The 0.01-grid variant is -3.000.
7. **[A] MEDIUM: `whale_analysis` fallback (lines 263-264).**
   - Coverage is not lost. `api_trades_v2` has at least the canonical `n_trades` in all 297 matched files (mean 1.81x, max 10.1x), with 0 duplicate transaction hashes across 8.96M rows.
   - Provenance differs. It is a June 2026 Data-API re-pull, not the frozen archive, and the fallback is silent.
   - 30 of 273 tapes end more than 1h before window end (up to 206h), and 8 have zero window overlap. They contributed 1 fill, so there is no headline effect, but no gate catches it.
8. **[A] MEDIUM: `start_utc` used for the year (line 314).** `january-1-january-3` and `january-2-january-9` get year 2025, so their windows land a year early and all prints drop. They are still counted in `auctions_used`. The same latent pattern exists in `bracket_hit_backtest.py:38`.
9. **[D] MEDIUM: effective n overstated.** The 118 auctions with fills span only 55 calendar weeks. 85 of 347 fills (24%) come from arch/higher/lower/continued sibling events, which `bracket_hit_backtest.py:35` excludes.
10. **[C] MEDIUM: provenance.** Not built by @backtest-builder. "PRE-REGISTERED" is unverifiable from a single wip commit. The RUN_META headline leads with the rebate-inflated number and has no validity flag.
11. **[A] LOW:** 24 unparseable slugs were excluded, including 2 valid weekly "between-X-and-Y" windows (disclosed).

## Trigger vs control

- Per-fill spec minus control is +0.0014, CI [-0.0107, +0.0147], clustered by auction. Hardened is +0.0028, CI [-0.0098, +0.0161]. Not distinguishable.
- A matched diagnostic (every eligible print as its own order, not executable) gives momentum minus non-momentum at +0.016 per fill, CI [+0.001, +0.029]. It is unstable: the early half is -0.006 and the late half +0.011, the sign flips by entry-price band, and dropping one auction (march-10-march-17) turns it negative. This is a hypothesis only.

## Checked and passed

- **THE WALL:** recomputed with later prints masked over 31,966 random decisions in 40 files, with 0 mismatches. No resample, rolling or center usage. The winner is read only at settlement.
- **Event-driven and maker-only:** every print is replayed, no taker fills, fee 0 both sides.
- **`noon_window()`:** all 546 endpoints are 12:00 ET, and DST weeks come out at 167h and 169h.
- **Settlement truth:** 260 of 269 winners end at or above 0.9 on the tape, and 4112 of 4114 non-winners end at or below 0.5. The exceptions are all early-ending tapes. 3 ambiguous winners are excluded (Rule 7).
- **RUN_META:** `model_version` matches `locked_pace.MODEL_VERSION`.

## Not checkable

Real L2 queue and depth; per-market tick history; whether the constants were fixed before seeing data; the `whale_analysis` contents (absent); live latency.

## Recommended next move (auditor)

If it is pursued at all, rebuild via @backtest-builder with these changes:
- Rebate fixed at 0.
- Headline gated on ex-rebate P&L.
- A matched, side-preserving zero-edge control.
- A loud archive-fallback warning.
- A tape-end gate.

Only the matched momentum-vs-non-momentum difference merits a held-out test.

## Rerun after Codex fixes (2026-10-27)

- Auditor: @backtest-auditor (re-audit). Worktree branch `claude/polymarket-momentum-backtest-2IDby`, baseline ac0b116, dirty (patch uncommitted, 3 tracked files modified).
- Reproduction: four fresh runs against canonical data (`--root` main checkout, `--out-dir` scratch), never over the worktree outputs. Scratch: `<scratchpad>/aud/{old,s23,f1,new}`. Old = unpatched ac0b116. s23 = fixes 2 and 3 only (the builder script). f1 = fix 1 only (my own revert of fixes 2 and 3 from the patched script). new = the patched script, byte-identical to the worktree copy.

### VERDICT: FAIL (unchanged)

The three fixes are correct and narrow. None of them rescues the claim; they make it worse. Do not quote TOTAL +0.886. The quotable number is spec ex-rebate -9.304, by-auction 95% CI [-13.823, -4.640], n=152 auctions.

### Headline reproduced from the ledger (76,559 rows, recomputed with pandas)

| mode | fills | spread | rebate | resolution | TOTAL | ex-rebate |
|---|---|---|---|---|---|---|
| spec | 654 | +25.550 | +10.190 | -34.854 | +0.886 | -9.304 |
| hardened | 629 | +24.430 | 0 | -33.982 | -9.552 | -9.552 |
| control_spec | 1799 | +92.190 | +31.160 | -102.831 | +20.519 | -10.641 |
| control_hardened | 1723 | +87.360 | 0 | -102.035 | -14.675 | -14.675 |

- Reproduced yes, but reproduced-but-invalid: spec TOTAL +0.886 is less than its own booked rebate (+10.190). Ex-rebate by-auction CI reproduced exactly with seed 20260101, 5000 resamples. Seeds 1, 2, 3 give upper bounds -4.64 to -4.73. Calendar-week clusters (66): [-14.770, -4.135]. Drop-best-auction: -10.110. Only 50 of 152 auctions are positive.
- A fresh run of the worktree script gives a ledger and results identical to the committed worktree outputs.

### Fix review

- Fix 2 and 3 only (old vs s23): ledgers identical on every column except `te` of resolution rows (inf becomes w1). Breakouts 7122, fills 347/334/927/889, totals, win rates and by-auction CIs identical. Only DD and peak capital move (spec peak capital 19.076 to 0.810; control_spec DD 3.007 to 2.830).
- Fix 1 is the only change that touches P&L: breakouts post-filter 7122 to 13735, fills 347 to 654, instruments passing liquidity 312 to 643. new vs f1 ledgers are identical except `te`.
- Fix 1 correct: the archive `notional` column equals price*size on all 8,956,477 rows (max deviation 0.0). Old code counted No prints at $38.2M mirrored versus $400.5M raw (10.5x understated). The usd is per print, summed over indices <= i, so no new look-ahead. WALL mask test on the patched `build_signals`: 20,800 decisions in 43 files, prints with ts > t removed, 0 mismatches on in-bracket, liquidity and momentum masks (2,998 liquidity-true cases).
- Fix 2 correct: independent recompute of DD by (te, tf, t) matches the script exactly (spec 2.605, hardened 9.737, control 3.169, control_hardened 15.588). Ordering by entry time gives 2.268, 9.689, 2.311, 15.241, so booking at entry understated spec DD by 0.337.
- Fix 3 correct: w1 is the slug-parsed noon-ET end (`noon_window`), not trade-derived. All 1,526 resolution rows have te at 12:00:00 ET, one te per auction, te month/day equals the slug END date in 164 of 164 auctions, tf < te, max hold 4.63 days. Peak capital recomputed independently: 1.045, 0.982, 3.635, 3.475 (exact match).
- Diff vs ac0b116 is 21 lines in the script, nothing else. `te` feeds only `drawdown()`; `busy_until` for holds is still inf, so fills are untouched.

### Structural finding, updated

| | old spec | new spec | new hardened | new control_spec |
|---|---|---|---|---|
| fills | 347 | 654 | 629 | 1799 |
| target exits | 209 (60.23%) | 365 (55.81%) | 349 (55.48%) | 1317 (73.21%) |
| resolution holds | 138 | 289 | 280 | 482 |
| holds that won | 0 | 0 | 0 | 0 |
| mean hold loss | -0.1382 | -0.1206 | -0.1214 | -0.2133 |
| break-even target-hit rate | 66.38% | 63.27% | 63.42% | 75.29% |

- Spec: break-even 63.27% against actual 55.81%, a 7.5 point shortfall (old: 6.2). Still structural: a winning bracket runs through the +0.07 sell first, payoff capped at +0.07 against a mean loss of 0.12.
- With the 0.01 rebate per leg included, break-even drops to 55.13% versus 55.81% actual: the entire headline edge is the rebate.

Ex-rebate by fill year (ET), spec / hardened / control_spec:

| year | spec n, ex-rebate | hardened | control_spec n, ex-rebate |
|---|---|---|---|
| 2024 | 3, -0.315 | -0.315 | 3, -0.477 |
| 2025 | 199, -3.500 | -3.590 | 563, -5.088 |
| 2026 | 452, -5.489 | -5.647 | 1233, -5.076 |

Negative in every year and every mode. Decomposition of the fix 1 change: the 329 fills common to old and new sum to -4.685 ex-rebate; the 325 new-only fills (mean entry 0.119, tail brackets) sum to -4.619; 18 old-only fills sum to +0.239. Both halves are negative, so the sign is not sensitive to the liquidity definition.

### Trigger vs control (new numbers)

- Executable control (same mechanics, same filters, fires on every eligible print), ex-rebate per fill, auction-clustered bootstrap (165 clusters): spec -0.01423 vs control -0.00591, difference -0.00831, CI [-0.01627, -0.00029]. Hardened -0.01519 vs -0.00852, difference -0.00667, CI [-0.01461, +0.00122]. The trigger is worse than the zero-edge control, and worse in every entry-price band.
- The old comparison (+0.0014 per fill, indistinguishable) has flipped sign. The two are not a matched pair (control entries skew to 0.20 to 0.40, trigger to under 0.20), so read it as no edge, not as a proven negative edge.
- Matched non-executable diagnostic (every eligible print its own non-blocking order, 771,577 candidates, 13,735 momentum): momentum minus non-momentum +0.00152 per order, CI [-0.00361, +0.00619] (hardened +0.00103, CI [-0.00380, +0.00550]). Includes zero. Early half -0.000005, late half +0.0033. Sign flips by band (0.10 to 0.20 and 0.30 to 0.40 negative), by year (2024, 2025 negative; 2026 positive). The momentum arm itself is net negative per order (-0.00028). Hypothesis only, not evidence.
- Rebate-only artifact still: control_spec TOTAL +20.519 is +31.160 rebate on -10.641.

### Findings, most severe first

1. [B] FATAL (unchanged) Headline TOTAL +0.886 is 100% booked per-leg maker rebate (+10.190); the rebate is a discretionary pool, not a per-fill credit. `run_meta` headline `net_pnl_usdc` still leads with it and carries no validity flag. Fix: headline on ex-rebate only.
2. [B/D] FATAL to the claim: ex-rebate -9.304, CI [-13.823, -4.640] by auction, negative in 2024, 2025 and 2026, hardened -9.552. Refuted, not merely unproven.
3. [B] HIGH Trigger underperforms the zero-edge control per fill (CI excludes zero for spec). No evidence the momentum filter adds anything on an executable basis.
4. [B] HIGH (unchanged, unfixed) Lines 394 to 396 test `control total > 0`, which includes rebate, so `control_verdict` and the results.md header still say `CONTROL PROFITABLE ... FILL MODEL IS FANTASY`. Control ex-rebate is -10.641 and -14.675. The string reaches the right conclusion for the wrong reason. Fix: test ex-rebate and say so.
5. [A] MEDIUM Liquidity definition. Raw price*size counts a $0.95 No print at full $ notional, so $50k of No-side volume can be about $2.6k of Yes-side risk. It matches the archive `notional` column, so it is defensible, but it doubled the universe (312 to 643 instruments) and the spec text (trailing-24h notional) does not say which. Not a bug; the sign of the result is insensitive to it. Pre-register the definition.
6. [C] MEDIUM Provenance: RUN_META `git_sha` is ac0b116 but the run came from a dirty tree, so the sha does not identify the code. Commit the patch before quoting.
7. [B] LOW `max_dd_pct_of_peak_capital` (249%, 992%, 87%, 449%) and `max_dd_pct_of_peak_equity` are meaningless: peak capital is about $1 for 1-share positions. Read max DD in dollars. DD is realized-only (holds booked at the noon-ET window end, not at payout), so it understates path risk.
8. [A] LOW Elon-only result: 653 of 654 spec fills are Elon, 1 is Trump. Trump is effectively untested.
9. [D] CORRECTION to my original finding 9. The claim of 85 of 347 fills (24%) from sibling events used the pattern `arch-|higher-bra|lower-bra`, which also matches `march-` in any March slug. True nonstandard sibling slugs are 10 of 347 (2.9%) old and 22 of 654 (3.4%) new, ex-rebate -0.211. The same regex sits at `bracket_hit_backtest.py:35` and silently drops every March auction there (out of scope, flagged for the owner).
10. [B] MEDIUM (unchanged) Fill realism gaps push results down only: touch fill with no queue, zero latency, side column ignored, 65.6% of spec entries off the 0.01 grid (62.2% before). True results are worse than -9.304.

### Checked and passed

- Winner coverage: 3 ambiguous-winner auctions, 0 fills in them (Rule 7). Tape-end gate: 1 of 152 spec-fill auctions has a tape ending more than 1h early (34.6h), 1 fill (-0.15); restricting to full-tape auctions gives -9.154 on 151 auctions.
- Event-driven, maker-only, no taker fills, fee 0, no resample or rolling. Window from slug, DST-correct.

### Not checkable

Real L2 queue and depth, per-market tick history, live latency, rebate pool share, whether the constants were fixed before seeing the data, `whale_analysis` contents (absent; the `api_trades_v2` fallback is still silent).
