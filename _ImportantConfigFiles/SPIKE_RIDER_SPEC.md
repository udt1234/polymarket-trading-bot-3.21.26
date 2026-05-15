# Spike Rider — Design Spec (DEFERRED)

This is the rebuild spec for a new trading module that buys cheap brackets early on recurring count auctions, rides the hype spike, and exits at peak. **First attempt was merged then reverted (PR #30 → revert)** because it was over-engineered and had auction-selection bugs. Rebuild from this spec once core files are cleaned up.

## Why we want it
Analysis of 60,134 historical Elon `price_snapshots` showed:
- Buy-and-hold loses 85-100% in nearly every auction
- BUT prices spike ≥100% from start in 50-75% of auctions
- Best brackets: `40-59` (50% flip rate, +8650% median peak), `160-179` (67%, +423%), `<40` (74%, +194%)

The edge isn't predicting the winner — it's catching the spike before the crash.

## Strategy in plain English
1. At the start of every recurring auction, buy every bracket in price band `[2¢, 40¢]` for $10 each
2. Sell in 1/3 tranches at 2x, 3x, 5x entry
3. Backup safety net: trailing stop 30% off peak after +50% gain
4. Stop entering once auction is past 50% elapsed

## Simulator results (from PR #30 reverted run)
Ran `scripts/simulate_sell_rules.py` over 211 historical Elon brackets in price band [0.02, 0.40]:

| Rule                    | Win % | Median Return | Captured % of Peak |
| ----------------------- | ----- | ------------- | ------------------ |
| **multi_stage_2x_3x_5x** | **78%** | **+155.6%**   | **39%**            |
| target_2x               | 52%   | +75.3%        | -                  |
| trailing_stop_25_min30  | 35%   | -18.5%        | -                  |
| buy_and_hold (baseline) | 13%   | -101.3%       | -                  |

`multi_stage_2x_3x_5x` is the clear winner. Use as the production default.

## Architecture lesson learned
**Don't build a parallel data layer. Clone the Elon module and override the strategy.**

PR #30 created a thin parallel data layer (`auction_series` table, custom `fetch_active_tracking_for_series`) which:
- Picked the wrong auction when xTracker returned 4 active tweets-counting series simultaneously (it grabbed the about-to-end one instead of the freshest)
- Caused dashboard "Loading module" because the page.tsx slug-matching didn't recognize the new module
- Doubled the surface area for bugs

### Correct approach for v2
1. **`cp -r api/modules/elon_tweets api/modules/spike_rider_elon`** — full copy
2. Edit only `_evaluate_async()` to replace ensemble probability logic with: filter brackets by `[entry_min, entry_max]`, emit fixed-$ BUY signals
3. Edit `module_config.py` to add new fields: `entry_size_usd`, `entry_min_price`, `entry_max_price`, `elapsed_max_pct`, `sell_rule_type`, `sell_multi_stage_targets`, `sell_target_multiplier`, `sell_trail_pct`, `sell_min_gain_pct`
4. Keep ALL the existing data fetching: `fetch_active_tracking`, `fetch_market_prices`, `fetch_market_brackets`, etc. They already work.
5. Inserted `modules` row with `name='Spike Rider — Elon'`, `strategy='spike_rider'`, `status='paper'`, `budget=100`

## Required platform changes (these were in PR #30 and need to come back)
1. **`risk_manager._check_edge_threshold` and `_check_negative_ev_aggregate`** — bypass when `signal.metadata['skip_edge_check'] == True`. Spike Rider entries have `edge=0, model_prob=0` because the strategy is price-level-driven, not probability-edge-driven.
2. **`PaperExecutor.execute` and `LiveExecutor.execute`** — partial-sell support. When `signal.metadata['partial_exit'] == True` and `0 < kelly_pct < 1.0`, sell `full_size * kelly_pct` instead of full position. Route through `partial_close_position()` when `size < full_size`.
3. **`engine._get_module_cfg`** — add a branch for the new module's name to load its config from `api.modules.spike_rider_elon.module_config`.
4. **`api/routers/modules.py`** — add a `_resolve_config_io` dispatcher that routes `/api/modules/{id}/config` GET/PUT to the right config getter/saver based on `module.strategy`. Add `SpikeRiderConfigUpdate` Pydantic model with bounds.

## Required UI changes
1. New `web/app/modules/[id]/components/spike-rider-settings.tsx` — entry size, entry price band, elapsed cutoff, sell rule type selector, multi-stage targets, trail %, min gain %, fee/slippage
2. In `web/app/modules/[id]/page.tsx`: detect `module.strategy === 'spike_rider'` early-return path that renders the new settings card + open positions + signals + trade history (skip the truth_social pacing UI which doesn't apply)

## DB schema
Only need ONE new table for v2:

```sql
create table position_exit_state (
  position_id uuid primary key references positions(id) on delete cascade,
  stage_1_done boolean default false,
  stage_2_done boolean default false,
  stage_3_done boolean default false,
  peak_price numeric,
  original_size numeric,
  updated_at timestamptz default now()
);
```

Track multi-stage tranches so a restart doesn't double-sell. Skip the `auction_series` table from PR #30 — by cloning the Elon module the handle is already hardcoded.

## Sell-rule logic (pure function spec)
File: `api/modules/spike_rider_elon/sell_rules.py`

```python
@dataclass
class PositionState:
    avg_price: float          # entry price after slippage/fees
    current_price: float
    peak_price: float         # max observed since open
    original_size: float
    current_size: float
    stages_done: tuple[bool, bool, bool]

def evaluate_multi_stage(state, targets):
    # Returns next pending tranche: ("fraction", 1/N, reason, stage_idx)
    # or None if no target hit yet

def evaluate_trailing_stop(state, trail_pct, min_gain_pct):
    # Returns ("full", reason) when peak >= avg*(1+min_gain) AND price <= peak*(1-trail)
    # else None

def evaluate(state, config):
    # Dispatch by config['sell_rule_type']: multi_stage | target_multiplier | trailing_stop
    # All non-trailing rules also run trailing_stop as backup safety net
```

## Simulator script
`scripts/simulate_sell_rules.py` (was in PR #30, deleted in revert). Replays `price_snapshots` through 10 sell rules. Required:
- `--module elon` flag (looks up module by name substring)
- `--bracket "<40"` to filter to a single bracket
- `--entry-size 10`, `--fee 0.02`, `--slippage 0.05`
- `--entry-min 0.02`, `--entry-max 0.40` (CRITICAL — without these, dust-priced brackets dominate the average return and report becomes useless)
- Rank by **median return** not total P&L (single outlier trades distort sums)
- Always include `buy_and_hold` baseline rule
- Output markdown report to `_ImportantConfigFiles/spike_rider_simulator_report.md`

## How to find the right active auction (the PR #30 bug)
xTracker returns multiple overlapping active trackings for elonmusk (weekly + monthly + 2-day variants). The legacy `truth_social.fetch_active_tracking` picks the **earliest start** = most elapsed = least useful for Spike Rider.

For Spike Rider, pick the tracking with the **largest `endDate - now`** (most time remaining) so there's the longest window for spikes to happen. Implement a new selector function — don't reuse `fetch_active_tracking`.

## Test plan when rebuilt
1. Apply migration with just `position_exit_state` table
2. Insert "Spike Rider — Elon" module row in `paper` status
3. `python -c "from api.modules.spike_rider_elon import Module; print(Module().evaluate())"` — should return BUY signals when an active auction exists with brackets in band
4. Run @qa-code-bug-hunter on the diff
5. Run @verify-bot end-to-end (paper trades land in `positions` table)
6. Watch first multi-stage tranche fire when a bracket hits 2x entry — confirm `position_exit_state.stage_1_done = true` and `positions.size` halved/thirded
7. Flip `paper → active` only after seeing at least one full entry → tranche → final exit cycle
