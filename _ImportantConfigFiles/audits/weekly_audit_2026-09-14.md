# Weekly Audit — 2026-09-14

Branch audited: `feat/newbot-step1-skeleton` @ `4820dd3` (live production code).
Live data: Supabase project `xdonwowgqvmtrduikaon`, last 7 days (2026-09-07 → 2026-09-14).
Report only — no trading logic, risk limits, or module behavior changed. All findings below are
recommendations for human review.

## Summary

The bot fleet has been fully paused since **2026-09-07** (the day of last week's audit) and has
not placed a single order since. The pause was a deliberate owner action, and the engine itself is
healthy and heartbeating normally — so there is very little "live" signal to audit this week. The
bigger story is on the **code** side: the three broken test files flagged last week are still
broken a week and 8 merged PRs later, and they're not a cosmetic problem — they abort the *entire*
`pytest -q` collection, so nothing in `tests/` currently runs in CI, masking 70 passing tests and
hiding that the executor (order-placement) suite is 0/7 passing against current code.

---

## LIVE (Supabase, last 7 days)

### [HIGH] Every module lost money this week; none has ever been net-positive
Per-module realized P&L (positions table, joined to modules):

| Module | 7-day P&L | All-time P&L | Open positions |
|---|---|---|---|
| S2 Basket-Hold | **-$131.01** | -$486.27 | 0 |
| Arb Scanner | **-$221.61** | -$456.31 | 1 |
| Copytrader | **-$39.86** | -$321.73 | 0 |
| Market Maker | $0 | -$35.36 | 0 |
| Sports Sweep | $0 | -$5.12 | 0 |

No module shows a positive realized P&L in either window. These are the same three persistent
losers flagged in last week's audit (S2 Basket-Hold, Copytrader, Arb Scanner) — the underlying
strategies have not been fixed or re-validated since, they were simply paused. Recommend: before
any of these three are re-enabled, require a fresh `@backtest-builder` / `@backtest-auditor` pass
against current canonical data, not just a manual unpause.

### [MEDIUM] Entire fleet has been paused for a full 7 days — confirmed intentional, still worth flagging
All 11 rows in `modules` are `status='inactive'`. 7 carry `inactive_reason='paused_by_owner'`
(Arb Scanner, Copytrader, Elon Late Arb, Elon Reversion, Market Maker, S2 Basket-Hold, Sports
Sweep — all still holding their $500 budget allocation) and 4 are permanently retired
(`decommissioned`: elon_tweets, truth_social; `dead_thesis`: LP Rewards, Mirror Trader — all
budget $0). This matches commit `5b87797` ("all modules paused by owner 2026-09-07") and the
subsequent watchdog/alert fixes (`2f20fa6`, `d815789`, `4279435`) that explicitly stop treating a
"paused on purpose" bench as an alert condition — so this is working as designed, not a bug.
Flagging only because it means: (a) this week's live-data audit is necessarily thin — there is
almost no fresh signal to check — and (b) the bot has now generated zero P&L, positive or
negative, for a full week while $3,500 of budget sits allocated to paused strategies. Worth a
human decision on whether to re-enable a subset, cut budgets further, or leave parked.

### [MEDIUM] Approval health — all activity happened in one ~5-hour burst before the pause
1,309 signals / 562 approved (43%) this week — but **100% of that volume occurred between
13:21–18:24 UTC on 2026-09-07**, immediately before the mass pause; zero signals in the 6+ days
since. Rejection reasons for the week, by count:

| rejection_reason | count |
|---|---|
| circuit_breaker | 365 |
| module_budget_cap_500 | 200 |
| duplicate_resting_order | 120 |
| spread_X>tol_0.3 (various) | ~60 |

`circuit_breaker` is the dominant gate, consistent with `settings.circuit_breaker` showing
**87 all-time trips** and a `cooldown_until` of `2026-09-07T18:45:58Z` (now expired, moot since
the fleet is paused anyway). This is not the "approved≈0 while signals>0" failure class the prior
audit warned about — 43% approval is a normal gate mix — but 87 lifetime breaker trips is a lot,
and lines up with the P&L table above. Recommend checking `daily_pnl` / breaker trip history for
what specifically triggered so many trips before considering re-enabling the paused modules.

### [RESOLVED, confirmed] Foreign "enabled_wallets" writer is dead
`logs` rows matching `%enabled_wallets%`: 2,032 total, all between 2026-08-31 and
**2026-09-07 17:39:02 UTC** — zero rows since. This matches commit `11023e0` ("ghost writer found
and killed - it was our own Railway JaxBot service"), which shipped the same day. Confirmed fixed;
no further action.

### [PASS] Engine liveness
Newest `logs` "Cycle: {...}" row is `2026-09-14 13:17:23 UTC`, `now()` at query time was
`13:20:52 UTC` — well under the 20-minute staleness threshold, and cycles have been landing every
5 minutes around the clock for the full week (spot-checked hourly buckets 2026-09-13/14, 11-12
cycles/hour throughout, no gaps). The engine process itself is healthy; it is correctly evaluating
`modules: 0` every cycle because every module row is `status='inactive'` (`engine.py:62-63` filters
`.neq("status", "inactive")` — this is working exactly as designed, see Module 3 below).

### Elon Late Arb / Elon Reversion — still silent, now masked by the pause
Last week's audit flagged these two as producing zero signals despite being paper-active. Both are
now paused too, so this can't be freshly tested, but neither module produced a single signal even
during Thursday's 5-hour active window before the pause (0 rows in `signals` for either module_id,
7-day window). Recommend re-checking these two specifically (not just re-enabling blind) before
they go back live — the silence predates and survives the pause, so it's unlikely to be
pause-related.

---

## CODE (branch `feat/newbot-step1-skeleton`)

### [CRITICAL] Test suite collection is still broken — `pytest -q` runs zero tests
Confirmed unresolved a full week after last week's audit (`c22fd2e`, 2026-09-07) flagged the exact
same three files, and 8 PRs have merged since without touching this:

- `tests/test_copy_trading.py:16` — `from api.modules.copy_trading.decision import (...)`.
  `api.modules.copy_trading` does not exist; the live module is `api.modules.copytrader`
  (different name, different package).
- `tests/test_engine.py:3` — `from api.services.engine import TradingEngine`. `engine.py` defines
  `class Engine`, not `TradingEngine`.
- `tests/test_risk_manager.py:4` — `from api.services.risk_manager import RiskManager, Signal`.
  `risk_manager.py` has no `RiskManager` class — risk checking is the module-level `check()`
  function plus `Signal`/`RiskVerdict` dataclasses.

A bare `python -m pytest -q` (as documented under `/pre-commit` and this file's own audit
instructions) **aborts collection entirely** with `3 errors during collection`, `Interrupted!` and
runs **0 tests** — it does not skip these three and run the rest. That means if CI/pre-commit
invokes plain `pytest -q`, it has been silently reporting a hard failure (or, worse, being ignored)
for at least a week, and it is hiding that 70 other tests currently pass. Fix: either update these
three files to the current module/class names, or delete them if the surface they tested is gone
for good — but something needs to change so `pytest -q` (no `--ignore` flags) can run at all.

### [HIGH] Executor test suite: 7/7 failing against current code — order-placement code has zero passing coverage
With the three collection-breaking files excluded, `tests/test_executor.py` fails all 7 tests:

- `@patch("api.services.executor.open_position")` (used in 4 of the 7 tests) — `open_position`
  (singular) does not exist anywhere in the codebase. The closest live function is
  `position_manager.open_positions` (plural), a different function with a different signature.
  `unittest.mock` raises `AttributeError: <module ...executor> does not have the attribute
  'open_position'` before the test body even runs.
- `TestLiveExecutor::test_missing_credentials_raises` and `::test_clob_failure_marks_rejected` call
  `LiveExecutor(profile={...})`. `executor.py:41` defines `LiveExecutor.__init__(self)` — it takes
  no arguments now and reads settings internally (this is actually a **good** change: it correctly
  implements the dual live-guard — `environment=="production" and not paper_mode and
  allow_live_trading` — per the CLAUDE.md non-negotiable rule). The test file was never updated to
  match.

Net effect: the code path that actually places (or simulates placing) every order has **no
executable test coverage** right now, live or paper. Given this is the single most money-sensitive
file in the repo, recommend prioritizing this over the sizing/ranking items below.

### [HIGH] `engine.py` still hardcodes the `sports_sweep` module name — Module Architecture Rule 4 violation
Also flagged last week, unchanged:
- `engine.py:201` — `from api.modules.sports_sweep import data as sports_data`
- `engine.py:251` — `self.registry.get("sports_sweep")`
- `engine.py:255` — `.eq("strategy", "sports_sweep")`

CLAUDE.md is explicit: *"Engine/router code MUST NOT hardcode module names... Use the module API."*
The module-agnostic pattern already exists two lines away in the same function (`_live_quotes`'s
"GENERIC coverage" block, `engine.py:208-226`, explicitly fetches quotes for *any* module's resting
order token without naming a strategy) — so the fix pattern is already in the file, it just wasn't
applied to the sports-quotes branch. Recommend extending `BaseModule` with something like
`get_live_quote_tokens()` / `get_series_ids()` so the engine can ask any module for what it needs
to quote, the same way it already asks `get_handle()` / `get_config()`.

### [MEDIUM] `rank_brackets()` default `top_n=5` contradicts its own test's expectation of 3
`api/modules/shared/signals.py:81` — `def rank_brackets(..., top_n: int = 5)`. But
`tests/test_signals.py::TestRankBrackets::test_returns_top_3` calls `rank_brackets(probs, prices)`
with no `top_n` override and asserts `len(result) <= 3`; it gets 5 back and fails. This isn't just
a stale-test cosmetic issue — `rank_brackets` output feeds directly into which brackets a module
signals on, and `risk_manager.py`'s correlated-exposure cap (`_correlated_exposure`,
`max_correlated_exposure`) is the thing standing between "rank more brackets" and "stack more
correlated exposure in one auction." Recommend an explicit owner decision on whether 3 or 5 is the
intended cap, then fix whichever side (code default or test) is wrong.

