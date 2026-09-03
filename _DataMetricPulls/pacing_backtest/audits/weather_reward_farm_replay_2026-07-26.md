# Audit: weather_reward_farm_replay.py / weather_reward_farm_report.py
Date: 2026-07-26
Auditor: backtest-auditor (adversarial pass)
Scope class: (c) maker-resting reward-farming sim, claims $/day P&L -> full fill/efficiency battery applies.

## VERDICT: FAIL (on the precise headline number and its stated CI) / NO-GO conclusion at scale independently CONFIRMED

The broad structural claim (reward-farming weather markets is a bad idea, especially at any
meaningful size or ungated) is well supported and survives every adversarial check run here.
The specific quoted headline figure -- sched120+jump2, gate 5c, s=3.0c, size=100 ->
nettouch = -$3.64/market-day, bootstrap CI [-16.92,-3.71], P<=0=100% -- is exactly reproduced
from the code and its own inputs, but rests on an unverifiable reward-rate assumption that,
within the range the report's own comparison sample supports, flips the sign. The stated 95% CI
does not include this parameter uncertainty, so 100% confidence overstates what is actually
known about this one row.

## Reproduced headline number: YES
Ran python weather_reward_farm_report.py --span-days 3.5956 against
audit_out_weather_v2/weather_reward_farm_replay.csv and got, verbatim:
- sched120+jump2 / gate 5c / s=3.0c / size=100: reward_pmd 3.22, mktouch_pmd -6.86,
  nettouch_pmd -3.64 -- matches claim exactly.
- Bootstrap (resample unit = market, n=198): touch mean -9.88, CI [-16.92, -3.71],
  P<=0 100.0% -- matches claim exactly.
- Ungated gross-reward corner (base/-1/s1.0/size2500): reward_pmd 86.57, mean_share 0.90
  -- matches claim exactly.
- net60 vs nettouch flip (jump2/-1/s2.0/size100): net60 +32.11 CI[22.34,42.22] P<=0 0.0%
  -> nettouch -51.39 -- matches claim exactly.
- All 225 swept configs confirmed negative on nettouch_pmd (max = -3.639; verified
  directly against weather_reward_farm_summary.csv, 225 rows = 5 defenses x 5 s x 3 sizes x 3
  gates, zero positive).
- v1's lone positive netres corner (size=2500) traced to sched120+jump2/gate5/s4.0/size2500,
  total $654.25, and the single market highest-temperature-in-chongqing-on-july-25-2026-40c
  contributes $5,227.69 = 799.0% of that total -- matches the claimed dismissal exactly.

## Findings, most severe first

**[CLASS B] [FATAL for the headline number] Reward-rate floor is not a verified lower bound, and
the headline sign flips within the report's own observed comparison range.**
- Evidence: weather_reward_farm_replay.py:76-78,106-119 -- RATE_FLOOR = 100.0; Gamma zeroes
  rewardsDailyRate on close, so 324 of 348 usable markets (all CLOSED markets) get a flat
  assumed $100/day, contributing 94.1% of the market-days in the headline config
  (47.30 of 50.29 market-days; recomputed directly from the replay CSV).
- The report's own comparison sample (28 still-open "July 26" markets with a live observed rate)
  spans $40-$233/day. Ten of 28 (36%) are already BELOW the $100 floor, which directly
  contradicts calling it conservative -- it is a point guess with roughly a 6x spread either way,
  not a lower bound.
- Recomputed the headline's sensitivity to this single assumption, holding everything else fixed:
  - at RATE_FLOOR=100 (as-reported): nettouch_pmd = -3.64
  - at RATE_FLOOR=200 (2x, still inside the observed 40-233 range): nettouch_pmd = -0.59
    (statistically indistinguishable from zero given the reported CI width of about 13)
  - at RATE_FLOOR=233 (the actual MAXIMUM observed rate in the report's own sample, not an
    invented extreme): nettouch_pmd = +0.41 -- sign flips positive.
- Why it matters: reward and bleed in the headline row are only 2.1x apart (bleed/reward ratio),
  which sits at the fragile low end of the author's own self-cited "2-10x" safety margin, not
  comfortably inside it. The bootstrap CI reported (weather_reward_farm_report.py:56-62)
  resamples over markets holding rate fixed at the point estimate -- it captures sampling noise,
  not this much larger structural/parameter uncertainty, so "P<=0=100%" materially overstates
  confidence for this one row. This is precisely the false-negative risk the task asked to hunt
  for: a real edge could be sitting inside the noise created by an unmeasured rate.
- Scope of the damage: this does NOT touch the ungated / larger-size corners (e.g. base/-1/s1-2c/
  size 500-2500, nettouch_pmd in the -200 to -10,700 range) -- those stay overwhelmingly negative
  even at 2.33x the assumed rate, so the general "don't do this at scale" conclusion is safe.
  It specifically undermines trusting "-$3.64/market-day" (and its CI) as a precise, confident
  number for the narrowly-defense-gated headline config.
