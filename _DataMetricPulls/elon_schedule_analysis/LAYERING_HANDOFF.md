# Elon Posting-Schedule Signals: Layering Handoff (for the Sheets session)

Self-contained spec. You do NOT need the originating chat. Everything needed (formulas,
coefficients, lookup tables, data paths, caveats) is in this file.

Goal: layer 9 newly-validated behavioral signals (A-I) about Elon Musk's posting onto the
bot's tweet-count projection, expressed as Google Sheet computations a Sheets session can
build. The bot projects how many tweets Elon posts inside a Polymarket auction window (noon-ET
to noon-ET) and buys a count bracket. These signals improve the intra-window projection and add
a "count is final" confidence gate.

Signals A-D are the daily-clock / burst / bedtime / partner findings. Signals E-I are the
deeper correlation pass (cluster count, heavy-morning + momentum, reply-rate, repost topic
scoring, end-anchored clock). All are validated to >=95% within their stated windows.

---

## 0. Source data (where the numbers come from)

- Canonical posts: `_DataMetricPulls/canonical/posts/elonmusk/{YYYY-MM}.parquet`
- One row per post. Relevant columns:
  - `ts_utc` (UTC, tz-aware), `ts_et` (America/New_York, DST-correct) <- ALWAYS anchor on ts_et
  - `is_reply`, `is_repost`, `is_quote`, `is_community_repost` (bool)
  - `content_text` (for retweet-partner parsing), `source`
- Rerunnable analysis script that produced everything below:
  `_DataMetricPulls/elon_schedule_analysis/analyze.py`
- CSV artifacts you can import straight into tabs:
  - `q2_continuation_hazard.csv` (silence -> probabilities)
  - `q3_daily_windows.csv` (715 active days: start/end/span)
  - `q4_retweet_partners.csv` (partner -> count)

### CRITICAL: how to define a counting window (do NOT use canonical auction start/end)
- The canonical `auctions` table's `start_utc/end_utc` are TRADE-derived (first/last trade), not
  the tweet-counting window. A "2-day" market's trade span is often 4-7 days. Using them to count
  tweets overcounts by ~2x and will not match the resolved bucket.
- Correct counting window = parse the market DATE range from `auction_slug` / `title`
  (e.g. `elon-musk-of-tweets-april-4-april-6` -> Apr 4 12:00 ET to Apr 6 12:00 ET) and count
  `counts_for_auction == True` posts in that NOON-ET window. This is the locked count rule and
  reconstructs the true count (validated: Apr 4-6 -> 66 posts, matches its 65-89 bucket).
- `winning_bucket` IS reliable for `confidence in (high, medium)`; the earlier-looking mismatches
  were caused by the wrong (trade) window, not a bad label.

### Data-quality caveats (READ before modeling, these are hard constraints)
- 3 stitched sources, different fidelity:
  - `osint_scrape_2025-12-10` (May24-Dec25): originals only, NO reposts/replies captured
  - `xtracker_elon_posts` (Oct25-May26): originals + reposts, NO replies
  - `supabase_elon_tweets` (May-Jun26): full fidelity (X-API)
- Therefore: NEVER compare raw post COUNTS across source eras. Only timing SHAPES and ratios
  are valid cross-era (verified: hour-of-day shape ALL-vs-originals agree at r=0.973).
- Reposts only exist from Nov 2025 onward. Retweet-partner analysis (Q4) is current-era only.
- The bot's live auction count rule (locked) counts originals + quotes + reposts + self-replies
  inside a noon-ET window. Reposts DO count toward the number traded.

---

## 1. The 4 signals (validated, with exact formulas)

### Signal A - Daily clock / sleep window  [HIGH confidence]
- Silent window: 09:00-14:00 UTC = only 14.3% of posts. Deepest 10-11 UTC.
- In ET: quiet 5-10am, deepest 6-7am. Twin daily peaks at 1-2am ET and 1pm ET.
- Best timezone fit: Pacific / night-owl (deepest sleep ~3-4am PT). Do NOT hard-code a fixed
  timezone: his trough wanders month to month (travel). Use the ET clock shape, not a tz label.
- Day-of-week is essentially flat (weekend only ~1.5pp lighter). Do not build heavy DOW logic.

Hour-of-day distribution, share of all posts by ET hour (use as an "expected pace" curve):

