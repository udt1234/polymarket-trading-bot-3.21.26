# Backtest Audit - wh_pace_port_backtest.py

- Auditor: backtest-auditor
- Date (UTC): 2026-07-24
- Target script: `_DataMetricPulls/pacing_backtest/wh_pace_port_backtest.py`
- Reference/exemplar under re-examination: `_DataMetricPulls/pacing_backtest/phase_wh_maker.py`
- Outputs audited: `audit_out3/wh_pace_port_ledger.csv`, `audit_out3/wh_pace_port_auction_summary.csv`, `audit_out3/wh_pace_port_backtest.run_meta.json`, `run_out.log`
- Claim under audit: WH n=5 net=+$613.7 (ROI +63.2%, 181 fills); Elon control n=3 net=+$5830.2 (ROI +136.5%, 510 fills); zero-edge baselines WH=-$69.3, Elon=+$3283.3; builder own verdict wh_beats_control=False, "NO EDGE PROVEN, INCONCLUSIVE at this n."

---

## VERDICT: FAIL

Do not trust either P&L number (WH +613.7 or Elon +5830.2). Do not use them to size real capital or to justify a WH pilot. The builder own "inconclusive, no edge proven" framing is honest as far as it goes, but this audit found something stronger than "unproven": a dynamically-confirmed residual fill-model defect that inflates P&L on both the model-informed strategy and the zero-informational-edge control, on both WH and the "documented-efficient" Elon market. More data collected under this same fill model will not fix it - the fill mechanic itself needs to change before any number from this family of scripts is trustworthy.

---

## Reproduced headline number: YES, exactly - and it is reproduced-but-invalid

Recomputed directly from wh_pace_port_ledger.csv (cost = sum of fill_price times shares, payout = sum of won times shares):

| fam | cost | payout | net (recomputed) | net (claimed) |
|---|---|---|---|---|
| WH | 970.40 | 1584.15 | 613.75 | 613.75 |
| ELON | 4271.40 | 10101.65 | 5830.24 | 5830.24 |

Per-auction net, bootstrap CI, and jackknife also reproduce exactly from run_out.log and RESULT_JSON. This is a clean, byte-exact reproduction - see "Dynamic confirmation" below for why it is nonetheless invalid.

---

## Findings - most severe first

### [CLASS B] [FATAL - dynamically confirmed] Residual maker fill-model optimism survives the fix; the "documented-efficient" Elon zero-edge control does not collapse under hardened fills
- Evidence: Re-ran the identical event stream (precompute_slug output, pickled and reused so the comparison is apples-to-apples) through a hardened run_config with three independently-toggleable realism knobs: (a) an extra tick-margin on the through-fill test, (b) a queue/depth haircut on the fillable size (should not assume 100% of a real print size is capturable), (c) a minimum rest time before a quote can be credited with a fill. Zero-edge baseline results (headline config: strict, margin 0.03, clip $250, gate on):

  | hardening | WH baseline net | ELON baseline net |
  |---|---|---|
  | none (original) | -69.3 | +3,283.3 |
  | +1 tick margin | +340.6 | +2,714.6 |
  | +2 tick margin | +319.8 | +2,689.7 |
  | 50 pct queue haircut | +257.5 | +2,524.9 |
  | 25 pct queue haircut | +40.6 | +2,100.0 |
  | min-rest 5s | -71.6 | +2,658.7 |
  | min-rest 30s | -67.7 | +2,056.5 |
  | COMBINED (1 tick + 50pct queue + 5s rest) | +44.3 | +2,176.3 |
  | COMBINED-HARD (2 tick + 25pct queue + 30s rest) | +62.9 | +131.6 |

  Under every single hardening tested, including a genuinely punishing combined stress test, the Elon zero-informational-edge control (quotes unconditionally whenever post-only-feasible, no model opinion) remains positive. It shrinks, it never goes to zero or negative. A real, uninformed liquidity-providing strategy on a market with no edge should not robustly clear $2,000+ across nine different fill-realism assumptions.
