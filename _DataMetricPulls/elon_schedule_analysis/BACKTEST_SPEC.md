# Seesaw + Flip-Guard Bot: Full Backtesting Strategy

Self-contained. Strategy = ladder complement pairs (YES+NO, same bracket, summing < $1) across
all brackets of an Elon tweet-count market, harvesting the dead-cluster drift, with a FLIP-GUARD:
stop adding to / pull inventory from a bracket when the count is about to cross its boundary.

---

## 0. The honest data problem (read first, it shapes everything)

A true backtest of THIS strategy needs historical minute-level BID/ASK order books per bracket.
We do NOT have that. What exists:
- `canonical/prices` = HOURLY OHLC, last-trade (not bid/ask), no depth. Too coarse for fill sim.
- The live minute logger (`scripts/elon_book_logger.py`) we just started = bid/ask + count +
  p_done per minute, going forward only.

So there are two backtest tracks, and you must run both for different purposes:

- TRACK A - Forward replay (fill-accurate, slow): accumulate logger CSVs over many markets
  (each 2-day market gives ~2,800 minute rows x N brackets). After ~15-25 markets (3-6 weeks)
  you can replay real bid/ask and simulate fills honestly. This is the ONLY track that gives
  trustworthy P&L. Start collecting now; it is the gate.
- TRACK B - Hourly structural backtest (directional, fast, available today): replay
  `canonical/prices` hourly to validate the FLIP-GUARD LOGIC and the drift edge, NOT to size
  P&L. Tells you "does the rule fire at the right times" not "how many cents you make."

Do not present Track B numbers as P&L. They are logic validation only.

---

## 1. The simulation model (precise)

### State (per minute, per bracket b)
`yes_bid, yes_ask, no_bid(=1-yes_ask), no_ask(=1-yes_bid), running_count, hours_to_close,
p_done, silence_min`. All present in the logger CSV.

### Order model
- You rest a ladder of limit BUY orders below mid on BOTH sides:
  YES bids at `mid_y - k*tick` for k=1..L; NO bids at `mid_n - k*tick` for k=1..L.
- FILL rule (forward replay): a resting YES buy at price p fills when `yes_ask <= p` at any
  minute (the book traded down to you). Same for NO with `no_ask <= p`. Conservative: require
  the ask to reach p, not just the mid.
- Each fill adds shares to that bracket's YES or NO inventory at price p.

### Pair accounting (this is the core)
For each bracket track `qty_yes, qty_no, cost_yes, cost_no`.
- `matched = min(qty_yes, qty_no)` shares are LOCKED. Locked P&L = `matched*1 - (paired cost)`.
  Pair cost uses FIFO matching of fills. Locked is risk-free, realized at resolution.
- `naked = qty_yes - qty_no` (signed). This is your exposure. Mark-to-market each minute at the
  current bid (what you could sell for). At resolution the naked side settles to $1 or $0.
- SEPARATE these two in every report. Locked profit is the safe income; naked P&L is where the
  burst losses live. A strategy that looks profitable on net but has fat naked-leg losses is
  the steamroller trade.

### Costs
- Polymarket fees: VERIFY the current schedule before trusting any P&L (historically 0 trading
  fee, gas on merge/settle). Model as `fee_bps` per fill + `gas` per merge, both configurable.
- Slippage: in forward replay, only fill the size available at/below your price (cap by the
  resting depth shown). Do not assume infinite fill.

### Resolution
At window close, winning bracket = the one containing `final_count`. That bracket YES->$1, all
other brackets YES->$0 (NO->$1). Settle all inventory, locked and naked.

---

## 2. The FLIP-GUARD rule (the user's ask, made precise)

A "flip" = the running count crosses a bracket boundary, turning a bracket from in-the-money to
out (or vice versa). The danger: you are accumulating NO on a bracket the count is about to enter
(a buy-low trap), or YES on a bracket the count is about to leave.

### Flip probability (quantify it, do not eyeball)
For bracket b = [lo, hi], current count c, hours-to-close T:
- Distance up to leave/enter: `d_up = (hi + 1) - c` (posts needed to exceed b).
- Distance into b from below: `d_in = lo - c`.
- Use the v2 pace model to get the predictive distribution of the FINAL count, then:
  `P(flip_up) = P(final_count > hi)`, `P(enter) = P(lo <= final_count <= hi)`.
  Short-horizon version using the burst hazard: expected remaining posts before close
  `R_hat = clock_remaining_share * daily_prior` (Layer 3b), and
  `P(reach boundary) ~ P(R_hat >= d)` from the spread of R_hat.