| ET hr | % | ET hr | % | ET hr | % | ET hr | % |
|---|---|---|---|---|---|---|---|
| 0  | 5.59 | 6  | 2.44 | 12 | 5.57 | 18 | 3.64 |
| 1  | 6.28 | 7  | 2.75 | 13 | 5.32 | 19 | 3.79 |
| 2  | 5.34 | 8  | 3.80 | 14 | 4.87 | 20 | 3.41 |
| 3  | 4.40 | 9  | 4.70 | 15 | 4.34 | 21 | 3.17 |
| 4  | 2.89 | 10 | 5.09 | 16 | 3.59 | 22 | 3.72 |
| 5  | 2.32 | 11 | 5.69 | 17 | 3.24 | 23 | 4.06 |

### Signal B - Burst continuation hazard  [HIGH confidence on shape]
Given he has been silent `s` minutes, probability he is "done for now" (no post for 2h+):

    P(done | silent s min) = 1 / (1 + EXP( -(-2.649 + 0.761 * LN(s)) ))

Anchor points (empirical, n=10,419 gaps, Nov 2025+):
- At a post: 60% chance of another within 5 min, 83% within 30 min, only ~8% done.
- silent 6 min -> 21% done. silent 15 min -> 32%. silent 32 min -> 50%. silent 90 min -> 80%.
- Sessions (break = gap > 120 min): median 10 posts, median 96 min long.
- Caveat: missing replies inflate some gaps, so true P(done) is slightly LOWER. Treat the
  curve as a conservative upper bound on "done."

### Signal C - Fixed bedtime anchor  [HIGH confidence]
- Tested on 715 active days: corr(start, end) = -0.04, corr(start, duration) = -0.69.
- His STOP time is the anchor, his START is the variable. Last post clusters at ~3:40am ET
  (12:40am PT) regardless of when he started. A late start = shorter day, not a later end.
- Practical rule: once the local clock is past ~3:00am ET AND he has gone quiet (Signal B),
  the day's count is very likely final. Do NOT keep projecting more posts past that.

### Signal D - Retweet partners  [HIGH confidence, Nov25-Jun26 window]
Top partners (share of 5,523 reposts). Three buckets: own companies, amplifiers, politics.

| # | Partner | RTs | % | Bucket |
|---|---|---|---|---|
| 1 | @XFreeze | 340 | 6.2 | amplifier |
| 2 | @cb_doge | 310 | 5.6 | amplifier |
| 3 | @teslaownersSV | 214 | 3.9 | amplifier |
| 4 | @MarioNawfal | 166 | 3.0 | amplifier |
| 5 | @SpaceX | 129 | 2.3 | own company |
| 6 | @SawyerMerritt | 107 | 1.9 | amplifier |
| 7 | @dvorahfr | 100 | 1.8 | amplifier |
| 8 | @Starlink | 82 | 1.5 | own company |
| 9 | @Rothmus | 71 | 1.3 | amplifier |
| 10 | @tetsuoai | 67 | 1.2 | amplifier |

Full list: `q4_retweet_partners.csv`. Use as context only (a repost spike from amplifier
accounts often rides a news/product event), not as a hard count driver.

### Signal E - Burst-cluster count / daily exhaustion  [HIGH confidence]
- At a 90-min session-break: mean 4.4 clusters/day, median 4, and 79% of days have >=4
  clusters (60-min break -> 5.8, 120-min -> 3.6). Source: 224 active days, Nov 2025+.
- Clusters FLOAT in time (not fixed clock slots); slight lean to late-night (0-6am ET) and
  late-morning starts.
- Use: count completed clusters in the window so far. Once >=4-5 clusters are done AND the
  clock is past the bedtime window, P(more posting) is low. Pair with Signals B + C for "done."

### Signal F - Heavy-morning predictor + day-to-day momentum  [HIGH confidence]
- P(heavy day | heavy morning, ET 6-12) = 93% vs 49% base rate. corr(morning, day total) = +0.70.
- Day-to-day momentum: total-posts lag-1 autocorrelation = 0.36 (lag-2 0.32, lag-7 0.19).
  Yesterday heavy -> today heavy.
- Use: by ~noon ET you can already call the day heavy or light; seed today's prior with
  yesterday's count (weight ~0.4) blended with the recent average.

### Signal G - Reply rate is a POSITIVE leading indicator  [HIGH in-window, MED to generalize]
- corr(replies, main-wall posts) = +0.91 (n=42 full-fidelity days, May-Jun 2026). High-reply
  days average 64 main-wall posts vs 32 on low-reply days.