- Why it makes the result wrong: BACKTEST_RULES / Pass B is explicit that a market/hold baseline showing profit in-sim is a RED FLAG for a look-ahead or fill bug, not a triumph. The sim credits our hypothetical resting quote with 100 percent of every qualifying print size, with no queue-position competition (other real makers already resting at the same improved price) and no market-impact adjustment (our own order presence would itself change what actually prints). Both the WH headline (+613.7) and the Elon control (+5830.2) inherit this same optimism, since they use the identical run_config fill mechanic - only the model-edge gate differs from the baseline.
- This is not a new suspicion - it corroborates two prior independent findings the project already has on file:
  1. memory market_hunt_2026_07_13.md: "The Elon CONTROL netted +$4,237/+125% but that is a small-n... artifact - NOT a real maker edge... The verify agent flagged the null as broken."
  2. memory crypto_sweep_backtest.md / reward_farm_verified.md: genuine maker fills on Elon are documented as rare/fragile/adversely selected and reward-pool-limited to losses, not $2,000-9,000 in profit from passive liquidity provision over 3 auctions.
  This hardening sweep is a third, independently-derived confirmation of the same underlying truth, via a completely different method (fill-model stress test rather than a flow-count or pool-size argument).
- Fix: model queue position explicitly (assume we are NOT first at best_bid+tick - other real makers plausibly already occupy an improved level the instant it becomes visible) and market impact (crediting the full print size to a hypothetical order overstates the achievable fill). Cross-validate the sim implied fill rate/profitability against the project own live paper-trading maker fill data (reward_farm_replay.csv, mirror_trader paper runs) before trusting any number from this fill mechanic again.

### [CLASS B] [HIGH - dynamically confirmed, historical] phase_wh_maker.py ambient-bid fill test is a real, quantifiable bug (about 21-29 pct phantom fills) - already removed from backtest-auditor.md exemplar list but NOT from backtest-builder.md
- Evidence: `phase_wh_maker.py:214` - `hit = (pn < bid) if strict else (pn <= bid)`, where `bid` is the loop-local ambient best_bid captured at the current print own snapshot (`phase_wh_maker.py:184`, `bid = bb[i]`), not the price our resting quote actually sits at (`cur["b"]`, set at `:231` from an earlier event). Confirmed by direct code read, then dynamically quantified by re-running the identical event stream through both rules side by side on the same live-quote state trajectory:

  | fam | gating | fills under FIX (pn less than cur.b) | fills under OLD rule (pn less than ambient bid) | phantom (OLD hit, FIX reject) | phantom pct of OLD |
  |---|---|---|---|---|---|
  | WH | model | 191 | 24 | 7 | 29.2 pct |
  | WH | baseline | 322 | 45 | 12 | 26.7 pct |
  | ELON | model | 2702 | 379 | 81 | 21.4 pct |
  | ELON | baseline | 5531 | 915 | 197 | 21.5 pct |

  Roughly one in four to five of every fill phase_wh_maker.py reported is phantom - a fill credited at a stale price the print never actually traded through, because the ambient book had rallied since the quote was armed.
- Why it makes the result wrong: this is exactly the mechanism the module docstring of wh_pace_port_backtest.py (`:30-49`) describes, and it is why phase_wh_maker.py own re-run headline shows the Elon control at +124.6 pct ROI - already flagged in market_hunt_2026_07_13.md as "NOT a real maker edge." This audit independently confirms the bug is real and quantifies its magnitude, rather than just accepting the builder prose claim.
- Already partially fixed, but inconsistently: `.claude/agents/backtest-auditor.md:15` already removed phase_wh_maker.py from the trusted-exemplar list on 2026-07-23, with essentially the same explanation given here. However, `.claude/agents/backtest-builder.md:17` is stale - it still lists phase_wh_maker.py as the reference exemplar for "strict through-fill p<b, calib_sigma, cap15", which will cause future builder-generated scripts to copy the buggy ambient-bid pattern.
- Fix: apply the same correction to backtest-builder.md:17 that backtest-auditor.md:15 already has - remove phase_wh_maker.py as the fill-test exemplar (its calib_sigma/cap15 math is fine since that is now centralized in locked_pace.py anyway) and point at wh_pace_port_backtest.py pn<cur[b] pattern instead, with the caveat from the finding above that even that pattern is insufficient alone (queue/market-impact still unmodeled).

