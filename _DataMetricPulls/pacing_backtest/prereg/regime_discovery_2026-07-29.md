# PRE-REGISTRATION: Regime Discovery (trajectory + day-sectioning)
**Written 2026-07-29 BEFORE any model was fit or any sealed data was opened.**
Authored by the orchestrator. Built by `@backtest-builder`. Audited by `@backtest-auditor`.
This file is the receipt. The auditor MUST diff what was reported against what is declared here.

## The two questions (the user's, in their framing)

**Q1, between-auction regime.** "Backtest for understanding regime change. Going through all past auctions for Elon 2-day and seeing if we can predict regime change based on trajectory. For example, seeing a curve line for auction ends that go from high to low to high and creating a formula based off of it."

**Q2, within-day sectioning.** "If we cut the day up into sections, we're able to figure out Elon's regime and/or ending tweet range based on his posting cadence, his posting time, the section of the day. For example, if we cut up the day based on a time frame of his bursts on average, we might see that he generally posts by 11am, 3pm, 9pm, 11pm ET. Furthermore, we're able to decipher that it will be a high regime day if he's posting every 2 hours, or that it will be a low regime where he doesn't post anymore if he bursts 10 in the morning."

Scope class: **(b) pure forecast-accuracy / calibration diagnostic**, plus descriptive rule discovery. No P&L claimed, no fills simulated.

## Standing constraints
- All prior strategy conclusions are HISTORY (unverified) and may NOT be used to skip, narrow, or pre-judge any test.
- Counting rule LOCKED: noon-ET window, market dates, originals + quotes + reposts + self-replies, no pure replies. Elon: `counts_main_feed == True`.
- Auction windows parsed from the market slug, NEVER trade-derived `start_utc`/`end_utc`.
- THE WALL: no feature may read data with timestamp > decision time T.
- Sections, thresholds and regime definitions are DISCOVERED from train data only, then frozen. Never fit on the full span.

## Data
Same canonical sources as `pattern_discovery_2026-07-26.md`. Elon clean span 2025-09-01 to 2026-06-27 (300 noon-ET days). Elon 2-day auctions n=68 high-confidence. Trump 7-day n=52.

## THE WALL (fixed now)
| Handle | Train | SEALED |
|---|---|---|
| Elon | through **2026-03-31** | **2026-04-01** onward |
| Trump | through **2025-12-31** | **2026-01-01** onward |

Identical to the prior study so results are comparable.

## Known baseline facts (DATA FACTS, computed 2026-07-29, not to be re-derived as findings)
- Elon daily counting-posts: median 36, p10 16, p90 69, mean 40.2, sd 21.3.
- Daily counts autocorrelate: lag-1 rho **0.440**, lag-2 0.452, lag-7 0.292. N_eff is about 39% of nominal.
- Trivial null: `count_so_far` alone explains R2 0.764 of the final daily count by hour 18, 0.856 by hour 21.
- The within-day HMM already showed real skill over naive (+0.121, CI [+0.029,+0.206], 87 sealed days). Q2 must BEAT that, not rediscover it.

---

## Q1 METHODS (between-auction trajectory)

| ID | Method | Constraint |
|---|---|---|
| R1 | Discretize each auction's final count into regime levels (tertiles or the bracket ladder), fit a **Markov transition matrix** on the level sequence | fit on train only |
| R2 | **Autocorrelation / spectral** analysis of the auction-level series: is there a cycle, or only the known lag-1 persistence? | report ACF/PACF with CIs |
| R3 | **Changepoint detection** (e.g. binary segmentation or PELT) on the auction-level series. Are there discrete regime shifts, and are they detectable at the time or only in hindsight? | must report detection LAG |
| R4 | **Mean reversion vs momentum test**: regress auction N+1 level on auction N level and on the recent trajectory shape (up-up, up-down, down-up, down-down) | walk-forward |
| R5 | **Trajectory-shape rules**: after a high-low-high pattern, what happens next? Report as a readable rule with cell counts | n>=30 or flagged |

**Q1 honest expectation to test, not assume:** lag-1 rho of 0.44 on DAILY counts may fully explain any apparent auction-level structure. R4 must report whether trajectory shape adds anything OVER simple lag-1 persistence. If it does not, that is the finding.

---

## Q2 METHODS (within-day sectioning)

