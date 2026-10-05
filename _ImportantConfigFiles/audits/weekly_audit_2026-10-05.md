# Weekly Audit — 2026-10-05

Branch audited: `feat/newbot-step1-skeleton` @ `4820dd3` (live production code, not `master`).
Live data: Supabase project `xdonwowgqvmtrduikaon`, last 7 days unless noted.

## TL;DR

The live bot is **completely idle** — every module is `inactive` and has emitted zero
signals for ~28 days — and the project's CLAUDE.md describes a different bot entirely
(the retired `master` codebase: `truth_social`/`elon_tweets`/`spike_trading`/`copy_trading`),
none of which exist on this branch. Code quality on the live branch itself is solid
(risk gate fail-closed, module isolation clean) but `pytest` is currently broken.

---

## LIVE Findings (Supabase)

### CRITICAL

**L1 — Bot is fully idle: all 11 modules inactive, zero signals in 7+ days, last signal 28 days ago.**
- `signals`: 0 rows in the last 7 days. All-time: 377,379 rows, but `max(created_at)` = `2026-09-07 18:23:51 UTC` — nothing since.
- `modules`: all 11 rows are `status = 'inactive'` (7× `paused_by_owner`, 2× `decommissioned`, 2× `dead_thesis`). None are `active`.
- `logs` Cycle entries confirm the engine itself is alive and healthy (newest at `2026-10-05 13:29:39 UTC`, ~5 min cadence — not stale), but every single one reads `Cycle: {'modules': 0, 'signals': 0, 'approved': 0, 'paper_fills': 0, 'errors': 0}` — the engine loop runs, finds zero active modules, and does nothing, every 5 minutes, for weeks.
- Timeline: commit `91915ae` (2026-09-01) explicitly revived 4 silent modules after a 12-day dead period and verified live signal generation. Signals resumed and then stopped again around `2026-09-07`, which lines up with `settings.circuit_breaker` showing `trips: 87`, `cooldown_until: 2026-09-07T18:45:58Z` (now in the past — the breaker is not currently holding anything back, modules are simply turned off).
- **This needs a human decision, not a code fix**: is the full stop intentional (owner paused everything after losses — see L2), or did it silently happen and get forgotten? Either way, right now nothing is being traded.

### HIGH

**L2 — Net negative realized P&L across every module that has ever traded; total -$1,304.79.**
| Module | Positions | Realized P&L (all-time) |
|---|---|---|
| S2 Basket-Hold | 67 | **-$486.27** |
| Arb Scanner | 33 | **-$456.31** |
| Copytrader | 100 | **-$321.73** |
| Market Maker | 4 | -$35.36 |
| Sports Sweep | 10 | -$5.12 |
| elon_tweets / LP Rewards / truth_social / Elon Reversion / Elon Late Arb / Mirror Trader | 0 each | $0.00 (never traded) |

7-day realized P&L is $0 for every module (consistent with L1 — nothing has traded this week). No open positions / unrealized P&L anywhere (consistent with everything being flat and inactive). This negative run, plus 87 lifetime circuit-breaker trips, is the most likely reason the owner paused everything (L1) — worth confirming.

**L3 — CLAUDE.md documents a bot that does not exist on this branch.**
CLAUDE.md's module list (`truth_social`, `elon_tweets`, `spike_trading`, `copy_trading`) and its large "⭐ SPIKE TRADING" section have **zero overlap** with the 10 real module directories on `feat/newbot-step1-skeleton`: `arb_scanner`, `copytrader`, `demo`, `elon_late_arb`, `elon_reversion`, `lp_rewards`, `market_maker`, `mirror_trader`, `s2_basket_hold`, `sports_sweep`. There is no `spike_trading/` directory anywhere in this branch's `api/modules/`, and no `Spike Trading` row in the Supabase `modules` table. CLAUDE.md is describing the retired `master` bot in full — any session (human or Claude) that reads CLAUDE.md for "what should the live bot be doing" will reason about a system that was never deployed here. Recommend either branch-scoping CLAUDE.md or adding an explicit banner pointing at the live branch's own module list.

### MEDIUM

**L4 — 4 modules are dead weight in the `modules` table.** `elon_tweets` and `truth_social` are `decommissioned`, `lp_rewards` and `mirror_trader` are `dead_thesis`; all four have `budget = 0` and have **never held a single position**. Low-risk cleanup candidate: archive/delete these rows (and, if confirmed unused, their code dirs — `lp_rewards/`, `mirror_trader/`) rather than carrying them forever as inactive rows next to the 7 that are merely paused.

**Clean / no finding:** no `logs` row matching `%enabled_wallets%` was found anywhere in the table's full history — no evidence of a foreign/legacy wallet-key writer on this shared DB.

---

## CODE Findings (`feat/newbot-step1-skeleton`)

### HIGH

**C1 — `python -m pytest -q` fails outright; 0 tests run.** Three files abort collection:
- `tests/test_copy_trading.py` → `ModuleNotFoundError: No module named 'api.modules.copy_trading'` (that module was renamed/replaced by `copytrader` on this branch).
- `tests/test_engine.py` → `ImportError: cannot import name 'TradingEngine' from api.services.engine` (class renamed/removed).
- `tests/test_risk_manager.py` → `ImportError: cannot import name 'RiskManager' from api.services.risk_manager` (file now exposes module-level `check()`, not a `RiskManager` class).

All three test old, now-removed APIs. If CI runs this exact command it is either currently red or isn't actually gating anything. **Fix (human call, not applied here):** delete the 3 orphaned files (their functionality has no live equivalent to re-target) or rewrite them against the current `check()`/`copytrader`/engine API.