### [CLASS D] [MEDIUM] The script own baseline_red_flag safety gate is statistically powerless at n=3/n=5 and creates false reassurance
- Evidence: `baseline_red_flag = (wh_base["net"]>0 and wblo>0) or (el_base["net"]>0 and eblo>0)` (`wh_pace_port_backtest.py:442`) requires the bootstrap-CI lower bound to also clear zero. At n=3 auctions the Elon baseline CI is [-1113.9, +7435.5] - enormous, and will almost never clear that bar even when the true underlying bias is large and persistent, which the hardening sweep above shows it is. The script self-reports baseline_red_flag=False ("clean") in the headline output and RUN_META, which reads as reassuring but is not a meaningful test at this n.
- Why it makes the result wrong: a reader trusting the printed baseline_red_flag=False would conclude the fill model is clean; the dynamic hardening sweep shows the opposite is true.
- Fix: at n below 10 auctions, do not gate solely on bootstrap-LB>0; require a hardened-fill stress-test sweep (as run in this audit) as a mandatory pre-registered check whenever scope is a claims-P&L maker-resting sim, since bootstrap alone lacks power to catch a persistent-but-not-huge structural bias at this sample size.

### [CLASS D] [MEDIUM, confirms builder own caveat - not a new fatal on its own] n=5/n=3, WH jackknife sign-flips, 2 of 5 WH auctions contributed zero
- Evidence: wh_pace_port_auction_summary.csv - WH per-auction net = [-285.5, -211.1, +1110.3, 0.0, 0.0]; dropping the single best auction flips WH from +613.7 to -496.6 (sign_flip: true in RESULT_JSON). Both n=5 (WH) and n=3 (Elon) are below the n<10 "noise until more data" threshold.
- Why it matters: this reinforces (does not contradict) the builder own "INCONCLUSIVE" framing - even ignoring the fill-model defect above, neither number is statistically safe to act on. Noted for completeness; the builder already surfaced this honestly and did not oversell it (wh_beats_control=False).
- Fix: none needed beyond what the builder already did (report CI + jackknife); flagged only so the reader has the full picture alongside the fatal finding above.

---

## Dynamic confirmation of the exclusion (Elon backfill/Gamma mismatch) - independently verified, NOT outcome-selective

Called the live Gamma API directly (GET /events?slug=...) for both excluded auctions, filtering strictly on the "Yes" outcome leg per token (not naive price>=0.999 across both legs, which - as a sanity check on the auditor own methodology - falsely flags the losing buckets No tokens too):

| slug | Gamma official winner (verified live) | script winner_bf (backfill) | reason for exclusion |
|---|---|---|---|
| elon-musk-of-tweets-june-19-june-26 | 240-259 | 200-219 | backfill_gamma_mismatch |
| elon-musk-of-tweets-june-23-june-30 | 240-259 | 260-279 | backfill_gamma_mismatch |

Both match the script own printed exclusion reasons exactly. The exclusion check (precompute_slug, wh_pace_port_backtest.py:234-238) runs before any trade simulation or P&L is computed for that auction - it compares two count-derived labels (own-backfill obs vs Gamma resolution), never a strategy outcome. This is structurally a data-quality gate, not a result-based filter, and is confirmed correct and not outcome-selective. The gamma_winning_tokens() per-token matching logic (`:152-178`) is also confirmed correct (matches by token id via zip(toks, prices) cross-referenced against the script own YES-token discovery table, not by array position or question text) via this same live re-check.

---

## What was checked and PASSED (coverage, not a certification)

