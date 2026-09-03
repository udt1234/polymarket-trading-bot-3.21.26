# Weekly Audit — 2026-07-29

Scope: live branch `feat/newbot-step1-skeleton` (HEAD `c762636`) + Supabase project `xdonwowgqvmtrduikaon`, last 7 days unless noted. All timestamps UTC. DB `now()` at audit time: `2026-07-29 19:00:56Z`.

No live trading logic, risk limits, or module behavior was changed. This PR is the report only.

---

## LIVE FINDINGS (Supabase)

### CRITICAL

**1. The retired old bot (branch `master`) is still running in production against the shared Supabase DB, with a live wallet key wired up — ~6 weeks after teardown was started and left unfinished.**

- `logs` shows a `decision`-type row every ~5 minutes reading `Cycle: enabled_wallets=0 shadow_mode=False`, most recently at `2026-07-29 18:59:05Z` — 2 minutes before this audit began.
- That exact string only exists at `api/modules/copy_trading/module.py:190` on `origin/master` (module `copy_trading`, not `copytrader`). It does not exist anywhere on the live `feat/newbot-step1-skeleton` branch — grepping the live tree for `enabled_wallets` returns zero hits. This is the retired bot, not the current one.
- `HANDOFF_DELETE_BOT.md` and `TEARDOWN_NOTES.md` (both dated 2026-06-15, committed at repo root) document that the user began tearing this down over 6 weeks ago: Supabase tables were truncated, but Railway service deletion ("Bot-API (Fast API)", "Bot-Dashboard", `cron-spike-alert`, `cron-anchor-alert`) was explicitly marked `⏳ NOT done yet`. TEARDOWN_NOTES.md warns in its own words: *"The Railway bot is STILL RUNNING... it will start re-writing rows... The DB will NOT stay clean until you stop/delete the Railway service."*
- TEARDOWN_NOTES.md also records that this same service had, prior to teardown, placed **155 LIVE orders** (`orders.executor` split: 155 live / 283 paper) using the real `POLYMARKET_PRIVATE_KEY` — i.e. this is not a paper-only leftover, it is a service that has traded real funds before and still has the credentials to do so again.
- Current state is a no-op (`enabled_wallets=0`, so `copy_trading` has no wallets configured to mirror) — but `shadow_mode=False` means the instant a wallet is added to its config it will attempt to trade live. It shares no risk-state settings keys with the new bot (checked: master's circuit breaker key is `circuit_breaker_state`, distinct from the new bot's `circuit_breaker`; master has no `global_halt`/`equity_peak` usage), so it is not currently corrupting the new bot's risk gate — but it is an unmonitored, credentialed, live-capable process nobody is watching, and it has been silently consuming Railway compute + Supabase log/settings-write volume for 6+ weeks past its intended shutdown date.

**Recommendation:** finish `HANDOFF_DELETE_BOT.md` step 2 — verify the Polymarket wallet balance/positions first, then delete the Railway "PolyMarket Bot" project (all 4 services). This is an operator action (Railway dashboard / API token), not a code change, and is time-sensitive given the live-order history.

---

### HIGH

**2. Approval health is not itself broken, but the circuit breaker is currently tripped and dominates rejections for the two modules that are actually losing money.** `settings.circuit_breaker`: `trips: 43` (all-time), `cooldown_until: 2026-07-29T19:29:34Z` — still ~29 min of cooldown remaining as of audit time (`db_now` 19:00:56Z). `watchdog_state.breaker.bad = true` (last alert 18:35Z today). Circuit-breaker rejections this week: Arb Scanner 2020, Copytrader 366, Market Maker 361, S2 Basket-Hold 69, Sports Sweep 45. Approval rates across all 7 active modules are low (0.2%–14%) but the dominant rejection reasons are legitimate gates (`stake_below_floor`, `portfolio_cap`, `spread_*>tol_*`, `circuit_breaker`) rather than one gate silently eating everything — this is NOT the "approved ≈ 0 while signals > 0" hidden-bug pattern from the class this audit specifically watches for. No action needed here beyond #3.