- Cheap live proxy when you lack the full distribution: he is likely to KEEP posting (count
  climbs) when `p_done` is LOW and `hours_to_close` is high; the count is FROZEN when `p_done`
  is HIGH (silent, past bedtime). So `P(flip_up) high` iff `p_done low AND d_up small AND T large`.

### The rule
For each bracket, each minute:
1. If `P(flip_up) > FLIP_THRESH` and you hold NO on b (or are bidding NO): STOP new NO buys on b,
   and optionally lift your YES leg to complete/flatten (the count is coming, b will resolve NO
   only if it overshoots... be explicit about which way). The point: do not keep buying the side
   a flip will zero out.
2. If `p_done > DONE_THRESH` (count frozen, e.g. past bedtime + silent 45m+): the current bracket
   is locking. Safe to hold YES on it / buy its cheap NO complement is NOT safe. Lean to the
   in-the-money side.
3. Always cap `|naked|` per bracket at `NAKED_CAP`. The guard limits how wrong a single flip can
   go.

The backtest's whole job is to find `FLIP_THRESH`, `DONE_THRESH`, `NAKED_CAP`, ladder depth L and
tick spacing that maximize net P&L while keeping the naked-leg loss tail bounded.

---

## 3. Parameters to sweep
`L` (ladder rungs 1-6), `tick_spacing` (1-5c), `NAKED_CAP` (shares), `FLIP_THRESH` (0.3-0.8),
`DONE_THRESH` (0.5-0.8), `fee_bps`, entry window (only trade when `hours_to_close` in [a,b]),
`min_make_both_margin` (only rest pairs when `make_both < 1 - m`).

## 4. Metrics (report ALL, never just net)
- Net P&L, and SPLIT: locked-pair P&L vs naked-leg P&L.
- Per-cycle (per market) P&L distribution; % cycles profitable.
- Naked-leg loss tail: worst 5% of cycles, max single-bracket naked loss (the steamroller metric).
- Fill rate per side; how often only one leg filled (legging frequency).
- Max `|naked|` reached; time-in-naked.
- Sharpe / return per $ at risk; max drawdown across the cycle sequence.
- FLIP-GUARD A/B: run identical params with the guard ON vs OFF. The guard earns its keep only
  if it cuts the naked-loss tail more than it cuts locked income.

## 5. Validation
- Walk-forward: fit thresholds on the first 60% of collected markets, test on the last 40%.
  Never report in-sample.
- Regime split: high-volume vs low-volume weeks; early-window vs late-window entries.
- BURST STRESS TEST: tag the subset of markets with a late burst (count jumped >=15 in <3h near
  close). The guard's entire value proposition is surviving these. Report P&L on this subset
  separately, guard ON vs OFF.
- Baselines to beat: (a) hold cash (0), (b) seesaw with NO guard, (c) always-hedge-at-market
  (locks the take_both > $1 guaranteed small loss), (d) buy-and-hold the favorite bracket.

## 6. Build sequence
1. NOW: run the logger on every live Elon market (2-day + weekly). One CSV per market. This is
   the data-collection gate; nothing trustworthy is possible without it.
2. Build the Track-B hourly structural sim on `canonical/prices` to validate the flip-detector
   logic (does `P(flip_up)` spike before real boundary crossings?). Fast, available today.
3. After ~15-25 logged markets: build Track-A forward-replay fill sim consuming the logger CSVs.
4. Sweep params (Section 3), report metrics (Section 4), validate (Section 5).
5. Only after Track-A shows positive net P&L with a bounded naked-loss tail across walk-forward:
   wire a live executor (paper mode first), reusing the bot's CLOB client + risk checks.

## 7. Backtest input schema (matches the logger CSV exactly)
`ts_utc, hours_to_close, window_count, silence_min, p_done, count_age_sec, bracket,
yes_bid, yes_ask, no_bid, no_ask, yes_mid, spread, take_both, make_both, volume,
setsum_yes_ask, setsum_yes_bid, n_brackets`

The replay engine groups by market (one CSV), iterates minutes ascending, maintains per-bracket
inventory, applies the order + fill + guard model, and settles at the final minute using
`window_count` -> winning bracket.

## 8. The one number that decides it
Net P&L is not the headline. The headline is: does the flip-guard keep the naked-leg loss tail
smaller than the locked-pair income across the burst-stress subset? If yes, the strategy is a
real positive-carry market-making book. If the burst tail eats the carry, it is the steamroller
trade and must not go live. The backtest exists to answer exactly that.