- Headline reproduction (gating step): exact, from the persisted ledger CSV (see above).
- RUN_META present and compliant: model_version="ensemble-cap1.5+calibsigma.2026-07-11" matches api/modules/shared/locked_pace.py MODEL_VERSION exactly - no locked-model drift. scope, fills (correctly declares maker_fee=0, taker_fee=N/A, rebate=0), trial_count=1, window_basis all correctly declared.
- Locked model imported, not re-derived: `from api.modules.shared.locked_pace import cap15_projection, calib_sigma, bracket_fair, MODEL_VERSION` (`:99`).
- THE WALL: obs(s,t) only ever called with t less-than-or-equal the decision/print time; walk-forward priors (build_priors) use only windows that ENDED before the auction started. No future_data / same_period_aggregate / global_fit / centered_window / leaked_label pattern found in this script.
- Event-driven: iterates real SELL prints in time order; no resample / rolling / fixed freq= bar aggregation.
- Maker-only: qb = bid+TICK gated qb < ask before ever quoting - never crosses the spread; taker fee correctly N/A, maker fee=0, rebate defaulted to 0 (conservative, per project fee truth).
- Token/price coverage (Pass A, the "-$824 bug"): every winning bucket in all 8 used auctions has substantial real event coverage (34 to 2286 events per winning bucket) - no silent skip of a winning token.
- Tick validity: the approximately 66 pct off-1c-grid book behavior is real and independently reproduced (WH 35.9 pct off-grid, Elon 76.7 pct off-grid, weighted 66.0 pct combined - matches the project own documented characteristic exactly), and is consistent with Polymarket documented neg-risk dynamic 0.001 tick (api/services/clob.py:23) for these multi-outcome bracket markets. Not a fabricated/invalid-tick artifact.
- No unflagged param drift: TICK, GATE_S, BANK, KMULT, MAXBET, and the headline margin=0.03/clip=250 are identical to phase_wh_maker.py own prior choices - not newly cherry-picked.
- No multiple-testing inflation in the headline itself: single pre-registered config (trial_count=1); the 8-cell diagnostic sensitivity grid is explicitly printed and labeled "NOT the headline claim."
- Statistics mechanics: per-auction (not per-fill/tick) block bootstrap + single-outlier jackknife correctly implemented and correctly reported alongside the headline, not hidden.

## What could NOT be fully checked

- Did not re-verify the L2 book-reconstruction/price_change-collapsing DuckDB query logic beyond confirming it is unchanged from the already-audited phase_wh_maker.py pattern.
- Did not independently re-verify the WH backfill tweet counts against a live X-API repull (WH showed 0/5 backfill-vs-Gamma mismatches and was internally consistent, so accepted at face value; only the two flagged Elon auctions were independently re-verified against live Gamma).
- Did not run a Brier/reliability calibration check on the underlying CAP1.5 projection for this specific WH/Elon-multi-bucket dataset - out of scope for this maker-resting P&L audit; would be a separate forecast-accuracy pass.
- The COMBINED-HARD hardening magnitudes (2-tick margin / 25 pct queue capture / 30s min-rest) are a reasonable stress test, not a precisely calibrated re-estimate of true achievable fills - treat the sweep as strongly directional evidence of a persistent bias, not a corrected P&L number.

---

## Bottom line for the caller

The fix in wh_pace_port_backtest.py (pn<cur[b] instead of pn<ambient bid) is real, correct, and a genuine improvement over phase_wh_maker.py - independently confirmed to remove roughly a quarter of phase_wh_maker.py fills as phantom. But it is not sufficient: a second, deeper fill-model defect (no queue-position or market-impact modeling) remains, and it is why the "documented-efficient" Elon zero-edge control still shows large, persistent profit that does not collapse under hardened, more realistic fill assumptions - the exact "profitable baseline equals fill-bug red flag" pattern BACKTEST_RULES warns about. Treat both the WH (+613.7) and Elon (+5830.2) numbers as reproduced-but-invalid. Do not lock a model or size real capital off either number. Fix the queue/market-impact assumption in the fill mechanic (and cross-check against real paper-trading fill rates) before re-running this family of scripts. Separately: backtest-builder.md:17 still cites phase_wh_maker.py as a trusted exemplar and needs the same correction backtest-auditor.md:15 already received, or future builder-generated scripts will re-introduce the ambient-bid bug.
