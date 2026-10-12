# Weekly Audit — 2026-10-12

Scope: LIVE bot (Supabase project `xdonwowgqvmtrduikaon`) + CODE on `feat/newbot-step1-skeleton` (HEAD `4820dd3`).
Auditor: scheduled weekly routine. No live trading logic, risk limits, or module behavior was modified. One dead-code removal is called out explicitly at the end.

---

## TL;DR

The bot has been **fully dormant since 2026-09-07** (all 11 modules `status='inactive'`, owner directive "Do NOT auto-revive" after -$1,217 on a $10k paper bench). The engine heartbeat is healthy and nothing live is on fire. The real findings are in the **code**, and they're serious: the test suite's coverage of the three most money-critical files — `risk_manager.py`, `engine.py`, `executor.py` — has been **silently broken at collection** since 2026-07-11, meaning 26 subsequent commits to risk/engine/module code (including 3 risk-manager fixes and 4 engine fixes) shipped with **zero working regression tests**. Separately, the per-module budget cap in the risk gate has a **fail-open gap** that defeats the exact protection it exists to provide, on a plain DB read error.

---

## LIVE FINDINGS (Supabase, last 7 days unless noted)

### CRITICAL — none live. The bot is correctly idle, not broken-and-trading.

### HIGH

**L1. Watchdog false-positive restart trigger, self-resolved (2026-10-12 11:44:40 UTC).**
`logs` row: `"watchdog fixed: engine not cycling (age=Nonem) -> systemctl restart polybot.service"` (severity `warning`), with `metadata.engine_age_min: null`. Cycle logs show **continuous 5-minute cadence** immediately before (11:39:41) and after (11:49:43) — there was no actual outage. The watchdog's engine-age check appears to treat an unreadable/`None` age as "stale" and fire a restart action rather than treating `None` as "can't tell, don't act." Because the bot is currently 0-active-modules, this is low-impact today, but if the same `None`-age condition recurs during live trading it could restart the engine process mid-cycle for no reason. **Recommend:** find the age computation this fed from (watchdog service) and make it skip the restart action when age reads `None`/unparseable instead of treating it as "stale."

### MEDIUM

**L2. Bot has been dormant for 5+ consecutive weekly audits (36 days as of today).**
All 11 `modules` rows are `status='inactive'`. Nine show `inactive_reason='paused_by_owner'` with `inactive_detail`: *"Paused on Sir's instruction 2026-09-07: every module is loss-making on the paper bench (-$1,217 on $10k). Do NOT auto-revive."* Two (`elon_tweets`, `truth_social`) are `decommissioned` placeholder rows (inserted only to stop a `.single()` PGRST116 tripwire — module code already retired). Two (`mirror_trader`, `lp_rewards`) are `dead_thesis`.
7-day `signals`: **0 rows** (newest signal in the whole table is `2026-09-07 18:23:51`, the moment of the pause). 7-day closed `positions`: **0 rows**. This is all consistent with the directive, not a bug — flagging only because this is the 5th straight week of "nothing to report" and it may be time for a human go/no-go: fix-and-revive, retire the losing modules outright, or keep paying for a Railway process that does nothing.

**All-time realized P&L** (the 5 modules that ever traded; everything else has 0 closed positions):
| Module | Realized P&L (all-time) | Closed positions |
|---|---|---|
| S2 Basket-Hold | **-$486.27** | 67 |
| Arb Scanner | **-$456.31** | 32 (1 still open) |
| Copytrader | **-$321.73** | 100 |
| Market Maker | **-$35.36** | 4 |
| Sports Sweep | **-$5.12** | 10 |
| **Total** | **-$1,304.79** | 213 |

Matches the owner's cited "-$1,217" within the gap between that message's timestamp and the current all-time total — no discrepancy worth chasing.

### LOW / INFORMATIONAL (healthy, no action needed)

