# Weekly Audit — 2026-08-17

Scope: live production branch `feat/newbot-step1-skeleton` (the "Step 1 skeleton" rewrite — NOT `master`, which is the retired old bot). Live data source: Supabase project `xdonwowgqvmtrduikaon`.

**Top line: the LIVE portion of this audit could not run.** Supabase was unreachable for the entire session (see CRITICAL-1). All CODE findings below come from direct manual review — the three automated QA sub-agents (risk-auditor, qa-architecture-quality, qa-code-quality) each failed twice in a row on Anthropic API overload (`529`) and never completed; findings they would normally surface may not be captured here. Recommend re-running this audit (or just the LIVE half) once Supabase connectivity and API capacity are confirmed healthy.

---

## CRITICAL

### C1 — Supabase project unreachable for the entire audit; LIVE section could not be produced
Every query against project `xdonwowgqvmtrduikaon` timed out or errored, across ~20 attempts spanning roughly 30 minutes:
- `execute_sql` (`select 1;`, `select now();`, a real `signals` count query) — `Connection terminated due to connection timeout`, every attempt.
- `list_tables` — same timeout.
- `get_advisors` — `Failed to run project user check: Connection terminated due to connection timeout`.
- `query_logs` (ClickHouse-backed unified logs, a separate backend from Postgres) — `Backend error! Retry your query.`

By contrast, `get_project` returned instantly with `status: "ACTIVE_HEALTHY"`, and `list_organizations` succeeded — so the MCP transport and Supabase's control-plane API are fine; it is specifically the project's **database/log query path** that is hanging or refusing connections.

This matches the failure signature already documented in this repo's own `CLAUDE.md` ("Retention + Parquet Archive" section): *"Supabase free tier choked on Disk IO 2026-05-22 (GoTrue auth hung, dashboard login broke)."* Given retention policies were added specifically to prevent a recurrence, this looks like the same class of incident happening again, not a one-off network blip.

**Could not verify:** signal approval health / rejection-reason breakdown, per-module realized P&L (7-day and all-time), module health / inactive-reason correctness, engine liveness (newest `Cycle:` log timestamp), or the foreign-writer check (`%enabled_wallets%` in `logs`).

**Recommendation:** check the Supabase project directly (dashboard, or `db.xdonwowgqvmtrduikaon.supabase.co` reachability) outside of this MCP path — if the live bot is also hitting this same timeout on its own Supabase calls, every risk-gate check that depends on a DB read (which is all of them — see risk_manager.py review below) is failing closed right now, meaning **the bot may currently be rejecting 100% of entry signals**. That would look identical to the "approval health" failure mode this audit was asked to check for, just caused by infra instead of a gating bug. Worth an immediate manual check independent of this report.

---

## HIGH

### H1 — `module_bankroll()` fails OPEN on DB error, contradicting risk_manager's own fail-closed doctrine
`api/modules/shared/config_store.py:24-36`:
```python
def module_bankroll(module_id: str) -> float:
    try:
        res = (get_supabase().table("modules").select("budget")
               .eq("id", module_id).limit(1).execute())
        if res.data and res.data[0].get("budget") is not None:
            return float(res.data[0]["budget"])
    except Exception:
        log.exception("budget read failed for %s", module_id)
    return get_settings().bankroll
```
On any DB error (or a module row with `budget` unset/null), this silently swallows the exception and returns the **full global bankroll** — not a small/conservative default, not a re-raise. It's called from `risk_manager.check()` at `api/services/risk_manager.py:222-226` inside the gate's own `try:` block, but because `module_bankroll()` catches its exception *internally*, the failure never reaches risk_manager's outer `except Exception` fail-closed handler (`risk_manager.py:239-241`) — the gate sees a *successful* (if wrong) budget value, not a DB error.

Effect: if the `modules.budget` read fails or the row's `budget` is null, the per-module budget cap (`mod_budget` at `risk_manager.py:225`) silently becomes the entire portfolio bankroll for that module. That is exactly the failure mode `_module_exposure()`'s own docstring says this cap exists to prevent: *"LP Rewards held 65% of the book, 2026-07-22."* It also directly contradicts the doctrine stated at the top of `risk_manager.py`: *"ALL checks FAIL CLOSED: any DB error, missing price, or missing data rejects the signal."*

**Fix direction (not applied — recommendation only):** either re-raise from `module_bankroll()` so the outer fail-closed handler catches it, or fall back to something bounded (e.g. `0.0`, forcing `module_budget_cap` to reject) rather than the unbounded global bankroll.