- Fix: either pull actual historical reward-rate telemetry for the closed markets (Gamma
  snapshots taken WHILE the market was still open, not after close) or report the headline as a
  range under a rate sensitivity table instead of a single point CI, and stop quoting "100%
  confidence" on a row whose reward/bleed ratio is this thin.

**[CLASS B] [HIGH] Two different definitions of "spread" are used for the same nominal
gate_c across the reward-accrual leg and the pickoff-ledger leg.**
- Evidence: weather_reward_farm_replay.py:250 -- reward accrual's mkt_spread_c = (aba - abb) *
  100.0 where abb,aba are computed only from levels meeting minsize (line 240-243,
  okb, oka = szb >= minsize, sza >= minsize). Versus weather_reward_farm_replay.py:313 --
  pickoff ledger's mkt_spread_c = (q_ask[li] - q_bid[li]) * 100.0, taken straight from the
  recorded best_bid/best_ask fields, which are the RAW, unfiltered top-of-book.
- Confirmed the raw feed is genuinely unfiltered, not already min-size-clipped: sampled the first
  book snapshot for highest-temperature-in-atlanta-on-july-23-2026-90-91f -- top bid level is
  price 0.43, size 26.82 shares (well under minsize=100), and the recorded best_bid at
  that instant is exactly 0.43. So the two ledgers' "gate 5c" means two different things: the
  reward leg only opens the gate when the qualifying book is tight; the bleed leg opens it
  whenever the raw (dust-inclusive) book looks tight, which is easier to satisfy. That means, for
  a given labeled gate_c, the bleed leg is exposed to more/different minutes than the reward leg
  earns credit for.
- Direction of the bias: raw top-of-book is generally tighter than the qualifying-size top (dust
  orders sit inside real size), so the bleed leg's gate is looser than the reward leg's -- this
  again pushes the reported net toward MORE negative than an internally-consistent single
  definition would, i.e. conservative, not a false-positive risk, but it means the exact -3.64
  is not an apples-to-apples reward-vs-bleed subtraction.
- Fix: gate both legs on the same spread definition (recommend the qualifying/min-size one, since
  that is what actually gates reward eligibility and is the economically meaningful one for
  "is this a real two-sided market to lean on").