| ID | Method | Constraint |
|---|---|---|
| S1 | **Discover the sections.** Do NOT impose clock hours. Fit the empirical intensity of posts by ET minute-of-day on TRAIN ONLY, then cut the day at intensity troughs (or via a 1-D clustering / changepoint on the intensity curve). Report the discovered boundaries and compare them to the user's hypothesis of ~11am / 3pm / 9pm / 11pm ET | boundaries frozen from train |
| S2 | **Section-feature model.** Features per section: posts in section, median gap in section, time of first post in section, burst size, cumulative count. Predict (a) the regime class and (b) the final count distribution | features strictly <= T |
| S3 | **Cadence-to-regime rule.** Test the user's specific hypothesis: does an inter-post gap near 2h predict a high-regime day? Sweep the gap threshold on train, freeze it, evaluate on sealed | one frozen threshold |
| S4 | **Burst-exhaustion rule.** Test the user's specific hypothesis: does a large morning burst predict a LOW remainder (exhaustion / mean reversion within the day)? Define "morning burst" from train, freeze, evaluate on sealed | report effect size + CI |
| S5 | **Early-identification test.** For every regime rule found, report the earliest hour at which it fires with what accuracy. A rule that only resolves at 11pm is worthless. Report accuracy-by-hour curves | mandatory for every rule |

**Regime definition, fixed now:** a day's regime class is its final counting-post total binned into terciles computed on TRAIN ONLY (low / mid / high), frozen. Do not redefine after seeing results.

---

## Baselines (every method scored against all of these)
- **B1 Naive:** `count_so_far / elapsed_fraction`.
- **B2 Climatology:** unconditional historical distribution.
- **B3 Incumbent:** `locked_pace.py`.
- **B4 The prior study's HMM (M4).** This is the bar for Q2. Section-based rules must beat the within-day HMM or they add nothing.
- **B5 MARKET:** implied bracket distribution where available (Elon 2-day only, and only on price-admissible auctions).

## Scoring
- Regime classification: accuracy, macro-F1, and a confusion matrix, plus **log loss on the class distribution**. Never accuracy alone.
- Final-count distribution: log loss and Brier over the bracket set, plus a reliability diagram.
- Scored on the **remaining** count, not the final count, wherever a within-day decision time applies.
- Block bootstrap by auction (by week for the daily substrate). Effective n reported as distinct auctions or days.
- Single-outlier jackknife on every headline.
- **`SUCCESS_N_FLOOR = 10`**: any success claim on fewer than 10 units emits an explicit disqualifying sentinel, not a method name. At tiny n a block bootstrap cannot exclude zero unless all values share a sign.

## Trial count
Declared upper bound: **10 methods x up to 5 decision hours x 2 handles, plus threshold sweeps in S3/S4 and section-count selection in S1.** The builder MUST log the exact realized count in RUN_META. Threshold sweeps are trials and must be counted.

## Success criteria (fixed now)
- **PRIMARY:** a Q2 section-based rule beats **B4 (the existing HMM)** on sealed-span log loss with a block-bootstrap CI excluding zero. Anything less means sectioning adds nothing over what is already built.
- **SECONDARY:** a Q1 trajectory feature beats simple lag-1 persistence on sealed-span regime prediction, CI excluding zero.
- **TERTIARY:** any rule beats B1/B2. Table stakes.
- **DESCRIPTIVE (always delivered regardless of the above):** the discovered section boundaries, the transition matrices, the readable rules with train and sealed cell counts and hit rates. Even if nothing beats the baselines, the user wants the map.
- Beating B1/B2 while losing to B4 is reported plainly as "adds nothing over the existing HMM." That is a valid, expected outcome.

## Required outputs
1. `===RUN_META===` via `run_meta.py::emit_run_meta`, with the exact realized trial count.
2. A per-row CSV from which every headline is recomputable by a third party.
3. A summary markdown, leading with the READABLE RULES and the discovered day sections, with the score tables after. The user asked for the map, not the scoreboard.

## File boundaries
Script `_DataMetricPulls/pacing_backtest/regime_discovery_2026-07-29.py`, outputs `_DataMetricPulls/pacing_backtest/regime_out/`. Do NOT modify `pattern_discovery_*`, `rules_out/`, `combo_out/`, `pattern_discovery_out/`, or any other prereg. Concurrent agents are working in this repo.

## Handoff
`@backtest-builder` builds against this file. `@backtest-auditor` audits and checks this pre-registration against what was reported. The builder does not certify its own result.
