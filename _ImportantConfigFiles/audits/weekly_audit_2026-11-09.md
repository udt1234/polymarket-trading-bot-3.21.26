# Weekly Audit — 2026-11-09

Branch audited: `feat/newbot-step1-skeleton` (live production branch per CLAUDE.md; `master` is the retired old bot).
Live data: Supabase `xdonwowgqvmtrduikaon`, last 7 days unless noted. Code: full-repo static read + `pytest`.

## Summary

The bot is **currently placing zero trades** — all 11 modules have been `inactive` since the owner paused them on 2026-09-07 for being loss-making, and that is intentional. The live risk here isn't today's trading, it's **what happens on the next deploy**: the live branch's watchdog is missing a safety fix (honoring `paused_by_owner`) that exists only on the retired `master` branch, and will auto-revive all 7 paused modules — including known losers — within 15 minutes of running, unless ported first. Separately, the bot's test suite cannot currently validate the risk gate, engine, or executor at all (import failures), and one previously-FAILed backtest's result is still sitting untouched in the repo.

---

## LIVE — Supabase (last 7 days unless noted)

### CRITICAL — Live branch's watchdog will auto-revive 7 owner-paused, loss-making modules on next run
`scripts/watchdog.py:200` (the script systemd-deployed via `infra/watchdog/polybot-watchdog.service` → `ExecStart=.../scripts/watchdog.py`, run every 15 min per `polybot-watchdog.timer`) skips auto-revive only for `inactive_reason in ("decommissioned", "dead_thesis")`. It does **not** skip `paused_by_owner`. All 7 currently-paused modules (Arb Scanner, Copytrader, Elon Late Arb, Elon Reversion, Market Maker, S2 Basket-Hold, Sports Sweep) carry `inactive_reason='paused_by_owner'` with `inactive_detail`: *"Paused on Sir's instruction 2026-09-07: every module is loss-making on the paper bench (-$1,217 on $10k). **Do NOT auto-revive.**"*

The fix for exactly this — `if inactive_reason in ("decommissioned","dead_thesis","paused_by_owner"): continue` — exists in commit `59da928` ("let the owner pause a module"), but that commit is **only on `master`**, never merged/ported to `feat/newbot-step1-skeleton` (`git merge-base --is-ancestor 59da928 HEAD` → not an ancestor). The same commit also replaced the global-only circuit breaker with a per-module one in `api/services/breaker.py`; that file on this branch is still the old single-counter version (`KEY = "circuit_breaker"`, no per-module keys) — so one losing module can again gate every other module's entries, the exact bug the Sep 7 fix addressed (635 Arb Scanner losses blocked 22 unrelated S2/Copytrader signals).

**Open question for a human:** the modules have stayed correctly `inactive` for 2+ months despite this branch's watchdog code running every 15 min — which means either the Dublin VPS is actually still running `master`'s (fixed) code, or a hotfix was applied on the box that was never committed back. **Verify what commit is actually deployed before touching this branch's watchdog/breaker code**, then port both fixes (`scripts/watchdog.py` skip-list + `api/services/breaker.py` per-module scoping) onto `feat/newbot-step1-skeleton` before any redeploy from it.

### HIGH — Watchdog restarted the live engine 6x in 7 days on an unverifiable signal
`scripts/watchdog.py:29-42` (`_last_cycle_age_min`) returns `None` on *any* exception from its `httpx.get("http://localhost:8000/api/engine/health")` call — timeout, connection refused, bad JSON, all collapse to the same `None`. The caller (`:163-170`) treats `age is None` identically to "engine actually stalled" and forcibly runs `systemctl restart polybot.service`. This fired 6 times in the last 7 days (2026-11-05, 11-06, 11-07, 11-08 ×2, 11-09), each logged as `"watchdog fixed: engine not cycling (age=Nonem) -> systemctl restart polybot.service"` — note `age=Nonem`, i.e. the age was *never once a real number*, only ever the unreachable/error case. There is no way from the logs to tell whether the engine was actually wedged or the health endpoint was just briefly slow/busy each time. Since no modules are trading right now the blast radius is zero, but once modules are live again this restarts the order-placing process on an ambiguous signal, up to once every ~`RESTART_COOLDOWN_MIN` (8 min).
**Fix:** distinguish "health endpoint unreachable" from "cycle genuinely stale" (e.g. alert-only on unreachable, restart only on a parsed, stale `last_cycle_at`), and log the real exception type instead of `None`.

