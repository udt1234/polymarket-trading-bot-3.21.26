# 2-Day Dead-Time Seesaw: Backtest Strategy

Self-contained. Tests ONE strategy: on 2-day Elon tweet markets, during his DEAD clusters,
accumulate complement pairs (YES+NO, same bracket) for a combined cost under $1, using the
predictable dead-time drift to fill the far leg cheap. Hold matched pairs to resolution ($1).

This is the focused, runnable version. It runs on data we ALREADY have (canonical hourly OHLC),
so it can be tested today. It is DIRECTIONAL evidence, not fill-exact P&L (see Limits).

---

## 1. Scope and data
- Markets: 2-day Elon tweet-count windows, Nov 2025 onward (repost-complete era only).
- Window: parse the noon-ET date range from the market slug/title (NOT canonical start/end,
  which are trade-derived). Window = [start_date 12:00 ET, end_date 12:00 ET].
- Prices: `canonical/prices/elonmusk/*.parquet` -> per (auction, bucket, hour): open/high/low/
  close (YES last-trade), `derived_spread`, volume.
- Posts: `canonical/posts` filtered `counts_for_auction == True` -> running count + silence per hour.
- Reuse the window-parse + running-count code from `silence_drift.py`.

## 2. Per-hour state (reconstruct for every window)
For each window, for each hour h (0..48), for each bracket b:
- `count_h` = counted posts from window start to h.
- `silence_h` = hours since the last counted post as of h (0 if he posted that hour).
- `dead_h` = `silence_h >= DEAD_HOURS` (default 2h) OR `p_done(silence_h*60) >= 0.5`.
- `position` = future (count_h < lo) / current (lo<=count_h<=hi) / past (count_h > hi).
- YES book proxy: `yes_mid = close`, `yes_ask = close + spread/2`, `yes_bid = close - spread/2`
  (use `derived_spread`; floor spread at 0.01). NO is the complement: `no_ask = 1 - yes_bid`,
  `no_bid = 1 - yes_ask`. Hourly `yes_low/yes_high` from OHLC drive fills.

## 3. Strategy rules (the thing under test)
ENTRY (only during dead hours):
- When `dead_h` is true, for each bracket place resting limit BIDS for the current hour:
  - YES bid = `yes_mid - PAD`, NO bid = `no_mid - PAD`, chosen so `yes_bid + no_bid <= 1 - MARGIN`
    (only quote pairs that, if both fill, lock at least MARGIN). Skip brackets where that is
    impossible at PAD.
- Cap exposure: at most `MAX_PAIRS` per bracket and `MAX_NAKED` naked shares per bracket.

FILL MODEL (hourly proxy):
- A resting YES bid at price p fills in a later hour k if `yes_low[k] <= p` (price traded down to
  you). A NO bid at q fills if `(1 - yes_high[k]) <= q`. Fill size = capped by `MAX_*` (we cannot
  see real depth on history; assume your small size fills if the price touches it).

PAIR ACCOUNTING (per bracket):
- `matched = min(qty_yes, qty_no)` = LOCKED. Locked P&L = `matched - paired_cost` (FIFO).
- `naked = qty_yes - qty_no` = exposure, marked at the current bid, settled at resolution.
- Keep locked and naked P&L as SEPARATE lines. (And per the position-separation note: this book
  is buy-and-hold only. It never sells. Any sell belongs to the scalp book, not this test.)

EXIT:
- Hold matched pairs to window close, settle at $1 (merge). Naked legs settle at $1/$0 by the
  winning bracket (= the bracket containing the final count).

## 4. The hypothesis being tested
H1 (edge): dead-hour entries complete pairs UNDER $1 more often / cheaper than active-hour
entries, because the dead-time drift walks the far leg down to your bid. -> run the same rules
with the dead filter ON vs OFF and compare locked margin captured.
H2 (risk): the naked-leg loss tail is bounded, i.e. bursts that flip a sold-against bracket live
do not exceed the locked carry. -> report the naked-leg loss distribution, especially on windows
with a late burst.

If H1 holds and H2's tail is smaller than H1's carry, the dead-time seesaw is a real positive book.

## 5. Parameters to sweep
`DEAD_HOURS` (1-4), `MARGIN` (1-5c, the min pair edge you demand), `PAD` (how far below mid you
bid, 1-6c), `MAX_PAIRS`, `MAX_NAKED`, entry-window filter (e.g. only last 50% of the window,
where decay is sharpest per the drift study: ~-1.7c/hr late vs -0.3c/hr early).

## 6. Metrics (report all, never net alone)
- Locked-pair margin captured per window (the safe carry).
- Naked-leg P&L per window + the worst-5% tail (the steamroller metric).
- Net P&L per window, % windows profitable, distribution.
- Pair completion rate: of pairs you started, how many completed under $1 before close.
- Dead-ON vs dead-OFF comparison (does the dead filter actually help, H1).
- Late-burst subset: net P&L and max naked loss on windows where count jumped >=15 in <3h near
  close (H2).

## 7. Baselines to beat
(a) Do nothing (0). (b) Same rules, dead filter OFF (quote pairs every hour). (c) Take-both at
market each dead hour (locks the guaranteed >$1 small loss; shows the value of resting vs lifting).

## 8. Honest limits (do not skip)
- Hourly OHLC is last-trade, not bid/ask, and has no depth. `yes_ask/bid` are spread proxies;
  fills are "price touched your level" not "your size actually filled." Minute-level oscillation
  (where most of your real scalp/seesaw fills happen) is INVISIBLE here.
- So this backtest answers "does dead-time pair-accumulation tend to be profitable and
  completable, directionally" NOT "you will make exactly X cents." For fill-exact P&L, replay the
  live minute logs (`scripts/elon_book_logger.py` output) once ~15-25 markets are collected.
- Treat a positive result here as a GREEN LIGHT to keep collecting logger data, not as proof to
  size real capital.

## 9. Run sequence (implementation)
1. Build `backtest_2day_seesaw.py`:
   - reconstruct windows + per-hour count/silence/dead (reuse silence_drift.py),
   - load per-(bucket,hour) OHLC + spread,
   - run the entry/fill/pair/exit loop per window,
   - aggregate Section 6 metrics, write a report + per-window CSV.
2. Sweep Section 5 params; print the dead-ON vs dead-OFF table.
3. Eyeball 3-4 example windows (predicted fills vs the actual price path) for a sanity check.
4. If H1 holds and H2 tail is bounded, proceed to logger-based fill-exact replay later.

## 10. Output schema (per-window result row)
`slug, final_count, winning_bracket, n_dead_hours, pairs_started, pairs_completed,
locked_pnl, naked_pnl, net_pnl, max_naked, had_late_burst`
