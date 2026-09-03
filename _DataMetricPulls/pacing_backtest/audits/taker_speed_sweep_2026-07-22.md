# Backtest Audit — taker_speed_sweep.py

- **Auditor:** backtest-auditor
- **Date (UTC):** 2026-07-22
- **Target script:** `_DataMetricPulls/pacing_backtest/taker_speed_sweep.py`
- **Outputs audited:** `audit_out3/taker_speed_sweep.csv`, `audit_out3/taker_speed_trades.csv`, `audit_out3/legiso.json`
- **Claim(s) under audit:**
  1. (original) "the taker tweet-reaction play loses at every latency including 0ms because the spread is 8-10x the signal."
  2. (correction, 2026-07-14, in memory `tweet-reaction-speed-test`) "shorting the near-money (15-65c) bracket is **+4.4/$100 at 0-150ms**, break-even ~300ms, negative beyond 400ms."

---

## VERDICT: **FAIL**

**Do not trust the "+4.4/$100 short near-money = +EV taker edge" number. Do not build a taker speed lane on the strength of it.**

The headline "+4.4/$100" reproduces **exactly** — but ONLY with the taker fee set to **zero**. The play is, by its own construction, a **taker** play (it walks the ask/bid ladder and crosses the spread). With the realistic taker fee the script itself defines (`FEE_RATE=0.05`, "verified sports/worst"), the identical leg is **-2.8/$100 at 0ms and negative at every latency**. The "+EV" reading is an artifact of dropping the fee that this strategy must pay.

Note: verdict #2 (correction) is the FAIL. Verdict #1 (original "loses at every latency, net of fee") is, ironically, the number this audit **confirms** — net of the taker fee the play loses everywhere.

---

## Reproduced headline number: **YES (and that is the problem)**

Recomputed directly from `taker_speed_trades.csv` (short leg, entry_vwap ∈ [0.15, 0.65), exit T+60s, clip=$50), ROI per $100 by latency [0,50,100,150,250,400,500,750]:

| Fee | 0ms | 50 | 100 | 150 | 250 | 400 | 500 | 750 |
|---|---|---|---|---|---|---|---|---|
| **0.0 (claimed)** | +4.4 | +4.4 | +4.4 | +4.4 | +0.8 | -1.0 | -2.2 | -2.6 |
| **0.0 (reproduced)** | +4.42 | +4.42 | +4.42 | +4.4 | +0.83 | -1.0 | -2.2 | -2.6 |
| **0.05 (realistic, reproduced)** | **-2.83** | -2.83 | -2.83 | -2.87 | -6.57 | -8.47 | -9.72 | -10.18 |

The claimed curve matches the **zero-fee** column to the decimal. `legiso.json` on disk stores `short_nearmoney = [4.4,4.4,4.4,4.4,0.8,-1.0,-2.2,-2.6]`, i.e. the persisted headline is the zero-fee curve. Fee drag on this leg is a flat **~7.2-7.5 ROI/$100 round-trip** — larger than the entire ~4.4 gross edge.

---

## Findings — most severe first

### [CLASS B] [FATAL] The actionable "+EV" headline omits the taker fee the play must pay
- **Evidence:** headline `short_nearmoney[0ms]=+4.4` reproduces only at `fee=0.0` (recomputed: +4.42 zero-fee vs **-2.83 at fee 0.05**). Script defines `FEE_RATES = [0.05, 0.0]` with the comment "0.05 = verified sports/worst; 0.0 = zero-fee" (`taker_speed_sweep.py:52`) and `fee = shares*rate*p*(1-p)` (`:221-222`).
- **Why it makes the result wrong:** the strategy's mechanism is *taking stale liquidity* — it walks the ask ladder to buy and hits the bid ladder to short (`walk_buy`/`sell_shares`, `:183-219`; docstring `:11-17`). A taker on Polymarket V2 pays the dynamic taker fee; makers pay zero (project memory `lesson_clob_v2_execution_specs.md:21`, `lesson_maker_not_taker.md`). Quoting the **zero-fee** curve as the edge models a maker execution of a taker-only play. That is self-contradictory: you cannot both cross the spread to hit stale liquidity AND pay the maker (zero) fee.
- **Fix:** report this leg net of `FEE_RATE=0.05` only. Net of fee the curve is negative at every latency → the correct conclusion is verdict #1 (original), i.e. the taker play loses. If a maker version is wanted, it must be modeled as a resting post-only quote with queue position and adverse selection (a maker resting ±1 through a tweet is filled on the wrong side — see memory §"CAN WE CAPTURE IT? NO"), not as this taker sim with the fee zeroed.

### [CLASS D] [FATAL] Net-of-fee edge is negative with 98% confidence; even the zero-fee edge is tail-concentrated
- **Evidence (bootstrap over 114 independent tweets, 5000 resamples, seed 0):**
  - Zero-fee: point +4.42, 95% CI **[+2.14, +6.99]**, P(>0)=100%.
  - Fee 0.05: point -2.83, 95% CI **[-5.19, -0.12]**, P(>0)=**2%**.
  - Concentration: of $285.25 total zero-fee profit over 132 legs, **one trade = $46.33** and top-5 trades = ~$139 (49% of net). One slug (`july-3-july-10`, 76 of 132 legs) contributes **$171.59 of $285**; slug `june-30-july-7` is net **-$10.75**. Win rate **50.8%** (coin flip). Median per-share capture only **0.19c** (mean 1.49c, tail-driven).