- **Engine liveness:** newest `logs` `'Cycle: {...}'` row at audit time was **2026-10-12 13:39:43 UTC**, 3 minutes before this audit started — well under the 20-minute staleness bar. Cadence is a steady ~5 minutes across the full 48h window checked (572 cycle rows between 2026-10-10 13:44 and 2026-10-12 13:39).
- **Approval health:** not applicable this week — 0 signals generated (all modules inactive), so there is no approved/rejected ratio to compute. (The "approved ~0 while signals>0" failure mode this check exists to catch cannot occur right now because signal generation itself is off.)
- **Errors:** `logs` severity breakdown for the last 7 days: 2,667 `info`, **2** `warning` (both the single watchdog false-positive above, logged twice — "fixed" + implicit re-check), **0** `error`/`critical`.
- **Foreign writer:** no `logs` rows matching `%enabled_wallets%` — no evidence of a legacy/foreign bot writing to this database.
- **`global_halt`:** `{"halted": false, "reason": "selftest_done"}`, unchanged since 2026-07-23. **`circuit_breaker`:** global breaker last tripped before the 2026-09-07 pause (87 lifetime trips, cooldown already expired); per-module breakers for Copytrader/S2/Arb Scanner all show expired cooldowns too. Nothing currently tripped-and-stuck.

---

## CODE FINDINGS

### CRITICAL

**C1. The test suite for the three most money-critical modules has been silently broken since 2026-07-11 — 26 commits of risk/engine changes shipped with no passing tests covering them.**

Running `python -m pytest -q` (after installing `requirements.txt` — the repo's pinned deps were not pre-installed in this environment) produces **18 collection errors**, three of which are the actual trading pipeline:

- `tests/test_risk_manager.py:4` — `from api.services.risk_manager import RiskManager, Signal` → `ImportError: cannot import name 'RiskManager'`. The real module (`api/services/risk_manager.py`) was refactored at some point to a plain `check(signal, breaker_tripped)` function plus `Signal`/`RiskVerdict` dataclasses — there is no `RiskManager` class anymore. Every test in this file (circuit breaker, exposure caps, loss limits — the literal "15 risk checks" CLAUDE.md calls non-negotiable) has not executed in at least 26 commits.
- `tests/test_engine.py:3` — `from api.services.engine import TradingEngine` → `ImportError: cannot import name 'TradingEngine'`. Same pattern for the engine orchestration layer.
- `tests/test_copy_trading.py:16` — `from api.modules.copy_trading.decision import (...)` → `ModuleNotFoundError: No module named 'api.modules.copy_trading'`. This module (and its spec, `COPY_TRADING_MODULE_SPEC.md`) no longer exists anywhere in the repo; it was superseded by the current `api/modules/copytrader/`. The file tests **5 "mandatory acceptance cases"** per its own docstring — dedupe of `whale_trade_id`, a staleness gate, a per-trade sizing cap, a daily-loss circuit, and a cold-start drop of stale trades. None of those five safety properties are currently verified against the module that actually runs today (`copytrader`).

Evidence of the drift window: all four broken test files were last touched in commit `77e9da4` (**2026-07-11**). Since then, `api/services/` and `api/modules/` together received **26 commits** through `4820dd3` (latest, includes work up to **2026-09-03**) — among them `dd077cc` (per-module budget cap), `0f23f10` (spread_tol override), `c762636` (dust-floor fix), and 4 separate `engine.py` fixes. Every one of those risk/engine changes landed with the harness that's supposed to catch a regression unable to even import.

**Why this matters:** CLAUDE.md's non-negotiable rule is "ALWAYS run all 15 risk checks before order placement." There is currently no automated way to prove that's true. This audit's own `python -m pytest -q` run — the exact command CLAUDE.md asks for — cannot verify the risk gate at all; it can only report that it doesn't collect.

**Fix (recommend, not applied):** rewrite the three test files against the current function-based `risk_manager.check()` / class-free `engine` API, and either port the 5 copy-trading acceptance tests onto `copytrader` or write new ones — this should happen before any module is revived.

### HIGH

**C2. Per-module budget cap fails OPEN on a DB error, not closed — defeats the exact protection it exists to provide.**

`api/modules/shared/config_store.py::module_bankroll()`:
```python
def module_bankroll(module_id: str) -> float:
    try:
        res = (get_supabase().table("modules").select("budget")
               .eq("id", module_id).limit(1).execute())
        if res.data and res.data[0].get("budget") is not None:
            return float(res.data[0]["budget"])
    except Exception:
        log.exception("budget read failed for %s", module_id)
    return get_settings().bankroll   # <-- falls back to the GLOBAL bankroll
```
This return value feeds directly into `risk_manager.check()`'s per-module exposure cap:
```python
mod_budget = module_bankroll(signal.module_id)       # risk_manager.py:223
mod_now = _module_exposure(sb, signal.module_id)
if signal.notional + mod_now > mod_budget:            # risk_manager.py:225
    return RiskVerdict(False, f"module_budget_cap_{mod_budget:.0f}")
```
On any transient Supabase read failure (or a module whose `budget` is NULL), `module_bankroll()` doesn't raise — it swallows the exception and hands back the **full global bankroll** as if that were the module's own budget. The per-module cap exists specifically to stop one strategy from monopolizing the book — it's the fix for the documented **2026-07-22 incident where LP Rewards held 65% of the portfolio**, and sits right next to the dust-floor fix (`c762636`) for the same class of bug (wrong denominator / silent fallback to the global number). Here the fallback isn't even wrong-denominator math — it's a complete bypass: the cap becomes "the whole bankroll," i.e. no cap, during exactly the kind of DB hiccup `risk_manager.check()`'s surrounding `try/except -> fail closed` (lines 192–241) was built to catch, except this failure happens *inside* `module_bankroll()` and never reaches that wrapper.

**Fix (recommend, not applied):** let `module_bankroll()` raise on a DB error instead of catching it (or return `None`/a sentinel and have `risk_manager.check()` treat that as `db_error` → reject), so this failure path is caught by the fail-closed wrapper that already exists one call up.

**C3. `test_executor.py` — 7/10 tests fail; the paper and live order-execution path has no passing coverage.**

Same staleness pattern as C1, one layer down:
- 4× `TestPaperExecutor` tests fail with `AttributeError: <module 'api.services.executor'> does not have the attribute 'open_position'` — they `@patch("api.services.executor.open_position")`, a function that doesn't exist in the current `executor.py`.
- `TestLiveExecutor.test_missing_credentials_raises` / `test_clob_failure_marks_rejected` fail with `TypeError: LiveExecutor.__init__() got an unexpected keyword argument 'profile'` — the constructor signature changed.
- `TestLiveExecutor.test_gtc_order_type` fails the same `open_position`-attribute way.

Net: **0 of the executor's buy/sell/order-type tests currently pass.** (Order placement code itself looks correct on manual read — `executor.py:77` sets `"post_only": True, "order_type": "GTC"`, consistent with the "ALWAYS limit orders, NEVER market orders" rule — but that's from reading the source, not from a passing test proving it.)