### [LOW] `kelly_sizing()` time-decay floor vs. its test's zero expectation
`tests/test_signals.py::test_elapsed_100pct_zeros_kelly` expects `kelly_pct == 0` at
`elapsed_pct=1.0`, but `signals.py:61-62` has an explicit, commented 30% floor
(`time_decay = max(1.0 - elapsed_pct, 0.30)`), so it returns `0.0171`, not `0`. This reads as the
test predating the floor being added, not a code bug — but flagging so the test either gets
updated to assert the floor, or someone confirms sizing really should hit exactly zero at 100%
elapsed (in which case the floor is the bug).

### What was checked and passed
- **Risk gate (`api/services/risk_manager.py`), full read.** Fails closed on DB error (`except
  Exception` at L239 returns `RiskVerdict(False, "db_error:...")`), on missing spread/ask
  (L174-175), on missing/zero book depth (L247-248), and on missing edge (L180-181). Every order
  path requires an explicit `price` (`Signal.price`, always used as a limit in the executor) — no
  market-order path exists. The per-module budget cap (`_module_exposure`) is correctly scaled by
  `module_bankroll(signal.module_id)`, **not** the global `bankroll` — the dust floor at L189
  (`signal.notional < 1.0`) is a flat $1 CLOB minimum, not scaled by any bankroll figure at all.
  This is the exact "wrong denominator" bug class this audit was asked to check for, and per the
  file's own inline comment it was already found and fixed (2026-07-29 starvation incident) — no
  regression found.
