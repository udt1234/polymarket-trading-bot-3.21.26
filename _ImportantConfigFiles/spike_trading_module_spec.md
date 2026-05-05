# Spike Trading Module — Specification & Build Plan

**Status**: Spec only. Do not implement until reviewed.
**Source data**: 51 historical Elon Musk 2-day `<40` Polymarket auctions (Jan-May 2026), 147,892 trades, 2,442 hourly tweet snapshots from xTracker.
**Sample size**: Moderate — directional findings, not statistical proof.

---

## Part 1 — Plain-English Strategy Description

### What the module does
"Spike Trading" looks at recurring Polymarket prediction-market auctions where the same question repeats on a clock (every 2 days, every week, etc.). It finds the auctions where:

1. **The market starts cheap** — usually 0.3¢ - 1.0¢ for the bracket we trade
2. **The price spikes during the auction** — typically reaching 3-7¢ at some point
3. **The bracket either wins big (~99¢) or dies (~0¢)** — bimodal outcome

The bot:
- **Buys very cheap (0.3-0.5¢)** as soon as the auction opens
- **Sells in 4 tiers** as the price rises (3¢ → 7¢ → 15¢ → 30¢+), locking in profit progressively
- **Holds the position if the underlying signal stays favorable** (e.g., Elon stays quiet → `<40` is winning, don't sell early)
- **Dumps the entire position immediately** if the signal turns hostile (Elon tweets pile up → bracket is dying)

### Plain-English example walkthrough

> "It's Tuesday at 12pm. A new Polymarket auction opens: 'Will Elon Musk post `<40` tweets from Tuesday to Thursday?' YES outcome trades at 0.4¢.
>
> The bot places a **limit buy at 0.5¢ for $50** and another **at 0.3¢ for $50**. Within an hour both fill. The bot now owns about 14,000 shares of YES at average 0.4¢, total cost $54.
>
> Wednesday morning, Elon has only tweeted 2 times. The bot's pacing model says `<40` is on track. Price has rallied to 4¢. The bot sees the **HOLD signal** because we're in the (0-5 tweets, 30-36h remaining) state which historically ends >30¢ in 25% of cases. **No sells trigger yet.**
>
> Wednesday afternoon, Elon goes on a tweetstorm: 18 tweets in 4 hours. The bot's tweet count crosses into the (16-20, 24-30h) zone. That's a **SELL-NOW signal** — historically 70%+ of auctions in this state ended at ≤1¢. The bot **liquidates immediately** at the current price (~5¢), capturing **+1,150% return** on entry before the bracket dies.
>
> Total profit on the cycle: ~$622 on $54 bankroll deployed. Bracket eventually closed at 0.1¢ (dead). Without the SELL-NOW trigger, the entire position would have lost 99%."

### Why this works (the underlying market structure)

`<40` (and other tail brackets) is a **lottery ticket**. Most of the time it dies. But there's a small probability it pays huge. The market initially prices it accurately (0.3-1¢, ≈1% chance), but as new information arrives (cumulative tweet count rises or falls), the implied probability swings violently — often to 5%+ before correcting back to 0% near the end.

Three sources of edge:
- **Front-running**: Be on the books at 0.5¢ before the auction is liquid. Many traders only show up after volume picks up at 2-3¢.
- **Tweet-count signal**: We have **better information than the market in the first 24 hours** because we ingest xTracker's count at a 1-hour lag, but most retail traders manually refresh hourly at most.
- **Tier laddering**: Mathematical guarantee against giving back gains. Each tier locks in profit independently.

### What's the catch?

1. **Sample size is moderate** (51 markets, 4 months). The pattern could weaken if Elon's posting style changes regimes.
2. **Liquidity at the floor** is shallow. $100 size is fine; $1,000+ may not fill at 0.5¢.
3. **Catastrophic single trades happen** — every ~20 cycles, you lose 100% with no chance to exit. The expected-value math accommodates this; the bankroll allocation must too.
4. **xTracker tweet feed has a 30-60 min lag**. The bot can't react in real-time to a tweet — it learns about it on the next snapshot.

---

## Part 2 — The Decision Logic (the actual rules)

### Buy rules

| When | Place |
|---|---|
| New 2-day `<40` auction goes live (T-48h) | Limit buy 50% of allocation at **0.5¢** |
| Same time | Limit buy 50% of allocation at **0.3¢** |
| 24 hours pass with no fill | Cancel both, walk away (auction is too rich) |

Total allocation per cycle = `bankroll × bracket_cap_pct` (default 5%).

### Sell ladder (placed immediately after first buy fill)

| Tier | Limit-sell price | % of position | Why |
|---|---|---|---|
| **T1** | **3¢** | 25% | Hits in 85% of past auctions — almost always |
| **T2** | **7¢** | 25% | Hits in 61% — typical peak |
| **T3** | **15¢** | 25% | Hits in 41% — strong moves |
| **T4** | **30¢+** | 25% | Moonshot tier — hits in 20% |

### HOLD/SELL override (the critical innovation)

Every engine cycle (5 min), recompute current state: **(cumulative tweets so far, hours remaining to close)**. Look up that state in the HOLD signal grid. Apply the rule.

**HOLD-WORTHY state** (don't liquidate even if up 5×):
- 0-5 tweets at any time T-48h to T-30h → **HOLD**
- 0-5 tweets at T-24h with median end-price 99¢ in history → **HOLD**

**SELL-NOW state** (liquidate everything at market):
- 16+ tweets with 24+ hours remaining
- 20+ tweets with 18+ hours remaining
- 30+ tweets at any time

Rationale: in these states, **>70% of historical auctions ended at ≤1¢**. Whatever paper gain you have right now, it's evaporating in the next few hours.

**SELL state** (let the existing limit ladder work, but cancel any T3+T4 limits):
- Mid-state (e.g. 10-15 tweets at 18-24h)
- Pull aggressive sell orders so you don't accidentally fill higher than the market warrants

### State-machine diagram (text form)

```
       [auction opens]
              |
              v
    +-> [WAITING_FOR_FILL]
    |         |
    |         | (limit buys placed; cancel after 24h if unfilled)
    |         v
    |   [MONITORING_HOLD]
    |         |
    |         | every 5 min: check (tweets, hours_left)
    |         v
    |    +-----+-----+
    |    |     |     |
    |  HOLD  SELL  SELL-NOW
    |   |      |      |
    |   v      v      v
    | (no-op) (let   (market-sell
    |        ladder  everything)
    |         fill)        |
    |         |            v
    |         v        [LIQUIDATED]
    |    [LADDER_FILLING]
    |         |
    +<--------+ (recurses each cycle)
              |
              v
        [auction closes]
              |
              v
        [RESOLVED/EXPIRED]
```

---

## Part 3 — Modular Build Plan

### File layout (mirrors existing `truth_social/` and `elon_tweets/` modules)

```
api/modules/spike_trading/
├── __init__.py            — exports SpikeTrading module class
├── module.py              — main module: discovers active markets, runs cycle
├── module_config.py       — config schema + DEFAULT_CONFIG
├── data.py                — fetches market list from Gamma + cumulative tweets from xTracker
├── decision.py            — HOLD/SELL/SELL-NOW classifier (the heatmap as code)
├── executor.py            — places/cancels limit orders, market-sells on emergency
└── README.md              — strategy summary + key numbers
```

### Database additions

**Migration 010_spike_trading.sql**:

```sql
-- Per-market state tracking for spike trading positions
create table if not exists spike_positions (
  id uuid primary key default gen_random_uuid(),
  module_id uuid references modules(id),
  market_id text not null,
  bracket text not null,                  -- e.g. '<40'
  state text not null,                    -- WAITING / MONITORING / LIQUIDATED / RESOLVED
  entry_price numeric,
  entry_size_shares numeric,
  entry_size_usd numeric,
  current_tweets int,
  hours_to_close numeric,
  last_decision text,                     -- HOLD / HOLD-LIGHT / SELL / SELL-NOW
  last_decision_at timestamptz,
  ladder_orders jsonb default '[]',       -- list of {tier, price, size, order_id, status}
  realized_pnl numeric default 0,
  unrealized_pnl numeric default 0,
  opened_at timestamptz default now(),
  closed_at timestamptz,
  end_price numeric                       -- final bracket resolution
);

create index idx_spike_module on spike_positions(module_id);
create index idx_spike_state on spike_positions(state);
create index idx_spike_market on spike_positions(market_id);

-- Snapshot table to record (tweets, hours_left, price) at every cycle for backtesting later
create table if not exists spike_state_snapshots (
  id uuid primary key default gen_random_uuid(),
  position_id uuid references spike_positions(id),
  cum_tweets int,
  hours_to_close numeric,
  current_price numeric,
  decision text,
  captured_at timestamptz default now()
);

create index idx_spike_snap_pos on spike_state_snapshots(position_id, captured_at desc);
```

### Module config schema

```python
# api/modules/spike_trading/module_config.py
DEFAULT_CONFIG = {
    # Discovery
    "platform": "x",                          # 'x' for Elon, 'truthsocial' for Trump
    "handle": "elonmusk",
    "window_days": 2,                         # only trade 2-day auctions
    "bracket_pattern": "<40",                 # which bracket to trade
    "min_market_volume_24h": 50_000,          # skip illiquid markets

    # Buy ladder
    "buy_tier_1_price": 0.005,                # 0.5¢
    "buy_tier_1_pct": 0.50,                   # 50% of allocation
    "buy_tier_2_price": 0.003,                # 0.3¢
    "buy_tier_2_pct": 0.50,
    "buy_cancel_after_hours": 24,

    # Sell ladder
    "sell_tier_1_price": 0.03,                # 3¢
    "sell_tier_1_pct": 0.25,
    "sell_tier_2_price": 0.07,
    "sell_tier_2_pct": 0.25,
    "sell_tier_3_price": 0.15,
    "sell_tier_3_pct": 0.25,
    "sell_tier_4_price": 0.30,
    "sell_tier_4_pct": 0.25,

    # HOLD/SELL override grid (data-driven thresholds from historical analysis)
    # Hold: stay in position even if up 5x because median end_price > 30c
    "hold_tweet_max": 5,                      # ≤ this many tweets means HOLD
    "hold_hours_min": 24,                     # ≥ this many hours left means HOLD

    # Sell-now: liquidate everything, bracket is dying
    "sellnow_grid": [
        # (min_tweets, min_hours_remaining)
        (16, 24),
        (20, 18),
        (30, 0),                              # 30+ tweets at any time
    ],

    # Risk
    "bracket_cap_pct_of_bankroll": 0.05,      # 5% per cycle max
    "stop_loss_pct": -0.5,                    # bail if down 50%

    # Backtesting hooks
    "shadow_mode": True,                      # log decisions but don't execute
}
```

### Cycle pseudocode

```python
# api/modules/spike_trading/module.py
class SpikeTradingModule(BaseModule):
    name = "spike_trading"

    async def evaluate(self) -> list[Signal]:
        cfg = self.get_config()
        signals = []

        # 1. Discover active 2-day <40 markets matching pattern
        active = await self.find_active_markets(cfg)

        # 2. For each active market, manage its position
        for market in active:
            position = self.get_or_create_position(market)

            # Fetch current state
            state = await self.compute_state(market, position)

            # Apply decision
            decision = self.classify_decision(state, cfg)

            # Take action
            if position.state == "WAITING":
                if not position.has_orders:
                    signals.extend(self.place_buy_ladder(market, cfg))
                elif state.hours_since_open > cfg.buy_cancel_after_hours and not position.any_filled:
                    signals.append(self.cancel_all_buys(position))

            elif position.state == "MONITORING":
                if decision == "SELL-NOW":
                    signals.append(self.market_sell_all(position))
                elif decision == "SELL":
                    signals.append(self.cancel_t3_t4_orders(position))
                elif decision == "HOLD":
                    pass  # let ladder fill organically
                # HOLD-LIGHT: same as HOLD, but tighten T4 limit slightly

            # Record snapshot for later analysis
            self.snapshot(position, state, decision)

        return signals
```

### Decision classifier (the heart)

```python
# api/modules/spike_trading/decision.py
def classify_decision(state, cfg) -> str:
    """Return 'HOLD', 'HOLD-LIGHT', 'SELL', 'SELL-NOW' for current state."""
    tweets = state.cum_tweets
    hours = state.hours_to_close

    # SELL-NOW (highest priority — bracket is dying)
    for min_tweets, min_hours in cfg["sellnow_grid"]:
        if tweets >= min_tweets and hours >= min_hours:
            return "SELL-NOW"

    # HOLD (best case — bracket is winning)
    if tweets <= cfg["hold_tweet_max"] and hours >= cfg["hold_hours_min"]:
        return "HOLD"

    # HOLD-LIGHT (decent case — likely still wins, less aggressive)
    if tweets <= 10 and hours >= 18:
        return "HOLD-LIGHT"

    # Default: SELL (let limit ladder work)
    return "SELL"
```

### Tests

**`tests/test_spike_trading.py`** must cover:
1. Discovery filters: only 2-day windows, only `<40`, only above min volume
2. Buy ladder: places 2 limit orders at correct prices and sizes
3. State transitions: WAITING → MONITORING → LIQUIDATED → RESOLVED
4. SELL-NOW triggers at exactly the documented thresholds
5. HOLD overrides do NOT cancel ladder orders
6. Cancel-after-24h logic for unfilled buys
7. Backtest replay: feed historical market data (from parquet) and verify decisions match the heatmap

### Dashboard additions

**Module page**: new "Spike Trading" tab with:
- Active positions table (state, entry, current_price, P&L, decision)
- Decision log per position (heatmap state at each cycle)
- Historical performance chart (median return per cycle, vs the simulator's predictions)
- Manual overrides (force-sell button, force-cancel button)

### Rollout phases

| Phase | Duration | Goal |
|---|---|---|
| **Phase 1: Shadow mode** | 4 weeks | Run logic in production but only LOG signals, never trade. Compare against actual past auctions. Validate the patterns hold. |
| **Phase 2: Paper trading, $1 size** | 2 weeks | Real fills against paper executor at minimum size. Verify ladder orders behave correctly in production wires. |
| **Phase 3: Paper trading, $50 size** | 2 weeks | Match the simulation's assumed entry size. Measure actual fill rates on 0.5¢ limits. |
| **Phase 4: Live, $20-50 per cycle** | Ongoing | Real money. Monitor weekly. |

### Failure modes to guard against

1. **Tweet count feed lag**: xTracker can be 30-60 min stale. Use a "tweet count is fresh" guard — if last update >2h ago, default to SELL (be conservative).
2. **Limit order queue position**: At 0.5¢ on a hot market, your limit might be 8th in line. Tracker → if buy doesn't fill within 6h, walk away.
3. **Cumulative tweet count from xTracker doesn't match real-time**: build a `verify_count` mode that polls the platform directly (Truth Social Direct or X API via IFTTT) and warns if discrepancy >3 tweets.
4. **Catastrophic loss**: 5% of cycles will lose 100%. Module-level circuit breaker: pause module after 3 consecutive 100% losses; require manual restart.
5. **Polymarket changes the bracket scheme**: hardcoded `<40` won't work if Elon's volume changes again. Build a "lowest bracket" auto-detector as fallback.

### Integration with existing infra

- **Re-uses**: risk_manager (15-check pipeline), executor (paper/live), engine cycle scheduler, alerts/notifications, dashboard module page framework
- **Adds**: spike_positions table, spike_state_snapshots table, decision classifier, ladder order manager
- **Doesn't break**: Trump module, Elon module — they continue running independently

### Acceptance criteria (Phase 1 → Phase 2 promotion)

- [ ] 4 weeks of shadow data shows median per-cycle profit > +200% in simulator OR matches historical heatmap within ±20%
- [ ] Zero tweet-count-feed errors that caused wrong decisions
- [ ] All 7 unit tests pass
- [ ] @risk-auditor sign-off on the SELL-NOW liquidation path (most dangerous code)
- [ ] Documented runbook for "module is misbehaving" emergency manual override

---

## Part 4 — Files & Reference Data

| File | Purpose |
|---|---|
| `_DataMetricPulls/elon_2day_analysis/qualifying_markets.csv` | The 54 source auctions |
| `_DataMetricPulls/elon_2day_analysis/buy_floor_levels.csv` | Source for buy ladder prices |
| `_DataMetricPulls/elon_2day_analysis/sell_tier_levels.csv` | Source for sell ladder prices |
| `_DataMetricPulls/elon_2day_analysis/hold_signal_grid.csv` | Source for HOLD/SELL/SELL-NOW thresholds |
| `_DataMetricPulls/elon_2day_analysis/plummet_pivot.csv` | Plummet trigger reference |
| `_DataMetricPulls/elon_2day_analysis/decision_brief.md` | Plain-English summary |
| Google Sheet tabs E1-E9 | All of the above, with descriptions, formatted, browsable |

Sheet: https://docs.google.com/spreadsheets/d/1c00JV2Oot8axapqkd9dF2bWRZQbCKCB5sc5gC_tSH8w/edit

---

## Part 5 — When to Build This

**Don't build yet.** Wait until:
1. Trump + Elon modules have been running cleanly for 2+ weeks (no `pending_signals` table-style emergencies)
2. We've validated the parquet data is what we think it is (run a 5-day shadow to compare to live xTracker counts)
3. Sample size has grown — even 2 more months of data improves the analysis materially

**When ready**, spawn a fresh Claude session with:
- This spec
- The CSVs in `_DataMetricPulls/elon_2day_analysis/`
- The HANDOFF.md note about parquet data tooling
- "Build the spike_trading module per `_ImportantConfigFiles/spike_trading_module_spec.md`. Phase 1 only — shadow mode."