- IMPORTANT correction to the obvious intuition: replies do NOT substitute for main-wall posts.
  Replying and posting are one "engagement intensity" factor; heavy replying signals a HEAVY
  count day. Treat reply rate as an UP signal, never a brake. Re-confirm once the X-API reply
  backfill extends history beyond 6 weeks.

### Signal H - Repost topic fingerprints (per-partner score)  [MED-HIGH confidence]
- Overall repost topic mix: AI/tech 22%, space 12%, politics 10%, tesla 6%, platform-X 4%,
  media 3%, crypto <1%. He reposts AI and space far more than politics.
- Per-partner topic lean (assign as a score per partner):
  - @SpaceX, @Starlink = 100% space  <- these reposts are LAUNCH-EVENT MARKERS
  - @dvorahfr 93% AI-Grok, @tetsuoai 73% AI-Grok
  - @SawyerMerritt = Tesla + space + news (40/41/33%)
  - @XFreeze, @cb_doge, @MarioNawfal, @teslaownersSV = general amplifiers, ~40% AI lean
  - @Rothmus ~0 on keywords (memes/images the classifier misses)
- Use: score each repost's likely topic from its partner; a @SpaceX / @Starlink repost
  partially flags a live event (ties to the dead-zone signal). Keyword classification is
  directional, not exact.

### Signal I - End-anchored clock + routine daytime gaps  [HIGH confidence]
- corr(start, end) ~ 0; whole-window timezone-shift days (start AND end slide together) are
  only ~6% of days. Do NOT model "late start -> late end" - it is false.
- Daytime gaps >=2h are ROUTINE: ~2.6 per day, 8% of waking intervals. A single 2h daytime
  gap is NOT "done" - it is just between-cluster. Only treat silence as "done" when Signal B
  (P-done), the bedtime window (C), and cluster-count (E) agree.

---

## 2. How to layer it (architecture)

Think of it as 5 stacked layers. Each consumes the layer below. Build them as tabs/columns.

```
Layer 4  DECISION OVERLAY    count-final gate (B + C + E agree) + bracket lock;
                             partner/topic context (D, H) as side note
Layer 3  WINDOW PROJECTION   posts-so-far + expected-remaining (A clock); prior seeded by
                             yesterday (F momentum) + heavy-morning flag (F) + reply-rate (G)
Layer 2  BURST STATE         current silence + P(done) (B); clusters-completed (E);
                             in-session flag; routine-daytime-gap guard (I)
Layer 1  PER-POST DERIVED    minutes-since-prior, ET hour, logical day, in-sleep-window, is_reply
Layer 0  RAW POST STREAM     ts_et + type per qualifying post inside the current noon-ET window
```

Design rules:
1. Anchor every time calc on ET (ts_et), never UTC, never a fixed offset (DST + travel).
2. Keep each layer one tab so a wrong formula in Layer 3 never corrupts Layer 1.
3. Signal roles, do not mix them up:
   - A (clock) + F (momentum + heavy-morning) + G (reply-rate) shape the REMAINING-posts estimate.
   - B (P-done) + C (bedtime) + E (clusters done) drive the FINAL gate (all three must agree).
   - D (partners) + H (topic) are display-only context. Do NOT let them move the number.
   - I (end-anchored + routine gaps) is a guard: it BLOCKS false "done" calls from one gap and
     forbids any "late start -> late end" logic.

---

## 3. Google Sheets implementation (concrete formulas)

Assume a tab `posts` with the current window's qualifying posts, column A = `ts_et`
(real datetime), sorted ascending, header row 1, data from row 2.

### Layer 1 - per-post derived columns (on `posts`)
- B (minutes since prior post):  `=IF(A2="","",(A2-A1)*1440)`  (B2 onward; B2 = first post -> blank)
- C (ET hour):                   `=HOUR(A2)`
- D (in sleep window 4-9 ET):    `=IF(AND(C2>=4,C2<=9),1,0)`
- E (logical day, cut at 7am ET so one row = one wake cycle): `=INT(A2-TIME(7,0,0))`