**3. Two modules are in a real, sustained losing streak over the last 7 days:**
| Module | 7d realized P&L | 7d closes | All-time realized P&L | All-time closes |
|---|---|---|---|---|
| Copytrader | **-$42.32** | 17 | -$42.32 | 17 |
| S2 Basket-Hold | **-$29.55** | 22 | -$37.85 | 29 |
| Arb Scanner | -$1.78 | 3 | -$1.78 | 3 |
| Sports Sweep | — (0 closes 7d) | 0 | +$0.32 | 1 |
| Market Maker, Elon Reversion, Elon Late Arb | no closed positions yet | — | — | — |

Copytrader has never had a winning week; S2 Basket-Hold's losses accelerated this week (-$29.55 of its -$37.85 all-time total came in the last 7 days). Both are paper-mode, so no real capital is at risk, but recommend a strategy-reviewer pass on both before any live promotion.

**4. `api/services/engine.py` hardcodes the module name `"sports_sweep"` in three places — a direct violation of CLAUDE.md's non-negotiable "Engine/router code MUST NOT hardcode module names" rule:** lines 188 (`from api.modules.sports_sweep import data as sports_data`), 238 (`self.registry.get("sports_sweep")`), 242 (`.eq("strategy", "sports_sweep")`). This reaches into one module's private `data.py` and special-cases it in the engine instead of going through a `BaseModule` method. Fix: add a `get_quote_tokens()` (or equivalent) method to `BaseModule` that every module implements, and have the engine call that instead.

**5. `for_db_row()` module-resolution fallback can silently misroute a `modules` row to the wrong strategy class** (`api/modules/__init__.py:56-60`). Primary match is on the `strategy` column (correct), but if that's ever blank/stale it falls back to substring-matching each module's declared "display keywords" against the row's display name, in alphabetical registry-discovery order. Verified overlaps: `"Elon Late Arb"` → matches `arb_scanner`'s bare `"arb"` keyword instead of `elon_late_arb`; `"Whale Mirror"` → matches `copytrader`'s `"whale"` keyword instead of `mirror_trader`; `"Liquidity MM"` → matches `lp_rewards`'s generic `"liquidity"` keyword instead of `market_maker`. A row misrouted this way gets evaluated, sized, and risk-checked under the wrong module's thesis/config — and could resurrect logic for `lp_rewards`/`mirror_trader`, both currently `inactive`/`dead_thesis`. Fix: delete the keyword fallback; require an exact `strategy` match and return `None` (skip the row, log it) otherwise.

**6. Three test files fail to *collect* on the live branch — the two most safety-critical modules (risk gate, engine) have no verified passing test coverage against their current shape:**
- `tests/test_risk_manager.py` imports `RiskManager` (a class) from `api.services.risk_manager` — that file now exports a function `check()`, no such class exists.
- `tests/test_engine.py` imports `TradingEngine` from `api.services.engine` — no such name exists.
- `tests/test_copy_trading.py` imports from `api.modules.copy_trading` — that package doesn't exist on this branch (it's `api.modules.copytrader`, a different, newer module).