### H2 — `MODULE_ARCHITECTURE.md` documents a module set that no longer exists
`_ImportantConfigFiles/MODULE_ARCHITECTURE.md` — the doc `CLAUDE.md` names as "the full guide" for module rules — describes `truth_social/`, `elon_tweets/`, `spike_trading/`, and `copy_trading/` as the module directories, with example files like `parquet_history.py`, `lunarcrush.py`, `decision.py` under `spike_trading/`.

None of those directories exist on `feat/newbot-step1-skeleton`. The actual `api/modules/` contents are: `arb_scanner`, `copytrader`, `demo`, `elon_late_arb`, `elon_reversion`, `lp_rewards`, `market_maker`, `mirror_trader`, `s2_basket_hold`, `sports_sweep`, `shared`. This is a full-repo rewrite (the "Step 1 skeleton", commit `06e64a3`) that never got the architecture doc updated to match. Anyone — human or agent — following this doc to add a module or verify isolation is reading rules for a system that was replaced.

---

## MEDIUM

### M1 — CLAUDE.md's own "always surface first" Spike Trading section refers to a retired module
`CLAUDE.md`'s `⭐ SPIKE TRADING` section is marked *"When user asks 'which brackets should Spike trade,' ALWAYS surface this first."* Grepped `api/` and `web/` for `spike_trading`/`SpikeTrading`: **zero hits**. The module does not exist anywhere in the live code on this branch — it was part of the pre-rewrite bot. Any assistant obeying this instruction today would surface bracket-recommendation guidance for a strategy that isn't running. This section needs either restoring (if Spike is coming back) or removing/marking retired, same root cause as H2.

### M2 — Test suite is ~1/6 broken, all confirmed stale (pre-rewrite), but currently masks real regressions
`python -m pytest -q` on the full repo aborts with **13 collection errors** before running anything. Narrowing to `tests/`, 3 files fail to even import:
- `tests/test_risk_manager.py:4` — `from api.services.risk_manager import RiskManager, Signal` — no `RiskManager` class exists; `risk_manager.py` only exposes a `check()` function and `Signal` dataclass.
- `tests/test_engine.py:3` — `from api.services.engine import TradingEngine` — no such class.
- `tests/test_copy_trading.py:16` — `from api.modules.copy_trading.decision import ...` — the real directory is `api/modules/copytrader/`, not `copy_trading`.

Excluding those three, `python -m pytest tests/ -q --ignore=tests/test_risk_manager.py --ignore=tests/test_engine.py --ignore=tests/test_copy_trading.py` runs **73 tests: 64 passed, 9 failed.** All 9 failures were manually verified as stale-test drift, not real bugs:
- `test_executor.py` — `LiveExecutor(profile={...})` and `patch("api.services.executor.open_position")`: current `LiveExecutor.__init__(self)` takes zero args (`executor.py:41`), and there is no top-level `open_position` in the module — signature changed in the rewrite, test wasn't updated.
- `test_signals.py::test_elapsed_100pct_zeros_kelly` — asserts `kelly_pct == 0` at `elapsed_pct=1.0`; current `kelly_sizing()` (`api/modules/shared/signals.py:60-63`) intentionally floors the time-decay at 30%, per its own comment (`"Time-weighted Kelly: reduce sizing late in the auction period (floor at 30%)"`) — the 0.0171 the test sees is correct current behavior.
- `test_signals.py::test_returns_top_3` — asserts `len(result) <= 3`; `rank_brackets()`'s default is `top_n: int = 5` (`signals.py:81`), not 3.