**C2 — 9 further test failures once the 3 broken files are excluded**, all against removed/renamed APIs, not new regressions:
- `tests/test_executor.py` (7 failures): tests call `LiveExecutor(profile={...})` and `PaperExecutor.open_position(...)`, but the live `api/services/executor.py` constructor takes no `profile` arg and `PaperExecutor` only exposes `execute()`/`check_fills()`. The executor was rewritten (post-only resting-order model); tests were not.
- This matches commit `91915ae`'s own note from 2026-09-01: "Test suite unchanged at 64 passed / 9 pre-existing failures" — i.e. these failures are **known and have been sitting untouched for over a month.**

### MEDIUM

**C3 — 2 `tests/test_signals.py` failures look like intentional-behavior-vs-stale-test, not bugs, but touch sizing/ranking directly — route to `@strategy-reviewer` before trusting either side:**
- `test_elapsed_100pct_zeros_kelly` expects `kelly_sizing(..., elapsed_pct=1.0)["kelly_pct"] == 0`. The live function (`api/modules/shared/signals.py:61-63`) deliberately floors the late-auction time-decay at 30% (comment: "reduce sizing late in the auction period (floor at 30%)"), so it returns a small nonzero value by design. The test predates that floor.
- `test_returns_top_3` expects `rank_brackets(probs, prices)` (no `top_n` passed) to cap results at 3; the live default is `top_n: int = 5` (`signals.py:81`). Either the default should be 3 or the test is stale — undetermined without product input.

**C4 — Backtests feeding the shared Google Sheet have no audit trail.** Spot-checked 6 scripts in `scripts/canonical/` (`backtest_noovd.py`, `backtest_noovd_model.py`, `backtest_noovd_xapi.py`, `backtest_noovd_calibrated.py`, `backtest_spike_v2.py`, `backtest_spike_ladder_vs_floor.py`): all correctly read from `_DataMetricPulls/canonical/` and none resample an event stream into bars. But **none emit a `RUN_META` block**, and none has a matching file under `_DataMetricPulls/pacing_backtest/audits/` — per `backtest-auditor.md`, an un-versioned, never-audited backtest is itself a finding. Two of them (`backtest_spike_v2.py`, `backtest_spike_ladder_vs_floor.py`) have their output CSVs actively pushed to the shared Canonical QA Google Sheet (`push_backtest_v2.py`, `push_backtest_results.py`) — i.e. **unaudited numbers are reaching a human-facing sheet**, which is exactly what CLAUDE.md's "Backtest Agents Are The Default" rule forbids ("@backtest-auditor is the ONLY way a backtest result gets trusted... No exceptions"). Worth noting: `spike_trading` isn't even a module on this live branch (L3), so these two in particular may be stale research for a strategy that was never deployed here. Recommend sending both through `@backtest-auditor` before anyone treats the sheet's numbers as real.

### LOW (safe, mechanical — included in this PR)

**C5 — `api/modules/demo/module.py` is dead code.** Its own docstring says `"Delete once S2 lands."` S2 (`s2_basket_hold`) landed long ago and has 67 live positions. Removed in this PR.

**C6 — 3 silent `except Exception: pass` blocks** (`api/services/halt.py:53`, `:60`; `api/services/engine.py:262`) swallow failures in a halt-notify call, a halt log-insert, and a per-row config-parse inside `_active_sports_series`. None guard the money path itself (the halt flag read/write is fail-safe elsewhere in the same file), but silently dropping a halt *notification* failure means an operator could miss that a halt never actually announced itself. Recommend `log.debug`/`log.exception` instead of bare `pass` — **not applied here** (behavior-adjacent, left for human review per the "never touch live trading logic" rule even though it's logging-only).

---

## What was checked and passed

- **Risk gate (`api/services/risk_manager.py`)**: every DB-dependent check fails closed (spread, edge, exposure, drawdown, depth, budget) with no bare `except: pass` on the money path. The dust floor (`signal.notional < 1.0`) is an **absolute** floor, not scaled by any bankroll — and the per-module budget cap correctly reads `modules.budget` via `module_bankroll()`, not the global `bankroll` setting. This is exactly the denominator bug class the task asked me to hunt for; the code's own 2026-07-29 comment confirms it was already found and fixed, and it has not regressed.
- **Risk cap coherence**: single-market (15%) < correlated (30%) < portfolio (50%) of bankroll — correctly nested, no contradictions.
- **Module isolation**: grepped every `api/modules/*/` directory for imports outside its own package / `shared` / `base` — zero cross-module imports found. `BaseModule`'s own docstring states the "sealed" rule and the code honors it.
- No `.single()` usage anywhere in `api/` (no PGRST116 exposure from that pattern).
- No `TODO`/`FIXME` in `api/services/*.py` or any `module.py`.
- No `enabled_wallets` log rows ever (foreign-writer check, full history).

## What could NOT be checked

- A full `@backtest-auditor`-grade pass (THE WALL, maker-fill realism, taker-fee truth, statistical honesty) was **not** run against every backtest script in the repo — only a 6-file spot check (C4). A full sweep is its own task for `@backtest-builder`/`@backtest-auditor`, not this weekly audit.
- `_DataMetricPulls/*_test.py` and `scripts/canonical/07_consistency_test.py` were excluded from the pytest run after the initial full run showed they fail only on this container (`duckdb`/`google` packages not installed, and some reference Windows-only local paths like `C:/Users/darwi/OneDrive/...`) — environment artifacts, not re-verified against the real dev machine, and unrelated to this branch's code correctness.
- Railway deploy logs were not inspected — the `railway` MCP connector failed to connect this session (`ENOENT: railway not in $PATH`). Engine liveness (L1) was inferred from Supabase `logs` Cycle entries only.