- **Module isolation.** Grepped every `from api.modules.` import across `api/modules/*`: every hit
  is either a module importing its own subpackage or `api.modules.shared` — zero cross-module
  imports found. All 9 live trading module directories (`arb_scanner`, `copytrader`, `demo`,
  `elon_late_arb`, `elon_reversion`, `lp_rewards`, `market_maker`, `mirror_trader`, `s2_basket_hold`,
  `sports_sweep`) have the required `module.py` / `data.py` / `module_config.py` / `__init__.py`
  (two also have an additive `decision.py`, which doesn't violate the structure).
- **Silent failures.** No `.single()` usage anywhere in `api/` (the PGRST116 class of bug is not
  present). No `TODO`/`FIXME`/`XXX` markers anywhere in `api/`. Spot-checked ~90 `except` blocks
  across `api/services` and `api/modules`: the large majority log via `log.exception(...)` before
  swallowing; the handful of bare `except: pass` are narrowly-typed and commented as intentionally
  inert (`net_tuning.py:28` — `OSError`/`AttributeError` on a non-TCP socket; `tweet_stream.py:117`
  — `RuntimeError` for "no running event loop, not reachable from run()"; `canonical_data.py:300`
  — explicitly labeled "silent — sheet logging is best-effort"). No bare `except: pass` found
  swallowing a broad `Exception` on a money-path.
- **Backtest RUN_META adoption** — spot check only (no backtest files changed this week, so a full
  `@backtest-auditor` pass wasn't triggered). ~9 of 133 scripts under
  `_DataMetricPulls/pacing_backtest/` emit `RUN_META`. Same historical-debt gap noted last week
  (scripts predate the mandate); unchanged, not a new regression.

### What could not be checked
- Test env in this sandbox lacked `pytest`, `pydantic-settings`, `supabase`, `numpy`/`pandas`/
  `scipy`, and `duckdb`; the first three were installed to get `tests/` running, `numpy`/`pandas`/
  `scipy` were installed to unblock `test_signals.py`/`test_projection.py`, but `duckdb` was not,
  so backtest test files under `_DataMetricPulls/pacing_backtest/*_test.py` and
  `scripts/canonical/07_consistency_test.py` still fail to collect on missing `duckdb` — that
  failure is an environment gap in this sandbox, not a confirmed code defect; re-run in an
  environment with the full `requirements.txt` installed to get a real verdict on those.
- No live/production order flow to audit this week (fleet paused entire window) — the executor
  finding above is a **test-coverage** gap, not evidence the live/paper order path itself is
  currently broken.
