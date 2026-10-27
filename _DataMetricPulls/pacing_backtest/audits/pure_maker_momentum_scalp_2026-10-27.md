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