### MEDIUM

**C4. 18 collection errors block a clean `pytest` run; real future test breakage could hide behind this wall.**
Beyond C1/C3, 13 more files fail to even collect, for two unrelated reasons:
- Hardcoded Windows dev-machine paths baked into `_DataMetricPulls/pacing_backtest/*.py` (`divergence_test.py`, `regime_test.py`, `run_overlay_test.py`, `test_conformance.py`, etc.): `FileNotFoundError: ... 'C:\\Users\\darwi\\OneDrive\\Desktop\\Claude Code\\Personal\\PolyMarket_Bot/...'`. These are research scripts picked up by pytest's default discovery (`test_*.py` glob) that were never meant to run outside the owner's Windows machine.
- Missing optional deps not pinned in `requirements.txt`: `duckdb` (`test_arb_maker.py`, `test_beat_market.py`, `test_done_edge.py`), `google-auth` (`scripts/canonical/07_consistency_test.py`).
This audit worked around it with `--ignore` per file to reach the real suite; CI presumably does the same or also fails outright. **Recommend:** either move these research scripts out of pytest's discovery path (rename off the `test_*` pattern, or add an `testpaths =` / `norecursedirs` in a `pytest.ini`/`pyproject.toml`) or accept the noise consciously — but right now a genuinely new broken test anywhere could land invisibly inside 18 pre-existing red herrings.

