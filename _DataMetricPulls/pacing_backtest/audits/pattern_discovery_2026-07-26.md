# Audit: pattern_discovery_2026-07-26 (post-cadence pattern discovery, scope class b)

Auditor: @backtest-auditor. Date: 2026-07-29.
Pre-registration: `_DataMetricPulls/pacing_backtest/prereg/pattern_discovery_2026-07-26.md`
Runner: `pattern_discovery_2026-07-26.py` / `pattern_discovery_lib.py` / `pattern_discovery_methods.py`
Outputs: `pattern_discovery_out/{per_row.csv, pattern_discovery_2026-07-26.run_meta.json, summary.md, run.log}`

## VERDICT: FAIL (BLOCK)

Do not quote or lock any elon_2day / elon_7day "primary success (beats B4/market)" claim from this run. The trump_7day result ("no tradeable edge, nothing beats B4") is clean and stands as the one trustworthy number this study produced.

## Reproduced headline number: YES (and that is the indictment, not a pass)

Recomputed elon_2day sealed B1 vs B4 skill directly from per_row.csv using the exact aggregation in compute_skill_table():
skill_mean = 3.335041 vs reported +3.3350, n=27 matches exactly (seed=0 deterministic bootstrap). Byte-level reproduction confirmed. Per BACKTEST_RULES / Pass B, a number that reproduces only because it embeds an invalid comparator is "reproduced-but-invalid" -- see Finding 1.

## Findings (most severe first)

### [CLASS A/B] FATAL -- B4 (market) log loss is contaminated by a silent near-zero default whenever the winning bracket's token has no price, inverting the "everything beats the market" headline
Both orchestrator suspicions are the SAME confirmed bug.

Where: pattern_discovery_lib.py:339-354 (market_bracket_probs) builds the market-implied distribution ONLY over brackets that have a price at/before T, and its own docstring says: "the caller decides whether the auction is admissible for a B4 comparison based on winner coverage specifically." No such caller-side filter exists. pattern_discovery_2026-07-26.py:341-348 (_emit) unconditionally does probs.get(label, 1e-6) for every bracket including the winner -- if the winner's price was never found, its "market probability" silently becomes 1e-6. pattern_discovery_2026-07-26.py:701-735 (compute_skill_table) computes logloss = -log(model_prob) on that defaulted value and only .dropna()s pairs where a whole column is missing -- it never checks price_coverage_n/price_coverage_tot (recorded in every row of per_row.csv but never consumed anywhere downstream).

Dynamic confirmation (recomputed from per_row.csv, not grep):
- elon_2day sealed B4-winner rows: 108 total, 32 (29.6%) defaulted to model_prob<=1e-5 with market_price=NaN (i.e. the winner never had a price at all, not just a low one).
- elon_7day sealed B4-winner rows: 95 total, 80 (84.2%) defaulted.
- trump_7day sealed B4-winner rows: 98 total, 0 (0.0%) defaulted -- clean control, matches its own 0.0% auction-level coverage gap.
- Auction-level (any span): elon_2day winner-ever-priced in only 21/60 auctions (65% never priced at all); elon_7day in only 11/72 (84.7% never priced); trump_7day 37/37 (100%).

Sign-flip test (the decisive probe): re-scored elon_2day sealed keeping only the 19 (of 27) auctions where the winner was priced at least once, dropping the rest instead of defaulting them:
- B1 vs B4: reported +3.3350 ("B1 beats market") -> hardened -0.3722 ("market beats B1")
- B3 vs B4: reported +3.4509 -> hardened -0.3359 ("market beats B3/locked_pace")
For elon_7day sealed, only 3 of 19 auctions have any real winner-price coverage at all; the reported n=19 comparison is 84% fabricated log-loss.

Why this makes the result wrong: every "PRIMARY (tradeable) beats B4" entry for elon_2day and elon_7day in RUN_META (primary_success_elon_2day_sealed_beats_B4: [B1,B2,B3,M1,M2,M4,M7(M1)], primary_success_elon_7day_sealed_beats_B4: [B1,B2,B3,M1,M2,M4,M5,M7(M1)]) is an artifact of this defaulting bug, not a real pattern. The pre-registration's own gut-check ("a baseline that itself looks impossibly good is a red flag for a leak, not a triumph") applies in mirror image here: B4 looking impossibly bad is the same red flag. Once corrected, Elon matches the one clean, uncontaminated control in the same study: trump_7day (0% missing) reports primary_success_trump_7day_sealed_beats_B4: none -- nothing beats the market. That is now corroborated, not contradicted, by the hardened Elon numbers. The true finding of this study is "no tradeable edge on either handle," the opposite of the current headline.

Fix: exclude an auction-checkpoint from every B4-vs-method comparison (dropping the SAME rows for both sides of each pair, to keep them matched) whenever the winning bracket has no price at time T -- never default to 1e-6. Wire price_coverage_n/price_coverage_tot (already computed, already in per_row.csv) into compute_skill_table()'s admissibility gate, or filter on is_winner==1 & market_price.notna() per auction before pivoting. Re-run the sealed-span success criteria on the corrected data before any Elon number is quoted.