`python -m pytest -q` cannot complete collection at all with these present (`13 errors during collection`, most of the rest being pre-existing `_DataMetricPulls/pacing_backtest/*_test.py` scripts that read a hardcoded Windows path — see LOW #16). Running `tests/` alone (excluding these 3 files): **64 passed, 9 failed.** The 9 failures are all stale-signature issues, not live bugs:
- 7 in `tests/test_executor.py` call `LiveExecutor(profile={...})` / `PaperExecutor(...)` with a constructor shape the current `api/services/executor.py` no longer accepts.
- `tests/test_signals.py::test_returns_top_3` asserts `rank_brackets()` returns ≤3 items; the live function's default is `top_n=5` (`api/modules/shared/signals.py:81`) — this is a stale assertion, not a bracket-limit regression.
- `tests/test_signals.py::test_elapsed_100pct_zeros_kelly` expects `kelly_pct == 0` at 100% elapsed; live code returns `0.0171`. Worth a strategy-reviewer look — could be an intentional floor added later, or a real edge case.

**Recommendation:** update or delete the 3 non-collecting files and the 7 `test_executor.py` cases to match current constructors; confirm the Kelly-at-100%-elapsed behavior is intentional.

---

### MEDIUM

**7. Dead code — 6 unimported files under `api/modules/shared/` (~678 LOC):** `feed_guard.py`, `l2_history.py`, `pacing.py`, `parquet_archive.py`, `projection.py`, `signals.py` have zero importers anywhere in `api/` or `scripts/`. Notably, CLAUDE.md documents `parquet_archive.py` as "already-wired" into `price_timing.py` and `whale_snapshot.py` — **neither of those files exists on this branch.** The CLAUDE.md Retention/Parquet-Archive section describes a state that predates the current module layout; either re-wire the archive reader into the modules that need >live-window data, or update CLAUDE.md to stop claiming it's wired.

**8. Two scripts import a deleted package and are dead on invocation:** `scripts/backfill_truth_social.py:32` and `scripts/verify_post_count.py:22` do `from api.modules.truth_social.truthsocial_direct import ...`; `api/modules/truth_social/` was deleted in `06e64a3`. Confirmed `ModuleNotFoundError` if run today.

**9. `api/services/risk_manager.py` shows hotfix layering: 7 of the last ~60 commits are `fix(risk):` patches to this single file with no intervening refactor**, and `check()` has grown to 111 lines (143–253) covering ~15 sequential gates. Each individual fix reads correct (verified: the dust floor is now an absolute $1, not scaled by global bankroll — see "not found" note below); the file itself is due for a refactor into a gate list/pipeline before the next hotfix lands on top.

**10. `for_db_row()` history check — no wrong-denominator gate found.** Went looking for the exact bug class this audit calls out ("per-order gate scaled by the wrong denominator, e.g. dust floor scaled by global bankroll not module budget") since it's explicitly named in the audit brief and was flagged in this repo before. **Already fixed**, and recently: commit `c762636` ("decouple dust floor from global bankroll") changed the dust floor at `risk_manager.py:189` to a flat `signal.notional < 1.0` (absolute $1 CLOB minimum), replacing whatever previously scaled it against `s.bankroll`. `module_bankroll()` (`api/modules/shared/config_store.py:24-36`) correctly reads each module's own `modules.budget` row, falling back to the global bankroll only when a module's budget is unset — the per-module cap at `risk_manager.py:225` (`module_budget_cap_{mod_budget}`) uses the right denominator. No other gate in `check()` scales a per-order threshold by the wrong pool. Confirming-clean, not a new finding — but since the brief specifically asked, recorded here for the record.

**11. Historical (resolved) — Mirror Trader and LP Rewards placed 127 real orders (~$2,429 notional) between 2026-07-22 and 2026-07-24, all subsequently cancelled with zero fills**, in the window before both were flipped to `inactive`/`dead_thesis`. `engine.py:63` correctly excludes `status = inactive` modules from evaluation today, and no signals have been generated for either module since 2026-07-24 — so this is not an active bug, just confirmation that the status flip landed at the right time and no capital was ever at risk (paper mode, orders cancelled not filled).

---

### LOW

**12. `api/services/engine.py:249` — bare `except Exception: pass` silently drops a module's `series_ids` config on failure**, shrinking paper-fill coverage for that module's cycle with no log line. Paper-only impact today, but masks config breakage.

**13. `api/services/halt.py:53,60` — `except Exception: pass` swallows notify/audit-log failures during a global halt.** The halt flag itself is still set (line 38 runs first, so trading does stop), but a halt that fails to alert Slack or write a `logs` row is invisible to whoever's on call.

**14. `api/modules/demo/module_config.py` is a stub** (`DEFAULT_CONFIG = {}`, no real loader/saver; `save_config` is a no-op) that bypasses `config_store` entirely, and its own docstring says "Delete once S2 lands" — S2 Basket-Hold has landed. Candidate for deletion.

**15. Doc drift: both `_ImportantConfigFiles/MODULE_ARCHITECTURE.md` and `ARCHITECTURE.md` describe module directories that no longer exist** (`truth_social/`, `elon_tweets/`, `spike_trading/`, `copy_trading/`) and list ~10 `BaseModule` methods (`get_auction_title_filter`, `count_posts_in_window`, `get_buy_order_ttl_hours`, `get_strategy_metadata`, `get_market_universe`, `get_brackets`, `archive_resolved_auction`) that are absent from the live `api/modules/base.py`. The 10 actual current modules (`arb_scanner`, `copytrader`, `demo`, `elon_late_arb`, `elon_reversion`, `lp_rewards`, `market_maker`, `mirror_trader`, `s2_basket_hold`, `sports_sweep`) are undocumented there.

**16. `risk_manager.py:287` `aggregate_price_ceiling_ok()` has no caller anywhere in the repo** — a documented D4 aggregate-price-ceiling guard that never actually runs. Either wire it in where cross-bracket exposure is decided, or remove it so it stops reading as coverage that doesn't exist.

**17. Several `_DataMetricPulls/pacing_backtest/*_test.py` and one `_DataMetricPulls/elon_schedule_analysis/test_tz_hypothesis.py` file hardcode an absolute Windows path** (`C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot\...`) to load their input parquet, so they can only ever run on the original author's machine — they fail collection in this (and presumably any CI) environment. These aren't part of the live trading path, but they block a clean `pytest` run from this branch's root and should either read from `_DataMetricPulls/canonical/` per CLAUDE.md's canonical-data rule, or be excluded from default pytest collection (e.g. via `testpaths` in `pytest.ini`/`pyproject.toml` scoped to `tests/`).

**18. No backtest scripts changed in the last 7 days** (only backtest-*tooling* — the RUN_META emitter and the backtest-auditor agent itself — landed this week; `git log --since=7d` shows nothing under `backtest/`, `_DataMetricPulls/pacing_backtest/`, `_DataMetricPulls/foretest/`). No new P&L/ROI claim exists to run a full `backtest-auditor` pass against this cycle; skipped for that reason, not because it was checked and passed.

---

## What was checked and passed

- Module isolation: **zero cross-module imports** found anywhere under `api/modules/` (every module imports only its own package, `api.modules.base`, and `api.modules.shared`). All 10 module directories have the required `__init__.py`/`module.py`/`data.py`/`module_config.py` file set. Per-module config is correctly scoped by `module_id` via `shared/config_store.py` — no shared/global config-key bleed found.
- Risk gate: fail-closed confirmed on every DB-touching path in `check()` (`try/except` around the whole exposure/budget/loss-limit block returns `RiskVerdict(False, "db_error:...")`; depth check rejects on `None`/`≤0`; spread/edge checks reject on missing data). Limit-only confirmed — no market-order path found anywhere searched. Dust-floor denominator bug (the exact class named in the brief) is already fixed as of `c762636`.
- No bare `except: pass` and no unguarded `.single()` calls found anywhere in `api/` outside the two LOW findings above (both log-adjacent, not order-path).
- No TODO/FIXME/XXX/HACK comments found in any money-touching file (risk, sizing, order placement, P&L).
- `engine.py:63` correctly filters `.neq("status", "inactive")` before evaluating modules — confirmed against live signal timestamps for the two inactive modules (both stopped generating signals exactly when they were marked inactive, 2026-07-24).
- Engine liveness: newest `logs` "Cycle: {...}" system-summary row at `2026-07-29 18:55:28Z`, ~5 min before `db_now` (19:00:56Z) — not stale.
- `global_halt` is `false` (`selftest_done`); no active halt.

## What could NOT be checked

- Could not verify current Polymarket wallet balance/open positions for the retired `master`-branch bot's credentials (finding #1) — no browser/Railway access in this session; this needs the operator to check directly before deleting the Railway service.
- SonarCloud PR-comment findings were not reviewed (this audit doesn't open against an existing PR with SonarCloud runs attached).
- Did not deep-audit any specific backtest per the `backtest-auditor` four-pass process, since no new backtest/claim landed in the last 7 days (see LOW #18) — this is not a statement that all existing backtests are clean, only that none are new this week.
- Did not verify CI status for this branch (no `gh`/GitHub Actions check run in this session beyond what's described here).