**C5. Two `test_signals.py` failures — stale tests, not current bugs, but worth a conscious fix.**
- `test_elapsed_100pct_zeros_kelly` expects `kelly_sizing(..., elapsed_pct=1.0)["kelly_pct"] == 0`; current code (`api/modules/shared/signals.py:61-63`) has `time_decay = max(1.0 - elapsed_pct, 0.30)` — a deliberate 30% sizing floor late in an auction, added after this test was written. The test is checking old behavior, not catching a regression.
- `test_returns_top_3` expects `rank_brackets(probs, prices)` to cap at 3 results by default; the current signature is `rank_brackets(..., top_n: int = 5)` — default changed from 3 to 5 without the test being updated.
Neither looks like a live bug. Recommend updating both assertions to match the current intended behavior (or, for the Kelly floor, have someone confirm a 30% floor at 100%-elapsed is still wanted — that's a strategy question, not a code one, so it's for `@strategy-reviewer` / Sir, not this audit to decide).

### LOW

**C6. Module isolation — PASS, no violation found.** Every `api/modules/*/module.py` imports only `api.modules.base` and (where needed) `api.modules.shared`; no cross-module imports exist anywhere in `api/modules/`. Matches `MODULE_ARCHITECTURE.md` + CLAUDE.md rule 2.

**C7. No hardcoded secrets found** in a scan of `api/` for inline API keys/secrets/passphrases/private keys.

**C8. Silent-failure patterns reviewed — mostly fine, one already-correct pattern worth noting as a positive example.** `api/services/halt.py::is_halted()` explicitly fails **SAFE** on a read error (`except Exception: ... return True`, i.e. "treat unreadable as halted") — this is the right pattern, and a good contrast to C2. The only bare `except Exception: pass` blocks found (`halt.py:53-54,60-61`, `engine.py:262-263`) are all genuinely best-effort (notification send, log insert, one sports-series config lookup) and don't gate money decisions. No `.single()` usage found anywhere (the PGRST116 tripwire CLAUDE.md's `elon_tweets`/`truth_social` decommission comment references appears to have been fully designed around). No TODO/FIXME found in `api/services/` or `api/modules/`.

**C9. Backtest audit trail is stale, consistent with the pause — not actionable now.** Newest file in `_DataMetricPulls/pacing_backtest/audits/` is dated 2026-07-31; nothing in the ~10 weeks since (matches: no backtest work has happened since before the 2026-09-07 pause). Only 10 of 133 scripts under `_DataMetricPulls/pacing_backtest/` reference the `RUN_META` emitter — most predate that requirement (added in `1a09866`, after `77e9da4`). No current violation to report; flagging only so that whenever backtest work resumes, new scripts go through `@backtest-builder` and emit `RUN_META` per CLAUDE.md, rather than reusing an old un-instrumented script as a template.

---

## What was checked and passed clean
Risk gate fail-closed behavior (manual read, all paths except C2); limit-only / no-market-order order placement; module architecture boundaries; hardcoded-secret scan; `global_halt` / circuit-breaker live state; foreign-writer check; engine heartbeat; 70 of 79 collectible `tests/` cases actually pass (pacing, projection, windows-slug, most of signals).

## What could NOT be checked
Nothing in `_DataMetricPulls/pacing_backtest/` was re-run (no backtest work is in flight; see C9). Railway deploy logs/dashboard were not inspected — the `railway` MCP tool failed to connect this session (`ENOENT: Executable not found in $PATH`); this audit relied on Supabase + git only.

---

## Dead-code removal applied in this PR (LOW-RISK, per audit scope)
Deleted `tests/test_copy_trading.py`. It imports `api.modules.copy_trading.decision`, a module and spec (`COPY_TRADING_MODULE_SPEC.md`) that no longer exist anywhere in the repo — it has not been collectible by pytest since at least 2026-07-11 and tests nothing that currently runs. This is a pure dead-code removal (no trading logic, risk limit, or module behavior touched); the 5 acceptance properties it describes (dedupe, staleness gate, per-trade cap, daily-loss circuit, cold-start drop) are called out in **C1** as a recommendation to re-verify against the current `copytrader` module, not closed out by this deletion.