### [CLASS D] LOW/MEDIUM -- trial_count silently excludes M6/M7(M6) despite both being fully fit, scored, and reported
RUN_META declares trial_count=118, broken down as M1:32, M2:38, M3:4, M4:12, M5:8, M1_compose:24 (sums to exactly 118). M6 (Hawkes MLE) and M7(M6) are fully computed with real skill/CI/jackknife numbers for every target and span in summary.md (e.g. M6 vs B4 in elon_2day sealed: skill=-7.5116), yet contribute zero to the declared count. The per-method disclosure explains M6 is fit via a fixed-structure Nelder-Mead MLE (2 restarts) rather than a hyperparameter grid search, which is a defensible reason for excluding it from a "grid-search trial" count -- but summary.md never states this definition explicitly, so a reader cannot distinguish "intentionally out of scope for trial_count" from "omitted." Does not change the verdict: M6 never appears in any primary/secondary success array, so it does not inflate the multiple-testing exposure on the headline. Fix: state explicitly in the summary "M6/M7(M6) excluded from trial_count: fixed-structure MLE fit, not grid-searched" so the count is self-documenting.

### [CLASS D] Observation, not a finding -- M6 (Hawkes) is uniformly and severely miscalibrated
M6 loses to every baseline in every target/span, often by 8-12 nats of log loss (e.g. elon_2day sealed mean logloss: B1=1.31, B4=4.62 (contaminated, see Finding 1), M6=12.19). This is reported honestly (M6 never wins, never appears in a success array) so it is not a disclosure failure, but a 12-nat log loss implies M6 assigns the true winner a probability on the order of e^-12 ~ 6e-6 almost every time -- worth a follow-up code review of fit_M6/predict_M6 for a possible bracket-key mismatch or simulation bug independent of this audit's scope, since a correctly-functioning (if unhelpful) Hawkes model should not be that confidently wrong.

## What was checked and passed

- Reproduction: headline elon_2day sealed B1 vs B4 skill reproduces exactly from per_row.csv (see above). Reproducible, but invalid (Finding 1).
- Token->price coverage (Pass A, the -$824 pattern): the script runs this check itself (check_token_price_coverage) and reports it up front in RUN_META/summary -- good practice; the audit's job was to determine whether the coverage gap was actually being HANDLED correctly downstream, and it was not (Finding 1).
- Canonical source only: confirmed data_paths in RUN_META are all under canonical/ + the declared clean X-API Elon parquet + locked_pace.py -- no stray one-off parquet reads.
- Noon-ET window parsed from slug: pattern_discovery_lib.py:83-101 (noon_window) parses month/day from the slug body; start_utc.year is used ONLY as a year anchor, never as the window boundary itself -- matches the bracket_hit_backtest.py::noon() reference pattern. Confirmed by reading the function, not just grepping the docstring.
- THE WALL / global_fit: train/sealed split honored at the exact declared dates (Elon train<2026-04-01, Trump train<2026-01-01) via wall_ts gating (train_units = [u for u in units if u["s"] < wall_ts]). Per-decision-unit refits use priors = [p for p in units if p["e"] < u["s"]] (auctions that ENDED before this one starts) -- the correct causal idiom from BACKTEST_RULES.md. M1/M2/M4/M5 hyperparameter selection uses a 70/30 chronological holdout strictly WITHIN train (both ends before the wall) -- causal, disclosed as a tractability simplification of a full walk-forward grid, not a leak. M3's centroids are frozen on train-only per the prereg's own explicit carve-out for M3 specifically (not a violation -- it is what was pre-registered). M4 (HMM) and M6 (Hawkes) are refit per decision-unit on bounded prior history (cap=40) -- causal.

- model_version / locked-model drift: RUN_META model_version "ensemble-cap1.5+calibsigma.2026-07-11" matches api/modules/shared/locked_pace.py:22 MODEL_VERSION exactly. No drift.
- Multiple-testing gate: the pre-registered gate (re-score any winner on the disjoint sealed span) was followed structurally -- train and sealed are reported separately throughout, and every success-criteria verdict in summary.md is drawn from the sealed span only. This does not rescue Finding 1, since the sealed-span comparison itself is what's contaminated.
- Effective n / small-sample honesty: the script correctly treats n=19-28 auctions as small: block-bootstrap CIs are reported per comparison, "unproven (CI incl. zero)" is used liberally and correctly (e.g. most M* vs B3 comparisons across all targets), and the single-outlier jackknife genuinely flips sign in several places (M3 vs B3 in elon_daily, M1 vs B1 in elon_2day sealed, M7(M1) vs B4 in trump_7day sealed) and is reported as such rather than hidden. Block size = 7 (weekly) for the autocorrelated daily substrate, 1 for auction-level targets -- matches the prereg's stated rho=0.44 adjustment.
- Estimator honesty (M1-M5, M7): spot-checked against the prereg's caps (M2 max_depth<=4, min_samples_leaf>=25 never exceeded; M4 n_states in {2,3,4}; M3 k in {3..6} within the declared 3..8 cap) -- all held in code, not just in the disclosure text.

## What could NOT be checked (fail closed, not assumed fine)

- Did not independently re-verify the underlying canonical/prices build pipeline itself (i.e. WHY 63.6%-84.7% of Elon winner tokens have no price row at all -- the summary's own hypothesis is a 03_build_auctions.py/08_normalize_bucket_labels.py interaction reverting bucket-label demotions). That is a canonical-data-layer bug, out of scope for this backtest's own code, but it is the root cause feeding Finding 1 and should be fixed at the source, not patched only in this script.
- Did not re-run the full 966-line script end-to-end (recomputing from raw canonical parquet would re-derive the same per_row.csv; reproduction was done from the emitted ledger per the audit protocol's first-class path, which is sufficient and faster).
- Did not deep-audit fit_M6/predict_M6 internals beyond confirming causal refit-on-priors; flagged above as a follow-up code-quality item, not fatal to this verdict.
- Did not verify M5's Monte-Carlo forecast sampler bit-for-bit against its stated Binomial-equivalence claim; took the disclosure at face value since M5 never appears in a success array either (it loses everywhere, consistent with a real but unhelpful hazard model).