**[CLASS B] [MEDIUM] Pool-share estimate is directionally conservative but unquantified
(self-declared limitation #2, confirmed and signed).**
- The replay computes competing Q on the AGGREGATE observed book (combine_q on summed
  bid/ask level scores, weather_reward_farm_replay.py:266-279), but Polymarket's real mechanic
  applies the min/combine rule PER MAKER, then sums those per-maker mins.
- Worked proof of direction: two makers, A bid-only, B ask-only, both scoring 10. Aggregate
  Qone=10, Qtwo=10 -> combine=10. True per-maker: min(10,0)=0 for A, min(0,10)=0 for B (or 1/3
  credit each if in-band, giving about 6.7 not 10). In every case aggregate >= true sum. So this
  approximation systematically OVERSTATES the competing pool's Q whenever the book is fragmented
  across one-sided makers, which UNDERSTATES our modeled share and reward -- again a conservative
  (pessimism-inducing) bias, not a false-positive risk. Magnitude cannot be bounded from public L2
  data (maker identity is not observable), so treat the reward-side numbers as a plausible lower
  bound, not a point estimate. Combined with the rate-floor finding above, the headline reward of
  $3.22/market-day could plausibly be understated on two independent axes at once.

**[CLASS A] [MEDIUM] Book-reconstruction fidelity is highly non-uniform; the claimed 98.0%
aggregate figure hides a bad tail on a subset of chaotic markets.**
- Independently re-derived top-of-book from book snapshot + price_change deltas (unfiltered,
  no min-size) and diffed against the recorded best_bid/best_ask on 15 randomly sampled slugs,
  45,000 ticks total: exact match 93.2%, within-1-tick match 98.4% -- broadly consistent with
  the claimed 98.0% and independently confirms the reconstruction is sound on typical markets.
- But one sampled slug (highest-temperature-in-seoul-on-july-23-2026-30corhigher, a legitimate
  "N-or-higher" cumulative bracket, not a partitioning artifact -- confirmed against Gamma meta)
  reconstructed at only 2.0% exact agreement, with 272,886 price_change rows in 2.5 hours
  (median inter-event gap 8ms) -- a genuinely hyperactive/contested book where dense same-
  millisecond bursts make delta ordering ambiguous. Checked: this slug never appears in any
  gate_c in (5,10) row (its spread never qualifies), so it does NOT contaminate the headline
  config, only the ungated sweep's descriptive numbers. Recommend excluding or flagging
  high-churn markets (e.g. >X price_change events/minute) from the "gross reward thesis" corner's
  supporting stats, since fidelity there is unverified.

**[CLASS A] [LOW] Mild but not statistically clear outcome-correlated survivorship.**
- 267 of 375 closed markets pass the "usable" filters (inband_min>=30, >=50 quote-ticks); YES
  resolution rate is 43.4% among used closed markets vs 36.1% among dropped ones (z about 1.3,
  not significant at n=267/108). Not fatal, but the drop reason (illiquid/never-tight book) is
  not obviously outcome-independent; flagging as advisory only, not confirmed.

**[CLASS C] [WARN] No RUN_META emitted.**
- Neither weather_reward_farm_replay.py nor weather_reward_farm_report.py emits the
  ===RUN_META=== stdout block or a .run_meta.json sidecar (emit_run_meta from
  _DataMetricPulls/pacing_backtest/run_meta.py is not imported/called anywhere in either
  script). Per policy this is itself a class-C finding: un-versioned, un-auditable provenance.
  No model_version/git_sha/scope/fills declaration to diff against. Recommend adding it
  before this number is cited again.

## What was checked and passed
- Headline reproduction: exact, from the checked-in CSV, no live calls needed.
- THE WALL / causality: end_ms (used by schedW) is a pure function of the slug's own
  date, always exactly 12:00:00 UTC the day after the slug's date, across all 479 metadata rows
  with zero exceptions -- confirmed this is a mechanical, ex-ante-known rule, not a value that
  could be revised post-hoc from the resolution outcome. jumpJ's trigger/cooloff series
  (jump_blocked_series) only looks backward (np.searchsorted(q_ts, q_ts - JUMP_WIN_S*1000))
  and only carries forward via np.maximum.accumulate -- causal, no leakage.
- Trade-side semantics: independently checked 987 last_trade_price rows across 20 random
  slugs against the contemporaneous best_bid/best_ask -- BUY prints median distance to ask = 0.00,
  SELL prints median distance to bid = 0.00. Confirmed as documented.
- No bar resampling: reward accrual grid is Polymarket's own 1-minute reward-sampling cadence
  applied to the tick-reconstructed book (not a resample of price bars); the pickoff ledger is
  fully event-driven off real last_trade_price prints. Confirmed by code read.
- Statistical honesty: bootstrap resample unit is market (groupby("slug")), matching Pass D
  requirement. All 225 swept configs confirmed negative on nettouch -- not cherry-picked.
  Single-outlier jackknife on the headline config in BOTH directions: dropping the single worst
  market moves pooled nettouch_pmd from -3.64 to -2.49 (still negative); dropping the single best
  market moves it to -4.02 (more negative). The negative sign for the headline is not an artifact
  of one market, in either direction -- a genuine false-negative-by-outlier is ruled out here
  (separate from the rate-assumption issue above, which is a parameter risk, not an outlier risk).
  v1's one positive corner was legitimately dismissed (799% single-market concentration,
  independently reconfirmed above).
- Capital honesty: weather_reward_farm_report.py:41-43 computes capital as
  sum(avg_capital*quote_minutes)/wall_clock_minutes over the FULL span, not per-market -- correctly
  reflects idle time and concurrency, not a per-market average.
- Fill model direction: confirmed qualitatively that filled-shares/lifetime-volume inflates
  sharply at size=2500 vs size=100 across multiple gate/s configs tried (ratios from about
  0.07-0.13x at size=100 to about 1.3-2.9x at size=2500), consistent with the claim's direction and
  justifying the size=100 choice for the headline, though the exact quoted 1.33x/6.16x and
  0.06x/0.27x figures were not reproduced under the configs tried -- likely a different
  aggregation slice than what was probed; low-severity reproduction gap on a secondary caveat
  metric, not the headline.
- Data source: reads only the recorder's own partitioned parquet (by_slug/slug=*), the canonical
  L2 recording, not a stray/derived source. Consistent with project rules.

## What could NOT be checked
- Could not independently verify the exact numeric value "98.0%" / "69,110 ticks" the author cites
  (no saved verification script exists for it) -- built an independent equivalent check instead
  (45k ticks / 15 slugs) that broadly agrees, with the caveat above about chaotic markets.
- Could not verify Polymarket's official reward-formula constant c=3 and the exact [0.10,0.90]
  combine-rule band against live docs (no internet access in this environment) -- verified only
  that the CODE matches the FORMULA AS STATED in the docstring/task description; did not re-derive
  it from docs.polymarket.com directly.
- Could not obtain true historical reward rates for the 324 closed markets (Gamma zeroes them on
  close; no alternate source found) -- this is the open question behind the FATAL finding above,
  and is likely unresolvable without a rate-history recorder running going forward.
- Did not re-run the full 348-slug replay end-to-end from scratch (would reproduce identically
  since the code is deterministic and the aggregate outputs were reproduced from the checked-in
  CSV plus spot checks against raw parquet); relied on the checked-in
  weather_reward_farm_replay.csv for bulk verification rather than a fresh full run.