### Layer 2 - burst state (live "is he done" for the LAST post)
Let `last_gap` = minutes since his most recent post to NOW:
- `last_gap`:   `=(NOW()-INDEX(A:A,COUNTA(A:A)))*1440`  (NOW is volatile; fine for a live tab)
- `p_done`:     `=1/(1+EXP(-(-2.649+0.761*LN(MAX(last_gap,1)))))`
- `p_resume_15m` (chance he posts again within 15 min): pull from `q2_continuation_hazard.csv`
  via VLOOKUP on the nearest silence bucket, or approximate `=1-p_done` for a rough display.
- `in_session`: `=IF(last_gap<90,1,0)`  (90 min = session-break threshold; matches Signal E)
- `clusters_done` (Signal E - bursts completed so far this window): with B = minutes-since-prior
  on the `posts` tab, `=1+COUNTIF(B2:B,">90")`
- `exhausted` (Signal E): `=IF(clusters_done>=5,1,0)`
- `routine_gap_guard` (Signal I): a single >=2h daytime gap is NOT "done". Encoded by requiring
  the bedtime factor in Layer 4, so do NOT flag done on last_gap alone.

### Layer 3 - window projection (posts by noon-ET close)
- `posts_so_far`:        `=COUNTA(A2:A)`
- `hours_remaining`:     `=( <next noon ET datetime> - NOW())*24`
- `daily_prior` (Signal F momentum - blend recent avg with yesterday, weight ~0.4 from the
  0.36 lag-1 autocorr):  `=0.6*recent_daily_avg + 0.4*yesterday_total`
- Expected remaining via Signal A clock (sum the ET-hour shares for the hours left, scaled to
  `daily_prior`):
  `expected_remaining = daily_prior * SUM(share[h] for each ET hour h still ahead before close)`
  (build a 24-row helper tab `clock` with ET hour + share from the Signal A table; SUMIFS the
  hours between NOW ET-hour and the close.)
- `heavy_morning` (Signal F - if morning ET 6-12 already busy, the day runs heavy 93% of time):
  `morning_posts = COUNTIFS(C2:C,">=6",C2:C,"<12")` then
  `morning_mult = IF(morning_posts >= morning_heavy_threshold, 1.15, 1.0)`
- `reply_rate_mult` (Signal G - heavy replying = UP signal, never a brake):
  `reply_share = COUNTIF(<type col>,"reply") / posts_so_far` then
  `reply_rate_mult = IF(reply_share > reply_hot_threshold, 1.10, 1.0)`
- `raw_projection`:      `=(posts_so_far + expected_remaining) * morning_mult * reply_rate_mult`

