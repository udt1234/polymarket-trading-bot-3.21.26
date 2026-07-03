# Elon Schedule - Deep Correlation Pass (Q1-Q6)

Source: analyze2.py + REPORT2.txt + daily_features_rich.csv. Window: Nov 2025+ (originals+
reposts) except Q4 which uses the May-Jun 2026 full-fidelity (reply-captured) window. Folded
into LAYERING_HANDOFF.md as Signals E-I.

## Q1 - Start vs end / timezone shift  [HIGH]
- corr(start, end) = +0.07 (~zero). corr(start, span) = -0.66. corr(end, span) = +0.71.
- His END is the anchor; a late start = shorter day, not a later end. P(late end | late start)
  = 20% vs 25% base. Whole-window timezone-shift days = ~6%. No usable "late start -> late end."

## Q2 - Burst clusters per day  [HIGH]
- 90-min break: mean 4.4 clusters, median 4, P(>=4) = 79%. (60-min -> 5.8; 120-min -> 3.6.)
- Clusters float in time; slight lean to late-night + late-morning starts. Your "4 clusters,
  80%" intuition was accurate at the 90-min definition.

## Q3 - Conditional cadence  [HIGH]
- P(heavy day | heavy morning) = 93% vs 49% base; corr(morning, total) = +0.70.
- corr(morning, rest-of-day) = +0.25 (modest). Day-to-day momentum: lag-1 autocorr = 0.36.
- corr(reposts, originals) = +0.76 (move together = one "active day" factor, not substitution).
- Days ending 2-4am ET (38%) look identical to average days. 3am-stop IS the default mode.

## Q4 - Replies vs main-wall  [HIGH in-window, MED to generalize]
- corr(replies, main-wall) = +0.91. High-reply days avg 64 main-wall vs 32 on low-reply days.
- User hypothesis (more replies = fewer posts) is WRONG. One engagement-intensity factor;
  reply rate is a POSITIVE leading indicator of a heavy count day. n=42 days; re-confirm post-backfill.

## Q5 - Event alignment / dead zones  [SPLIT]
- Predictable dead zone = sleep, 4-9am ET (validated).
- Daytime >=2h gaps are routine: ~2.6/day, 8% of waking intervals -> a single gap is NOT "done".
- Named-event alignment (launches, earnings, Rogan) needs an external calendar feed. Only
  in-data event marker today: @SpaceX / @Starlink reposts (100% space).

## Q6 - Repost topic scoring  [MED-HIGH]
- Overall mix: AI/tech 22%, space 12%, politics 10%, tesla 6%, platform-X 4%, media 3%, crypto <1%.
- Per-partner fingerprints: SpaceX/Starlink 100% space; dvorahfr 93% / tetsuoai 73% AI; SawyerMerritt
  Tesla+space+news; XFreeze/cb_doge/MarioNawfal ~40% AI; Rothmus ~0 keyword (memes/images).
- Keyword classification is directional. Use to score a repost's likely topic + flag events.

## Q7 - Backlog (see chat for full ranked list)
Tier 1 (have data): predictive distribution; momentum prior; reply-rate indicator; post-length
rapid-fire; originals topic vs volume; self-reply threads; @grok engagement; cashtags/media.
Tier 2 (need a pull): event calendar; per-post engagement; TSLA price; reply backfill; deletions.
Tier 3 (regime/meta): regime clustering + transitions; sleep-gap-midpoint tz detection;
count-rule arbitrage; holiday/week-of-month; post-event catch-up surge.
