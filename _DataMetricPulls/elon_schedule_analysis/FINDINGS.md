# Elon Posting-Schedule Analysis (Q1-Q4)

Data: 22,005 captured posts, 2024-05-24 -> 2026-06-12, canonical/posts/elonmusk.
3 stitched sources, different fidelity:
- osint_scrape_2025-12-10 (12,180; May24-Dec25): originals only, MISSED reposts + replies
- xtracker_elon_posts (7,809; Oct25-May26): originals + reposts, MISSED replies
- supabase_elon_tweets (2,016; May-Jun26): full fidelity (X-API)

Method note: timestamps are real on every row, so hour-of-day SHAPE is robust to the
fidelity gaps (ALL-vs-originals hour shape agree at r=0.973). Burst hazard (Q2) run on the
richest continuous window (Nov 2025+). Retweet partners (Q4) only exist Nov 2025+ (reposts
not captured before). Counts are NOT comparable across sources; shapes/ratios are.

---

## Q1 - Daily clock + timezone   [confidence: HIGH on clock, MEDIUM on tz label]
- Silent window: 09:00-14:00 UTC holds just 14.3% of posts. Deepest at 10-11 UTC.
- In ET that quiet block = 5-10am; deepest 6-7am ET. In PT = 2-7am, deepest 3-4am.
- Twin daily peaks: 05-06 UTC (1-2am ET / 10-11pm PT) and 17 UTC (1pm ET / 10am PT).
- Best timezone fit = PACIFIC / night-owl. Deepest-sleep trough at ~3-4am PT is the
  physiological tell (humans bottom out ~4am local). He runs roughly US-West hours.
- Weekday vs weekend: nearly flat (Sat/Sun only ~1.5pp lower). No real weekend slowdown.
- Monthly trough WANDERS (std ~4.6h) - consistent with heavy travel across zones. The
  pooled clock is solid; a fixed per-month timezone is NOT claimable.

## Q2 - Burst continuation formula   [confidence: HIGH on shape]
Closed-form (fit r-good vs empirical):
    P(done >= 2h | silent s min) = 1 / (1 + exp(-(-2.649 + 0.761 * ln(s))))
Key points (empirical):
- At any post: 60% chance of another within 5 min, 83% within 30 min. Only ~8% "done".
- silent 6 min -> ~21% done (your 30% guess was close, slightly high).
- silent 15 min -> 32% done. silent 32 min -> 50% (coin flip). silent 90 min -> 80%.
- Sessions (break = gap > 120 min): median 10 posts, median 96 min long; 50% of sessions
  are >= 10 posts. Bursty/self-exciting - matches the Hawkes model already in code.
- Caveat: missing replies inflate some gaps, so true P(done) is slightly LOWER than shown
  (he continues a bit more than captured). The curve is a conservative upper bound.

## Q3 - Wake/sleep: does start predict end?   [confidence: HIGH]
Tested on 715 active days (>=4 posts).
- corr(start, end) = -0.04  -> his STOP time does NOT move with his start.
- corr(start, duration) = -0.69 -> later start just means a shorter day.
- Last post clusters at ~3:40am ET (12:40am PT) REGARDLESS of when he started.
- First post varies (~8am-12pm ET). Median active span 17h.
- ANSWER TO YOUR HYPOTHESIS: the opposite of "shift the whole window." His BEDTIME is the
  anchor, not his awake-duration. Start at 8am or start at noon - he still winds down ~3:40am.
  The predictable variable is the END, not the length.

## Q4 - Top retweet partners   [confidence: HIGH within Nov25-Jun26 window]
5,523 reposts parsed (100% via "RT @handle"). Top 10:
  1 @XFreeze 340 (6.2%)   2 @cb_doge 310 (5.6%)   3 @teslaownersSV 214 (3.9%)
  4 @MarioNawfal 166 (3.0%)   5 @SpaceX 129 (2.3%)   6 @SawyerMerritt 107 (1.9%)
  7 @dvorahfr 100 (1.8%)   8 @Starlink 82 (1.5%)   9 @Rothmus 71 (1.3%)   10 @tetsuoai 67
Three buckets: own companies (SpaceX, Starlink, Tesla, grok), Tesla/Musk amplifier accounts
(XFreeze, cb_doge, teslaownersSV, MarioNawfal, SawyerMerritt), and politics/culture
(KatieMiller, BasedMikeLee, libsoftiktok, GadSaad). @elonmusk RT @elonmusk (49) = boosting
his own old tweets. Window caveat: pre-Nov-2025 reposts not captured; this is current-era.

---

## Do the live pacing formulas already use any of this?
- Q1 hourly clock: PARTIALLY. pacing.dow_hourly_bayesian_pace + enhanced_pacing DOW/hourly +
  projection "dow" ensemble member weight posts by hour-of-day x DOW for COUNT projection.
  But nothing models the sleep window, the fixed bedtime, or timezone - it's a count weight,
  not an "is he awake / will he stop" detector.
- Q2 bursts: PARTIALLY. hawkes.py (self-excitation, decay) is an ensemble member at 8-15%
  weight; pace_acceleration tracks momentum. But the calibrated gap-survival "P(done after N
  min)" curve does NOT exist - only an intensity-decay proxy.
- Q3 start->end / fixed bedtime: NO. Not modeled anywhere. New edge.
- Q4 retweet partners: NO. Reposts count toward auction totals (per the locked Elon count
  rule) but partner identity is never used.

Artifacts: REPORT.txt, q2_continuation_hazard.csv, q3_daily_windows.csv, q4_retweet_partners.csv, analyze.py
