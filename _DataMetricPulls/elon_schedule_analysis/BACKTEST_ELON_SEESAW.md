# Elon Dead-Time Seesaw Backtest: Full Handoff Spec (2-day + 7-day, by time-to-close)

Self-contained build + run spec for ANOTHER session. You do not need the originating chat.
Supersedes BACKTEST_2DAY_SEESAW.md (broadens it to 7-day and to the time-to-close horizons).

## Objective
Test the dead-time seesaw on Elon tweet-count markets: during his quiet stretches near the end
of a window, accumulate complement pairs (YES+NO on the SAME bracket) for a combined cost under
$1, completing the far leg cheap off the predictable decay, and hold matched pairs to resolution
($1). Risk-free per pair; the open risk is an unhedged leg when a burst flips a bracket live.

## Core hypothesis (this is the whole point of the test)
The edge is concentrated in the FINAL hours, not with ~1 day left. With a day left, brackets
still have momentum and bursts flip them, so quoting against them bleeds. Near close, the count
is effectively locked (not enough time/posts left to cross boundaries), so out-of-reach brackets
decay reliably and pairs complete under $1. Expectation: P&L and pair-completion improve sharply,
and the naked-loss tail shrinks, as time-to-close drops from 48h -> 6h -> 1h.

## Normalize BOTH market types by hours-to-close (the key move)
Do not treat 2-day and 7-day differently. Express every entry by `hours_to_close (htc)`:
- A 2-day market's full window = htc 48 -> 0.
- A 7-day market "from day 6" = its final 48h = htc 48 -> 0.
So both contribute to the same htc axis. Pool them, and also report split by market type.

## The three entry horizons to compare (the experimental variable)
Run the SAME strategy three times, changing only when you are allowed to OPEN positions:
- H48: open anytime htc <= 48 (your "2 days / from day 6").
- H6:  open only when htc <= 6.
- H1:  open only when htc <= 1.
All three HOLD to resolution. Compare net P&L, pair-completion, and naked-loss tail across them.
ALSO report disjoint time-band attribution (P&L of opens in 48->6h vs 6->1h vs 1->0h) so you can
SEE whether the ~1-day-left band is the loser, confirming the hypothesis directly.

---

## Data
- Markets: all 2-day AND 7-day Elon tweet windows present in `canonical/prices/elonmusk`,
  Nov 2025 onward (repost-complete era). REPORT N for each type; if 7-day recent price coverage
  is thin, say so (the final 48h of a 7-day still behaves like a 2-day, so it is informative).
- Window = noon-ET date range parsed from the slug/title (NOT canonical start/end, which are
  trade-derived and ~2x wrong). Reuse the parser + running-count code in `silence_drift.py`.
- Prices: `canonical/prices/elonmusk/*.parquet` -> per (auction, bucket, hour): OHLC of YES last
  trade, `derived_spread`, volume.
- Posts: `canonical/posts`, filter `counts_for_auction == True` -> running count + silence/hour.

## Per-hour reconstructed state (per window, per bracket, per hour h)
- `htc` = hours to window close.
- `count_h`, `silence_h` (hours since last counted post), `dead_h = silence_h >= DEAD_HOURS or
  p_done(silence_h*60) >= 0.5`, where `p_done(s)=1/(1+exp(-(-2.649+0.761*ln s)))`.
- `position` = future (count_h < lo) / current (lo<=count_h<=hi) / past (count_h > hi).
- `P(flip)` = probability the bracket's in/out status changes before close. Use predictive_v2.py:
  `P(final_count > hi)` and `P(lo <= final < hi)`; cheap proxy = high when `d_to_boundary` small,
  `htc` large, `p_done` low. Later horizons -> lower P(flip) -> the theoretical reason H6/H1 win.
- Book proxy: `yes_mid=close`, `yes_ask=close+spread/2`, `yes_bid=close-spread/2` (spread =
  max(derived_spread, 0.01)); `no_ask=1-yes_bid`, `no_bid=1-yes_ask`; hourly `yes_low/high` from OHLC.

## Strategy rules (under test)
OPEN (only if within the active horizon H48/H6/H1 AND `dead_h`):
- For each bracket, rest YES bid = `yes_mid-PAD` and NO bid = `no_mid-PAD`, sized so
  `yes_bid+no_bid <= 1-MARGIN` (only quote pairs that lock >= MARGIN if both fill). Skip if impossible.