### Layer 3b - v2 CONDITIONED projection (USE THIS - it beats naive c/f, validated)
THE EDGE IS THE RECENT-VOLUME PRIOR, not the within-window pacing shape. His 2-day pacing is
near-linear on average (so c/f and clock-pacing are no better than each other), BUT his volume
LEVEL is regime-persistent: corr(trailing 6-day baseline, this window's final) = +0.63. Anchoring
early on that baseline cuts prediction error 41% at 25% elapsed (MAE 35 -> 21). This is almost
certainly the edge a session "sees nothing" is missing: do not extrapolate the current window
alone, anchor on his recent days.

- `trailing_prior` = mean final count of the last ~3 same-length windows (strictly BEFORE this
  one; e.g. for a 2-day window, the mean of the prior three 2-day counts). No leakage.
- v2 fitted projection (2-day windows; coefficients by elapsed hour h, window opens noon ET):

  | elapsed | formula (final_hat) |
  |---|---|
  | h=12 (25%) | `17.2 + 1.72*count + 0.53*prior - 1.42*last6h` |
  | h=24 (50%) | `6.6 + 1.14*count + 0.33*prior + 0.10*last6h` |
  | h=36 (75%) | `0.6 + 1.03*count + 0.25*prior - 0.05*last6h` |
  | h=42 (88%) | `1.01*count + 0.11*prior` |

  `count` = posts so far; `prior` = trailing_prior; `last6h` = posts in the last 6 hours.
  Note how `count`'s weight falls toward 1.0 and `prior`'s weight fades as the window matures:
  early -> lean on the baseline; late -> the realized count IS the answer.
- LATE DONE-GATE (Signals B+C+E): if h>=36 AND ET clock in 03:00-10:00 AND silent >=45 min,
  override `final_hat = count` (+0-2). He has gone to bed; stop extrapolating.
- Re-fit these coefficients from `predictive_v2.py` after each canonical refresh.

### Layer 4 - decision overlay (the gate, this is the new edge)
- `past_bedtime`: 1 if current ET time is after 03:00 and before 09:00 (his wind-down to wake)
  `=IF(AND(HOUR(NOW())>=3,HOUR(NOW())<9),1,0)`
- `count_final_conf`: how sure the day's count is locked. Three signals must agree (B + C + E):
  `=MIN(1, p_done * IF(past_bedtime=1,1.0,0.6) * IF(exhausted=1,1.15,1.0))`
- `final_projection`:
  `=IF(count_final_conf>=0.7, posts_so_far, raw_projection)`
  Meaning: once he is quiet enough that P(done) is high, AND it is past ~3am ET, AND he has
  already run his ~5 clusters, stop adding expected-remaining and treat posts_so_far as final.
  The `exhausted` and `past_bedtime` factors stop a single routine 2h daytime gap (Signal I)
  from faking a "done" call.
- Partner / topic context (display only): show the window's top reposted handle from the
  Signal D table and its topic fingerprint from the Signal H table. A @SpaceX / @Starlink
  repost flags a likely live event (expect a short dead zone around it).

Thresholds to expose as editable cells (do not bury in formulas): session-break 90 min,
count-final confidence 0.70, bedtime window 03:00-09:00 ET, sleep window 04:00-09:00 ET,
morning-heavy threshold, reply-hot threshold, momentum weight 0.40.

### Helper tabs to build (paste-ready from artifacts)
- `clock` (24 rows): ET hour + share from the Signal A table.
- `hazard`: import `q2_continuation_hazard.csv` for the VLOOKUP P(resume) column.
- `partners`: import `q4_retweet_partners.csv` + the Signal H topic fingerprints; add a
  boolean `is_event_marker` column (TRUE for @SpaceX, @Starlink).

---

## 4. Validation / QA the Sheets session should run
- Sanity 1: on a known completed window, `final_projection` at +30 min past his last post and
  after 3am ET (with `exhausted=1`) should equal the true final count within +/-2 tweets.
- Sanity 2: rebuild the Signal A clock tab from parquet via analyze.py and confirm the 24
  shares match the table in section 1 (drift means the data refreshed; update both).
- Sanity 3: `p_done` must be monotonic increasing in silence and pass through ~50% at 32 min.
- Sanity 4 (Signal E): `clusters_done` over a full day should land at median ~4 (90-min break).
  If you are seeing 8+ clusters/day, your break threshold is too small.
- Sanity 5 (Signal G): on the full-fidelity window, corr(daily replies, daily main-wall) must
  come out POSITIVE (~+0.9). If you get a negative number your reply/main-wall split is wrong.
- Do NOT trust any window whose posts predate Nov 2025 for repost-inclusive counts, and do NOT
  use reply-based signals (G) outside the May-Jun 2026 full-fidelity window until backfill lands.
- Source of the E-I numbers: `analyze2.py` + `REPORT2.txt` + `daily_features_rich.csv`.

---

## 5. If this later gets wired into the bot (Python touch-points, not your job but FYI)
- Hour/DOW count weighting already exists: `api/modules/shared/pacing.py`
  (`dow_hourly_bayesian_pace`) and `enhanced_pacing.py`.
- Burst self-excitation already exists at 8-15% ensemble weight: `api/modules/shared/hawkes.py`,
  blended in `api/modules/shared/projection.py`.
- NOT yet in code: the calibrated Signal B "P(done after N min)" curve, Signal C fixed-bedtime
  gate, and any Signal D partner use. Those are the net-new pieces this spec adds.
- Entry module: `api/modules/elon_tweets/module.py`.

---

Not in this spec (needs data we do not have yet):
- Event-calendar dead zones (SpaceX launches, Tesla earnings, Rogan, political dates). His
  predictable dead zone is sleep (4-9am ET). Daytime >=2h gaps are routine (~2.6/day) so they
  do NOT mark events on their own. Aligning named events needs an external calendar feed joined
  on date. A @SpaceX / @Starlink repost is the only in-data event marker today (Signal H).
- A calibrated predictive DISTRIBUTION of the final count (not just the point estimate) for
  bracket selection. That is being built separately as the Tier-1 model; it will plug in above
  Layer 4 and consume `final_projection` + `count_final_conf` as inputs.

Owner note: numbers valid as of data through 2026-06-12. Re-run analyze.py (Signals A-D) and
analyze2.py (Signals E-I) after any canonical refresh; update sections 1 and 3 if the clock,
hazard coefficients, cluster counts, or correlations move.
