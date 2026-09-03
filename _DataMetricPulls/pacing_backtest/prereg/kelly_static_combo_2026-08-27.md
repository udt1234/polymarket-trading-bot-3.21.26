# PRE-REGISTRATION: Recency-Selected Static Bracket Combo + Kelly Sizing
**Written 2026-08-27 BEFORE any model was fit or any sealed data was opened.**
Authored by the orchestrator. Built by `@backtest-builder`. Audited by `@backtest-auditor`.
This file is the receipt. The auditor MUST diff what was reported against what is declared here.

## Sir's question
"The cadence doesn't change for the majority of the tweet markets. Elon will always land under 64 in the 2-day markets with outliers. White House will always land between 180-200+ majority with outliers. If we always purchase the same brackets using Kelly criterion for risk management, will we come out on top?"

Scope class: **(a) claims P&L / edge.** Pass B's cost/fill/fee battery applies IN FULL alongside A, C and D.

## What is ALREADY KNOWN and must NOT be re-discovered as if new
`bracket_combo_ev_2026-07-29.py` (audited **PASS**, log `audits/bracket_combo_ev_2026-07-31.md`) tested STATIC ALL-HISTORY combos and found:
- Cost tracks hit rate almost perfectly: OLS slope **0.92-1.00**, intercept ~0, R2 up to 0.97, across 637 Elon and 1023 Trump combos.
- A combo winning X% costs about X cents. Both of Sir's named combos had CI including zero on every span.
- Selecting the best combo on the full sample produced a Trump bracket that went **0-for-13** on a disjoint holdout.

This study must BEAT that result, not repeat it. If it reproduces "the market prices combos correctly", say so plainly.

## What is GENUINELY NEW (the actual hypothesis)
**DATA FACT computed 2026-08-27:** Elon's modal winning bracket has SHIFTED with his activity drop (mean daily posts 44.2 train vs 30.7 sealed).

| Elon 2-day sample | `<40` or `40-64` wins | adding `65-89` |
|---|---|---|
| ALL 68 auctions | 23 = **33.8%** | -- |
| **LAST 20** | 13 = **65.0%** | **19 = 95.0%** |
| LAST 10 | 5 = 50.0% | 9 = 90.0% |

Sir's observation is CORRECT on the recent regime. The 33.8% all-history figure previously reported was masking the shift.

**THE HYPOTHESIS TO TEST:** does the market re-price the bracket ladder SLOWER than the underlying cadence regime shifts? If yes, a recency-selected combo is systematically cheap for a window after each shift. If no, cost tracks the new hit rate immediately and there is no edge. **This is the only mechanism by which Sir's idea can work.** State it, test it, report it either way.

## Method (walk-forward, no hindsight anywhere)
At EACH auction, using ONLY auctions that resolved strictly before it:
1. Look back over a trailing window of W auctions (sweep W in {10, 20, 30, all}).
2. Compute each candidate combo's historical hit rate over that window.
3. Read each leg's actual market price at the decision checkpoint.
4. Compute EV = hit_rate minus total_cost. Select the best-EV combo. Freeze it.
5. Size it by Kelly. Buy at the real price. Record the realised outcome.
6. Compound the bankroll.

**No combo may be selected using its own auction's outcome or any later auction.** THE WALL applies per-auction, not just per-span.

## Kelly, stated honestly up front
**Kelly is a sizing rule, not an edge generator.** For a binary bet at price p paying $1 with true win probability q, the Kelly fraction is `f* = (q - p) / (1 - p)`. **If q <= p then f* <= 0, meaning DO NOT BET.** If the prior efficiency result holds (q approximately equals p), Kelly correctly sizes to approximately zero and the strategy trades nothing. That outcome is legitimate and expected.
- Report **full Kelly, half Kelly and quarter Kelly**.
- Report the **distribution of f\*** across auctions. If f* is at or below zero most of the time, that IS the headline.
- Apply Sir's standing bankroll caps from memory `darwins_rules`: sweeps <= 20% of bankroll per market, normal buys <= 50%.
- Compare against **flat sizing** so Kelly's contribution is isolated from the combo's.

## Outliers are IN SCOPE, not deferred
Sir said "we'll figure out the outliers later." They cannot be deferred: a 95%-hit combo loses **100% of stake** on the 5%. That tail IS the risk. Mandatory:
- Max drawdown, longest losing streak, and the full terminal-bankroll distribution, not just the mean.
- **Probability of ruin** at each Kelly fraction.
- What a single outlier costs relative to the accumulated wins between outliers.
- A strategy whose median outcome is positive and whose mean is negative must be reported as such.