- Caps: <= `MAX_PAIRS` and <= `MAX_NAKED` naked shares per bracket.
- Optional flip-guard: skip/cancel a bracket when `P(flip) > FLIP_THRESH` (the user's "stop
  buying the prior bracket near a flip"). Test guard ON vs OFF.
FILL (hourly proxy): YES bid p fills in hour k if `yes_low[k] <= p`; NO bid q fills if
`(1-yes_high[k]) <= q`. Small size assumed to fill on touch (no real depth on history).
ACCOUNT (per bracket): `matched=min(qty_yes,qty_no)` LOCKED, P&L `matched - paired_cost` (FIFO);
`naked=qty_yes-qty_no` marked at bid, settled at resolution. Keep locked vs naked P&L SEPARATE.
This book is buy-and-hold only; it never sells (sells belong to the scalp book, out of scope).
EXIT: hold to close; matched pairs settle $1 (merge); naked settles $1/$0 by winning bracket.

## Parameters to sweep
`ENTRY_HORIZON` in {H48,H6,H1} (primary), `DEAD_HOURS` (1-4), `MARGIN` (1-5c), `PAD` (1-6c),
`MAX_PAIRS`, `MAX_NAKED`, `FLIP_THRESH` (guard off / 0.3 / 0.5 / 0.7).

## Metrics (report per horizon AND per market type; never net alone)
- Locked-pair margin captured (safe carry) and naked-leg P&L, separately.
- Net P&L per window; % windows profitable; distribution.
- Pair completion rate (started pairs that completed < $1 before close).
- Naked-leg loss tail (worst 5% of windows; max single-bracket naked loss = the steamroller metric).
- THE HEADLINE TABLE: rows = H48 / H6 / H1 (and the disjoint bands 48->6 / 6->1 / 1->0),
  columns = net P&L, locked carry, naked tail, completion rate. This table tests the hypothesis.
- Late-burst subset: windows where count jumped >= 15 in < 3h near close; report P&L there
  per horizon (does going later actually dodge the bursts?).

## Baselines to beat
(a) do nothing (0); (b) dead filter OFF (quote every hour in-horizon); (c) take-both at market
each dead hour (locks the guaranteed >$1 small loss; shows resting-vs-lifting value);
(d) buy-and-hold the favorite bracket at horizon start.

## Validation
- Walk-forward: fit params on the earliest 60% of windows, test on the last 40%. No in-sample claims.
- Split results by market type (2-day vs 7-day-final-48h) to confirm they agree once normalized by htc.
- Report N per cell; flag any horizon/market-type cell with < ~15 windows as low-confidence.

## Honest data limits (do not skip, do not oversell)
- Hourly OHLC is last-trade, not bid/ask, no depth. `yes_ask/bid` are spread proxies; fills are
  "price touched your level," not "your size filled." Minute oscillation (where most real seesaw
  fills happen) is INVISIBLE. Spreads/liquidity on out-of-money brackets near close are also
  understated, so H1 fill realism is the weakest, treat H1 results as the most provisional.
- This answers "does the dead-time seesaw pay more and flip less as close approaches,
  directionally" NOT exact cents. Fill-exact P&L comes from replaying the live minute logs
  (`scripts/elon_book_logger.py` output) once ~15-25 markets are collected. A positive result
  here = green light to keep logging, not a sizing signal.

## Implementation (build `backtest_elon_seesaw.py`)
1. Reuse `silence_drift.py`: window parse, running-count, bucket lo/hi.
2. Build per-(window,bucket) hourly frames from `canonical/prices`; align posts for count/silence.
3. For each window x each horizon x each param set: iterate hours ascending, apply OPEN/FILL/
   ACCOUNT/EXIT, settle at the final hour using `final_count -> winning bracket`.
4. Aggregate the metrics; print the headline horizon table + per-band attribution; write a
   report.txt + per-window CSV.
5. Sanity-eyeball 3-4 windows (your simulated fills vs the real price path).
6. Optionally pull P(flip) from `predictive_v2.py` to add the flip-guard arm.

## Output schema (per-window-per-horizon row)
`slug, market_type, horizon, final_count, winning_bucket, n_dead_hours_in_horizon,
pairs_started, pairs_completed, locked_pnl, naked_pnl, net_pnl, max_naked, had_late_burst`

## Reusable code already in repo
- `_DataMetricPulls/elon_schedule_analysis/silence_drift.py` (window parse, count, bucket, drift).
- `_DataMetricPulls/elon_schedule_analysis/predictive_v2.py` (final-count distribution -> P(flip)).
- `scripts/elon_book_logger.py` (live minute logs for the later fill-exact replay).
- Burst hazard / clock / bedtime signals: see LAYERING_HANDOFF.md (Signals A-I).