- **Why it makes the result wrong:** the realistic-fee edge is statistically negative (CI excludes zero on the losing side). The zero-fee edge that survives is small, tail-driven, and rests on a single auction/single trade — remove the fattest trade or the top slug and +4.4 collapses toward break-even before fees.
- **Fix:** report n (independent tweets, not latency-duplicated legs), a bootstrap CI, and the leave-one-slug-out stability. Treat as unproven.

### [CLASS D] [HIGH] Multiple-testing: the winning leg is best-of-~10, reported without correction
- **Evidence:** `legiso.json` computes 10 leg×entry-bucket curves (`short/long` × `<5c, 5-15c, 15-35c, 35-65c` + 2 `nearmoney`). The reported winner `short_nearmoney` (and the "strongest 35-65c, n=22" sub-bucket) is the single best of those 10. The script's own `taker_speed_sweep.csv` also sweeps 287 cells (2 fee × 2 exit × 3 play × 3 clip × 8 lat).
- **Why it makes the result wrong:** picking the best entry-bucket × leg post hoc inflates the headline; the "+11 fast, n=22" 35-65c sub-bucket is exactly the seesaw/kalman "best-of-N at tiny n" pattern this project has been burned by.
- **Fix:** treat +4.4 (zero-fee) as an upper bound; the honest number is the pre-registered "short the near-money" leg net of fee = negative.

### [CLASS B] [MEDIUM] Gross mid-to-mid is presented alongside as if capturable
- **Evidence:** `gross_mid = shares*(mid_out-mid_in)` (`:293, :307`); memory quotes "gross mid-to-mid +8.3 ROI/$100 @0ms." The audited winning leg's own per-share edge is a mid move that the taker cannot realize after crossing the spread.
- **Why it matters:** mid-to-mid moves are not tradeable P&L (BACKTEST_RULES / this project's repeated "mid is not capturable" finding). Fine as a *diagnostic* of signal strength, but it must never be read as the edge — and the net-of-fee number shows it isn't.
- **Fix:** keep gross_mid labelled strictly as signal diagnostic; the decision number is net-of-taker-fee fills only.

---

## What was checked and PASSED (coverage, not a certification)

- **Look-ahead / THE WALL (Pass C):** entry fills read at the tweet+latency time; exit read at T+latency+exit_s (strictly later). Entry price is floored/capped at the *fresh* `price_change` best (`pc_at`, `FRESH_MS=5000`) so a stale book snapshot cannot gift a pre-jump price. Confirmed empirically: mean entry_vwap is flat 0→150ms (0.2643) then *falls* with latency (0.2521 @750ms) — the expected "stale liquidity reprices" signature, not a leak. Gamma winner used only for the secondary hold-to-resolution scoring (`:309-319`). **No look-ahead leak found in the audited leg.**
- **Round-trip accounting (Pass B):** `cash == shares*(entry_vwap - exit_vwap)` to max abs diff 0.0 — internally consistent.
- **Token/price coverage (Pass A, the -$824 bug):** N/A-clean here. The script reads pmxt L2 **by slug**, not by canonical `bracket_yes_token_ids`, so the canonical-token-gap silent-skip does not apply. Verified the top-contributing slug (`july-3-july-10`) has 32,577 book rows across 26 brackets — real, tradeable data, not a silent skip.
- **Canonical/source (Pass A):** reads pmxt L2 archive (`api.modules.shared.l2_history`) + `elon_backfill_ext_to_2026-07-10.parquet` (X-API tweet times, same ms-UTC clock as L2). Both files present. Acceptable sources for a speed backtest (pmxt is the approved L2 archive).
- **Window / timezone (Pass A):** noon-ET parsed from the slug (`noon()`, `:77-83`), not from trade-derived start/end. Correct per the canonical-window rule.
- **Event-driven (Pass C):** iterates every counting tweet and reads book/quote at event time; no `resample`/`rolling`/`freq=` bar aggregation. Compliant for a speed strategy.
- **Determinism:** no RNG in the sim; outputs are a deterministic function of the input parquets. Headline reproduces bit-for-bit from the trade CSV.

## What could NOT be fully checked

- **Full end-to-end re-run** of `taker_speed_sweep.py` (all 8 slugs, Gamma fetches) was not run to completion under the ~2-min budget (it makes live Gamma HTTP calls per slug and loads 2,221 pmxt files). Mitigation: reproduced the headline directly from the persisted `taker_speed_trades.csv` (which the script writes at `:327`, before any fee/aggregation), and independently confirmed the top slug's raw book data loads and matches the CSV's per-slug cash. Confidence in the reproduction is high; confidence that re-running regenerates an identical trade CSV is medium (not executed).
- **Maker-side realism** of any "rest instead of take" alternative was not modeled here (out of scope for this taker script); project memory already concludes a passive maker through a tweet is adversely selected.
- **Depth realism beyond $50 clip:** the script/memory already flag $100+ walks negative; not re-audited in detail since the $50 case already fails net of fee.

---

## Bottom line for the caller

The "+4.4/$100 short-the-near-money taker edge" is a **zero-fee** number for a **taker** play. Apply the taker fee the strategy must pay and it is **-2.8/$100 at 0ms, negative at every latency, P(>0)=2%**. The original "taker loses at every latency net of fee" verdict is the correct one; the 2026-07-14 "correction" that revived it as +EV is the error. Elon-tweet taker speed remains **not an edge for us**.