### Approval health, P&L, module status
- **Signals (7d):** 0 generated, 0 approved — expected, all modules inactive. Rejection-reason breakdown is N/A (no signals to reject). **All-time:** 192,664 signals / 12,944 approved (6.7%); last signal ever was 2026-09-07 18:23 — the pause moment.
- **Realized P&L (all-time, all-time = 7d total since nothing has traded since the pause):** S2 Basket-Hold **-$486.27**, Arb Scanner **-$458.11**, Copytrader **-$321.73**, Market Maker **-$35.36**, Sports Sweep **-$5.12** (sum **-$1,306.59**, in line with the "-$1,217 on $10k" cited at pause time plus positions that wound down afterward — e.g. Arb Scanner's last exit was 2026-10-19, a month after the pause, which is expected: pausing stops new entries, not existing exits). No open positions, zero unrealized P&L.
- **Module health:** All 11 modules `inactive`. 7 `paused_by_owner` (2026-09-07), 2 `decommissioned` (`elon_tweets`, `truth_social`, both retired to stop a `.single()` PGRST116 tripwire — see CODE section), 2 `dead_thesis` (LP Rewards, Mirror Trader). None currently emit signals, so the "signals but never approved" check is moot this week.
- **Engine liveness:** Newest `Cycle:` log is from minutes before this audit ran — not stale by the 20-min bar. Cycle cadence is ~5 min, consistently logging `modules: 0` (correct, given the above).
- **Foreign writer (`enabled_wallets`):** none found. Caveat: the `logs` table only retains back to 2026-10-26 (5,494 rows total), so this only clears the last ~2 weeks, not history.
- **Settings sanity:** `global_halt.halted = false`; global `circuit_breaker` key is stale (cooldown timestamp in the past, last updated 2026-07-06, predates the per-module keys that do exist for some modules) — harmless now, but another symptom of the branch/breaker divergence above.

---

## CODE — `feat/newbot-step1-skeleton`

### CRITICAL — Test suite cannot currently validate risk_manager, engine, executor, or copytrader
- `tests/test_risk_manager.py` and `tests/test_engine.py` fail at **import/collection** — they reference `RiskManager`/`TradingEngine` classes that don't exist; live code is function-based `risk_manager.check()` and `class Engine`. Neither file has run a single assertion since this drift began.
- `tests/test_copy_trading.py` imports `api.modules.copy_trading.*`; the live module is `api/modules/copytrader/` (`CopytraderModule`). 100% dead test file.
- `tests/test_executor.py`: **7 of 11 tests fail** against the current `executor.py` — `LiveExecutor.__init__()` no longer takes `profile=`, `PaperExecutor` tests patch a now-nonexistent `open_position` attribute. Real signature drift, not flakiness.
- Net effect: the four money-path areas this audit was asked to scrutinize (risk gate, engine, executor, module-approval) have **no working automated regression coverage** on this branch today. A future change to any of them could pass `/pre-commit` and CI clean while silently breaking order placement.
- `python -m pytest -q` (scoped to `tests/`): 4 collection errors, 9 failed, 70 passed. (Full-repo run also hits 15 unrelated `numpy`/`pandas`/`duckdb` import errors in `_DataMetricPulls/`/`scripts/canonical/` — environment gap, not a code defect, not pursued further.)

### CRITICAL — A FAIL-audited backtest's numbers are still sitting in the repo, unfixed, unflagged
`_DataMetricPulls/pacing_backtest/audits/wh_pace_port_backtest_2026-07-24.md` gave `wh_pace_port_backtest.py` a **FAIL**: its zero-informational-edge control stayed profitable ($131–$2,689) under every fill-realism stress test, meaning the fill model itself — not the data — fabricates the edge. The audit's required fix (model queue position / market impact) was never applied; the file has no content-revising commit since (only a bulk "start tracking research scripts" commit), and no re-audit exists. Per CLAUDE.md, `@backtest-auditor` is "the ONLY way a backtest result gets trusted... no exceptions" — this one failed and nothing happened. **Any WH/Elon ROI number quoted from this script (e.g. +$613.7, +$5,830) is not trustworthy.** Fix: either apply the queue/market-impact fix and re-run `@backtest-auditor`, or quarantine the script and purge any numbers derived from it from memory/lessons files.

### HIGH — Risk gate's module-budget cap can silently fail open to the global bankroll
`api/modules/shared/config_store.py:24-36` (`module_bankroll()`), the sole source of the per-module budget used by `risk_manager.py:222-226`'s `module_budget_cap`, catches its own DB exception internally and **returns the full global bankroll** instead of raising. `risk_manager.check()`'s outer `try/except` (lines 192-241) is built to fail-closed on exactly this class of error ("risk gate DB failure - failing CLOSED") — but never sees it, because the error is swallowed one frame down. **Failure scenario:** a transient Supabase read error on `modules.budget` during that call → a module's budget cap compares against the full ~$10k bankroll instead of its real ~$200-500 budget → the cap doesn't trip → a single module can again eat the whole portfolio for the duration of the outage, the same bug class (wrong-denominator sizing) this cap exists to prevent. **Fix:** re-raise instead of returning `get_settings().bankroll` on error, and let the outer gate reject.

### HIGH — Unresolved spec question: can the bot size a position after an auction window has fully elapsed?
`api/modules/shared/signals.py:61-63` floors `kelly_sizing()`'s time-decay at 30% (`max(1.0 - elapsed_pct, 0.30)`), so at `elapsed_pct=1.0` it still returns a nonzero Kelly stake. `tests/test_signals.py::test_elapsed_100pct_zeros_kelly` asserts it should be zero. This function currently has no live caller (see below), so it's not live-risky today, but needs a human decision — floor intentional, or bug — before it's wired back into a module.

### MEDIUM — Dead shared-sizing code, doc drift
- `kelly_sizing()` / `rank_brackets()` in `api/modules/shared/signals.py` have zero call sites in any live module — `s2_basket_hold` and `copytrader` each reimplement their own Kelly sizing instead. Violates CLAUDE.md "prefer deleting code over adding it" and the shared-code consolidation goal in `MODULE_ARCHITECTURE.md`. Either delete, or make the live modules actually use it.
- `_ImportantConfigFiles/MODULE_ARCHITECTURE.md`'s directory-layout example documents modules (`truth_social/`, `elon_tweets/`, `spike_trading/`, `copy_trading/`) that don't exist on this branch; the actual live set is `arb_scanner, copytrader, demo, elon_late_arb, elon_reversion, lp_rewards, market_maker, mirror_trader, s2_basket_hold, sports_sweep`. The 8 module-architecture *rules* are still followed (verified clean — see below); only the concrete example is stale.
- CLAUDE.md references `_ImportantConfigFiles/MODULE_QUICK_RULES.md`, which does not exist (only `MODULE_ARCHITECTURE.md` does).
- CLAUDE.md's "⭐ SPIKE TRADING" banner points at `_ImportantConfigFiles/SPIKE_BRACKETS.md`, which doesn't exist (actual: `SPIKE_RIDER_SPEC.md`, `spike_trading_module_spec.md`).
- `_ImportantConfigFiles/HANDOFF.md` is dated 2026-05-18 and describes the *old* bot entirely (Truth Social/Elon Tweets/Spike modules, Railway-only deploy) — superseded by the VPS move (`infra/vps/`) and the current module set. Per CLAUDE.md this should be updated "at end of major work sessions"; it hasn't been since the rebuild.
- `tests/test_signals.py::test_returns_top_3` fails on `rank_brackets()`'s default `top_n=5` vs. expected `3` — moot given no live caller, but confirms the contract drifted from what was last agreed.

### LOW
- CLAUDE.md's "ALWAYS run all 15 risk checks" is stale — `risk_manager.check()` actually has ~18-19 distinct reject paths. Not a safety gap (more checks, not fewer), just an inaccurate number in the doc.
- `api/services/halt.py:53,60` — bare `except Exception: pass` on best-effort notify/log calls (not money-path; halt state is persisted before either call), inconsistent with the rest of the file's `log.exception` pattern.
- `elon_tweets`/`truth_social` modules carry `inactive_detail`: *"Row inserted to stop PGRST116 tripwire from engine `.single()` fetch. Module code retired."* — a known, already-handled instance of the `.single()`-on-possibly-empty-result failure mode; no live `.single()` call sites found elsewhere in `api/`.
- `infra/watchdog/` directory contains two unrelated things: the actually-deployed systemd unit/timer (targets `scripts/watchdog.py`) *and* a separate, older `watchdog.py` + Railway `nixpacks.toml`/`railway.toml` for a different, external Telegram-only watchdog design that nothing currently points at. The old Railway files are likely dead and should be removed or clearly marked retired to stop future confusion about which watchdog is live (directly relevant to the CRITICAL finding above).

### Verified clean — no finding
- **Limit-only orders:** confirmed by construction. `executor.py:77` submits GTC `post_only` orders; `risk_manager.check()` rejects `price<=0` or `>=1`. No market-order path exists.
- **Cap stack coherence:** duplicate → single-market → correlated → module-budget → portfolio → daily-loss → weekly-loss → drawdown → depth is internally consistent; no cap found that can never trigger or contradicts another. Dust floor is a correct absolute $1 floor (previously fixed from a global-bankroll-fraction bug, 2026-07-29) — this one specific check does **not** have the wrong-denominator bug the task asked about.
- **Module isolation:** zero cross-module imports across all 10 module folders; no hardcoded module-name branching in `api/routers/*` or engine code; every module has the required `__init__.py`/`module.py`/`module_config.py` layout.
- **WebSocket backoff:** `tweet_stream.py` and `fills.py` both implement genuine capped exponential backoff (`min(backoff*2, N)`).
- **Hardcoded secrets:** none found in `api/` — env vars only.
- **Silent failures (money path):** no bare `except: pass` found anywhere in `api/`; the pattern exists only in research/backtest scripts under `_DataMetricPulls/` and `scripts/`.
- **Backtest anti-pattern (winner-price epsilon-fill):** previously caught by `@backtest-auditor` (2026-07-29) in `pattern_discovery_2026-07-26.py` and properly fixed (gates on `b4_admissible`, confirmed by a reaudit) — a working example of the required agent loop.

---

## Recommended next actions (human review required — no live logic was touched by this audit)
1. **Confirm what commit is actually running on the Dublin VPS** before any redeploy of `feat/newbot-step1-skeleton`'s `scripts/watchdog.py` or `api/services/breaker.py`.
2. Port commit `59da928`'s two fixes (`paused_by_owner` skip in the watchdog; per-module circuit breaker) from `master` onto this branch.
3. Fix `scripts/watchdog.py`'s health-check to distinguish "unreachable" from "stale" before trusting its auto-restart in a live-trading state.
4. Fix `module_bankroll()` to re-raise (not fall back to global bankroll) on DB error.
5. Repair or remove the 4 broken test files (`test_risk_manager.py`, `test_engine.py`, `test_copy_trading.py`, `test_executor.py`'s 7 failures) before trusting `/pre-commit` on risk/engine/executor changes again.
6. Decide and re-audit `wh_pace_port_backtest.py`, or quarantine its numbers.
7. Resolve the `kelly_sizing()` 30%-floor-vs-zero-at-100%-elapsed question before wiring it into any live module.