None of these are money-path bugs. But a suite that's red-by-default trains people to ignore `pytest` output, and 3 files erroring at collection means **the entire suite silently doesn't run** on a bare `pytest -q` — a genuine regression introduced tomorrow in `risk_manager.check()`, `executor.py`, or `signals.py` would not be caught by CI/local runs unless someone already knows to scope around the broken files. Recommend deleting or rewriting the 3 retired-API test files and updating the 9 stale assertions as a follow-up (flagged here, not touched by this audit per its low-risk-only-fix constraint — deleting whole test files isn't "typo/dead-code" scale).

### M2a — RUN_META compliance is effectively zero across the backtest suite
The `backtest-auditor` agent (and commits `1a09866`/`fb54671`/`ee35342`) built a `RUN_META` footer system specifically so backtest compliance ("locked model version, scope, fill model") is machine-checkable instead of grepped by hand. Checked: of the 54 `.py` scripts under `_DataMetricPulls/pacing_backtest/`, exactly **one** file references `emit_run_meta`/`RUN_META` — `run_meta.py` itself (its own definition). Not a single actual backtest script, including the currently-trusted exemplars (`real_fill_v5.py`, `bracket_hit_backtest.py`, `trade_sim.py`), emits the footer. Per the auditor's own rule, *"A backtest with NO RUN_META is a class-C finding in itself."* Spot-checked `real_fill_v5.py` for THE WALL compliance directly: no `resample(`/`rolling(center=True)` lookahead pattern found — its one `.rolling(4, min_periods=2).min()` call is backward-looking/causal, so no fatal finding there — but its provenance is still unverifiable by the automated gate because it never wires in RUN_META.

---

## LOW

### L1 — Two silent `except Exception: pass` in `api/services/halt.py`
`halt.py:53` (Slack notify failure inside `set_halt()`) and `halt.py:60` (audit-log insert failure, also inside `set_halt()`) both swallow the exception with no logging at all — every other `except` in this file (and in the rest of `api/services/`, confirmed by a full grep) calls `log.exception(...)`. Neither is money-critical (one's a Slack ping, one's an audit-trail write for a halt that already took effect), but a persistently-failing halt audit log would be invisible. Minor — add a `log.debug`/`log.warning`.

---

## What was checked and passed

- **risk_manager.py fail-closed behavior** — read in full. Every DB-dependent gate (`_open_exposure`, `_module_exposure`, `_correlated_exposure`, `_realized_pnl_since`, `_drawdown_exceeded`) either raises (caught by the outer fail-closed `except Exception` at `check():239-241`) or is itself defensive; `_book_depth_shares` explicitly returns `None` on any failure and the caller treats `None` depth as a reject. Confirmed correct **except** for H1 above.
- **Dust floor fix verified** — `risk_manager.py:189` (`signal.notional < 1.0`) is now an absolute $1 floor, not scaled by global bankroll. Commit `c762636` (`fix(risk): decouple dust floor from global bankroll`) is correctly reflected in current code. No other per-order gate found scaled against the wrong denominator besides H1 (which is a different code path — a fallback default, not a scaling bug).
- **Limit-only orders** — no evidence of market-order placement found in the reviewed executor/risk paths; `Signal.price` is mandatory and validated (`price <= 0 or price >= 1` rejected) before any sizing happens.
- **Cross-module import isolation** — grepped every `from api.modules.<name>.` import across `api/`. All cross-module references route through `api.modules.shared.*` (config_store, tweet_count, canonical_data, parquet_archive). No module imports another module's internals. `BaseModule` (`api/modules/base.py`) explicitly documents the sealing rule and provides `get_handle()`/`get_platform()`/`get_display_keywords()`/`get_config()` as the sanctioned API surface.
- **No hardcoded module-name branching found** in engine/router code. One `"elon" in fams` check exists in `api/modules/market_maker/data.py:109`, but it's matching against the market_maker module's *own* per-module config field (`cfg["markets"]`), not engine routing — not a violation of the rule.
- **Module file structure** — every module directory (`arb_scanner`, `copytrader`, `demo`, `elon_late_arb`, `elon_reversion`, `lp_rewards`, `market_maker`, `mirror_trader`, `s2_basket_hold`, `sports_sweep`) has `module.py` + `data.py` + `module_config.py` + `__init__.py`, matching the required structure.
- **No `.single()` calls anywhere in `api/`** — the PGRST116-on-empty-result footgun this audit was asked to check for isn't present at all.
- **No TODO/FIXME/XXX/HACK in `api/services/`.**
- **WebSocket exponential backoff** — confirmed correctly implemented with a stall watchdog in both `api/services/fills.py` (`UserChannelStream`, backoff capped at 60s) and `api/services/tweet_stream.py` (`TweetStream`, backoff capped at 30s).
- **No hardcoded API keys** found in the reviewed money-path files (all credentials read via `get_settings()`/env).

## What could not be checked

- All 7-day LIVE metrics (approval health, P&L, module health, engine liveness, foreign-writer check) — blocked by C1.
- Full risk-auditor / qa-architecture-quality / qa-code-quality deep sweeps — both automated retry attempts on each failed on API overload (`529`); this report substitutes a direct manual review of the same rule set but is not as exhaustive as those agents' normal file-by-file coverage (e.g. dead/orphan-code detection across the whole repo, not just the money paths reviewed here).
- Executor/order-placement code was read for structure but not exercised — no paper/live trade was placed as part of this audit (out of scope: this is a static + DB audit, not `qa-real-trade`).

---
_Generated by an automated weekly audit routine._