## Targets
1. **Elon 2-day** (68 high-conf auctions, 10-rung ladder consistent across 60). Primary.
2. **Trump 7-day** (52 auctions, 11 brackets, 0% price-coverage gap). Independent control.
3. **White House** -- NEW, never tested. Sir claims 180-200+ modal. There is NO WH auction table in `canonical/auctions/`; posts exist at `pacing_backtest/wh_backfill_2026-06_to_07.parquet` (approx 2 months) and recorder L2 at `recordings_pulled/whitehouse-daily-tweets.parquet`. **Build the winner/auction table first, or report the blocker.** If WH history is too thin for a walk-forward test, say so and report the descriptive bracket distribution only. Do NOT force a number out of a 2-month sample.

## THE WALL
| Handle | Train | SEALED |
|---|---|---|
| Elon | through **2026-03-31** | **2026-04-01** onward |
| Trump | through **2025-12-31** | **2026-01-01** onward |
| White House | first 60% of available auctions by date | remaining 40% |

Every swept parameter (window W, Kelly fraction, combo size cap) is selected on TRAIN only and evaluated ONCE on SEALED.

## Costs and fills (Pass B binds)
- Maker-only. A resting post-only bid fills ONLY when a real print trades THROUGH our price. No mid fills, no top-of-book full-clip.
- Makers pay ZERO fee. Any spread-crossing leg is a TAKER and MUST pay `C x rate x p x (1-p)`. A taker number at zero fee is a lie.
- Respect the dynamic tick; an off-tick price is a fictional fill.
- **The prior study's cost-proxy limitation carries forward and must be disclosed:** canonical `prices.close` is a last-trade proxy, not a fill. Measured against real L2 on 179 points: mean bias 0.22c but **13.4% of pairs go the OPPOSITE direction**, sd ~1.1c. Where real L2 exists (2026-04-13+), use it and say so. Where it does not, label every P&L number proxy-based and report the noise floor beside it.
- **A zero-edge control is mandatory:** run the identical schedule with the combo chosen at RANDOM. If the random control is profitable, the fill or cost model is broken. STOP and fix before reporting anything.

## Baselines
- **B1** Do nothing (bankroll flat). The bar any strategy must clear.
- **B2** Buy the single all-history modal bracket every auction, flat sized. The naive version of Sir's idea.
- **B3** The market price itself: is EV per auction distinguishable from zero?
- **B4** Flat sizing on the same recency-selected combo, to isolate Kelly's contribution.

## Scoring
- Terminal bankroll, CAGR, max drawdown, Sharpe, probability of ruin.
- **Block bootstrap BY AUCTION**, and a single-outlier jackknife on every headline.
- **Effective n = resolved auctions**, never legs, ticks or checkpoints.
- `SUCCESS_N_FLOOR = 10`: any success claim below 10 sealed auctions emits an explicit disqualifying sentinel, never a number.
- Declare the **exact realized trial count**; a window x Kelly-fraction x combo-size sweep is many trials and every one counts.

## Success criteria (fixed now, cannot move)
- **PRIMARY:** sealed-span terminal bankroll beats B1 (do nothing) with a block-bootstrap CI excluding zero, AFTER real maker fills and fees.
- **SECONDARY:** beats B2 (naive modal bracket) and B4 (flat sizing), showing recency-selection and Kelly each earn their place.
- **TERTIARY:** the regime-lag hypothesis is confirmed, i.e. cost measurably lags hit rate after a shift.
- **Failing all three is the expected outcome given the prior efficiency result, and must be the headline if that is what the data says.** Do NOT tune toward a positive.

## Required outputs
1. `===RUN_META===` via `run_meta.py::emit_run_meta` with the EXACT realized trial count.
2. A per-auction CSV: handle, auction_slug, decision checkpoint, selected combo, each leg's price, total cost, Kelly f*, stake, outcome, bankroll after. Every headline must be recomputable from this file alone.
3. A summary markdown leading with the plain answer to "will we come out on top", then the drawdown and ruin numbers, then the tables.

## File scope
Script `_DataMetricPulls/pacing_backtest/kelly_static_combo_2026-08-27.py`, outputs `_DataMetricPulls/pacing_backtest/kelly_out/`. Do NOT modify `pattern_discovery_*`, `regime_*`, `extract_rules_*`, `combo_out/`, `rules_out/`, or any other prereg.

## Handoff
`@backtest-builder` builds against this file. `@backtest-auditor` audits and diffs this pre-registration against what was reported. The builder does not certify its own result.
