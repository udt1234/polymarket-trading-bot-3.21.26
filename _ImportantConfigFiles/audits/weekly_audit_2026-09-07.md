# Weekly Audit — 2026-09-07

Scope: live bot state (Supabase, project `xdonwowgqvmtrduikaon`, last 7 days) + code on
`feat/newbot-step1-skeleton` (the live production branch). No live trading logic, risk
limits, or module behavior was changed. Findings below are recommendations for human
review only.

## Headline

1. A **foreign/legacy writer is still active** on the shared logs table — the "ghost
   writer" flagged as an open item in the 2026-09-04 session docs has not been killed.
2. The **test suite for the three most safety-critical files (risk manager, executor,
   engine) cannot even be collected** — CI has had zero real coverage on money-path code
   for an unknown period.
3. Three modules are persistent losers on paper money; two other paper-active modules
   have produced zero signals in 7 days.

---

## LIVE FINDINGS (Supabase, last 7 days)

### CRITICAL

- **Foreign writer still active.** `logs` contains 1,980 rows matching
  `Cycle: enabled_wallets=0 shadow_mode=False` in the last 7 days (2026-08-31 →
  2026-09-07 13:24:03 UTC), on a ~5-minute cadence distinct from and interleaved with the
  bot's own `Cycle: {'modules': 7, ...}` heartbeat (latest 13:26:27 UTC). This is the
  legacy/foreign-key bot on the shared DB called out in CLAUDE.md and already identified
  as an open item in the 2026-09-04 "ghost writer ID" session — it was not resolved and is
  writing right now, minutes before this audit ran. Recommend locating and decommissioning
  whatever deployment is still emitting `enabled_wallets=`/`shadow_mode=` log lines (likely
  a stale Railway service or an old process still pointed at this Supabase project).

### HIGH

- **Persistent losing modules (paper).** Realized P&L, 7-day / all-time, vs. $500 budget:
  - **S2 Basket-Hold**: −$55.05 / **−$355.26** (−71% of budget all-time), 3 open positions
    of 63 total.
  - **Copytrader**: −$17.13 / **−$281.87** (−56% all-time), 11 open of 100 total.
  - **Arb Scanner**: **−$156.60** (worst 7-day bleed of any module) / −$234.70 all-time
    (−47%), 10 open of 31 total.
  - Market Maker (−$35.36 all-time, flat 7d) and Sports Sweep (−$5.12 all-time, +$0.56 7d)
    are comparatively immaterial.
  All three are still `status=paper`, so no real capital is at risk, but none should be
  considered for a paper→live flip until root-caused.

- **Two paper-active modules producing zero signals.** `Elon Late Arb` and
  `Elon Reversion` are both `status=paper` with a $500 budget each, but neither appears in
  `signals` at all for the last 7 days (0 rows). Either their signal-generation pipeline is
  silently failing (no error surfaced) or they should be marked `inactive` — right now the
  config says "trading" and nothing is happening.

### MEDIUM

- **Signal generation is dominated by pure noise for the two most active modules.**
  Arb Scanner emitted 40,154 signals in 7 days, only 4,698 (11.7%) approved;
  `duplicate_resting_order` alone is 18,129 of the rejections (45% of all Arb Scanner
  signals) — it re-emits a signal for a market/bracket where a resting order already
  exists, every cycle, instead of checking existing order state before generating. Market
  Maker shows the identical pattern (`duplicate_resting_order` = 3,761 of 4,529 signals,
  83%). The risk gate correctly blocks these before any order is placed, so there is no
  P&L exposure — but it is wasted DB writes/compute and it is exactly the kind of noise
  that hid a real "approved ≈ 0" bug for days previously per CLAUDE.md. Recommend the
  modules skip signal generation for (module, market, bracket) tuples that already have a
  resting BUY, rather than relying on the risk gate to reject after the fact.
- **`rejection_reason` embeds the raw numeric value** (`spread_0.960>tol_0.3`,
  `spread_0.950>tol_0.3`, …dozens of variants this week alone), which fragments any
  `GROUP BY rejection_reason` into near-duplicate rows and makes the dominant gate harder
  to spot from a dashboard or a quick query. Recommend a bucketed reason code (e.g.
  `spread_too_wide`) with the exact value kept in `metadata`/jsonb instead of the string.

### LOW / healthy

- **Overall approval health is fine right now**: 5,487 / 45,495 signals approved over 7
  days (12.1%) — not the "approved ≈ 0 while signals > 0" failure mode the audit brief
  warns about. No action needed beyond the two items above.
- **Engine liveness: healthy.** Newest `Cycle:` heartbeat at 2026-09-07 13:26:27 UTC,
  well inside the 20-minute staleness threshold.
- `settings.circuit_breaker` shows 81 cumulative trips with `cooldown_until` already
  elapsed (2026-09-07T08:01:10Z) and `consecutive_losses: 0`; `global_halt.halted = false`.
  Breaker is not currently tripped. 81 is a lifetime counter, not urgent, but worth
  confirming it's meant to accumulate forever rather than reset.

---

## CODE FINDINGS

### CRITICAL

- **The test suite for the three most safety-critical files cannot be collected.**
  `python -m pytest tests/` fails outright with 3 collection errors before any test runs:
  - `tests/test_risk_manager.py` imports `RiskManager` from `api/services/risk_manager.py`
    — that class doesn't exist; the module now exposes a functional `check()` API (see
    `risk_manager.py:143`). The risk gate has had **zero executable test coverage** for an
    unknown period.
  - `tests/test_engine.py` imports `TradingEngine` from `api/services/engine.py` — also
    does not exist under that name.
  - `tests/test_copy_trading.py` imports from `api.modules.copy_trading` — the module is
    actually named `copytrader`; the import path is simply wrong.
  Additionally, once those are excluded, `tests/test_executor.py` fails all 7 of its
  tests: `LiveExecutor.__init__()` no longer accepts the `profile` kwarg the tests
  construct it with, and the `PaperExecutor` tests `@patch` a function
  (`api.services.executor.open_position`) that no longer exists in that module. None of
  `executor.py`'s current behavior is under test.
  **Net effect**: risk manager, executor, and engine — the three files that decide
  whether and how real orders get placed — currently have no passing automated coverage,
  and this would not be caught by casually running `pytest` without `-q`/reading collection
  errors closely, since the summary line ("9 failed, 70 passed") reads as "mostly green."
  This is the silent-failure pattern CLAUDE.md's testing discipline exists to catch.
  **Recommend**: treat restoring these three test files to the current `check()` /
  executor / engine APIs as the top priority coming out of this audit.

### HIGH

- **Engine hardcodes a module name (Module Architecture Rule 4 violation).**
  `api/services/engine.py:201` does `from api.modules.sports_sweep import data as
  sports_data`, and lines 251/255 do `registry.get("sports_sweep")` /
  `.eq("strategy", "sports_sweep")`. This is exactly the `if "trump" ... elif "elon"`-style
  special-casing the architecture rules forbid. The generic block immediately above it
  (`engine.py:208-226`) already fetches quotes for any uncovered resting token, so the
  special case looks redundant. Recommend replacing with a `BaseModule.get_quote_tokens()`
  method rather than deleting blind.
- **Dead imports of the decommissioned `truth_social` module.**
  `scripts/backfill_truth_social.py:32` and `scripts/verify_post_count.py:22` both do
  `from api.modules.truth_social.truthsocial_direct import ...`, but `api/modules/
  truth_social/` was deleted when that module was decommissioned (confirmed live in
  Supabase: `modules.inactive_reason = 'decommissioned'`, dated 2026-07-11). Both scripts
  will crash on import if anyone reruns a Trump backfill.

### MEDIUM

- **Two doc/code drifts.** (1) CLAUDE.md's Module Architecture Rules list
  `module.get_search_term()` as part of the `BaseModule` API; `api/modules/base.py` has no
  such method. (2) `web/app/page.tsx:69-97` hardcodes a `MODULE_INFO` dict keyed by module
  name covering only 6 of the 10 currently-registered modules (missing `demo`,
  `elon_late_arb`, `elon_reversion`, `market_maker`) — a new or renamed module silently
  gets no dashboard description. This metadata belongs on `BaseModule`, served via the API,
  per the module-agnostic-UI intent of the architecture rules.
- **Two stale (not regressed) test assertions in `tests/test_signals.py`.**
  `test_elapsed_100pct_zeros_kelly` expects `kelly_pct == 0` at `elapsed_pct=1.0`, but
  `kelly_sizing()` (`api/modules/shared/signals.py:60-63`) has an explicit, intentional
  30%-floor time-decay ("floor at 30%"), so it can never reach exactly 0 from time decay
  alone — the test is wrong, not the code. `test_returns_top_3` expects `rank_brackets()`
  to cap at 3 results, but the function's `top_n` defaults to 5
  (`api/modules/shared/signals.py:81`) and the test never passes `top_n=3`. Same root cause
  as the CRITICAL finding above (tests drifting from code), smaller blast radius since
  these are logic, not import, failures.
- **Canonical backtest scripts predate the RUN_META mandate.** None of the 6
  `scripts/canonical/backtest_*.py` scripts (`backtest_spike_v2.py`,
  `backtest_spike_ladder_vs_floor.py`, `backtest_noovd*.py` ×4) emit a `RUN_META` block,
  unlike the 11 scripts under `_DataMetricPulls/pacing_backtest/` that already import
  `emit_run_meta`. Per `.claude/agents/backtest-auditor.md`, "a backtest with NO RUN_META
  is a class-C finding in itself." All 6 last changed 2026-07-11, before the RUN_META
  mandate landed (2026-07-22, commit `1a09866`), and were never retrofitted. They do
  correctly read from the canonical parquet layer (Pass A "canonical source only" is
  satisfied). Any number quoted from these 6 scripts should be treated as unverified until
  rerun through `@backtest-builder` / `@backtest-auditor`.

### LOW

- `get_config_schema()` (drives auto-generated settings forms) is overridden by only 1 of
  10 modules (`s2_basket_hold`); the other 9 fall back to an empty list. Contract-compliant,
  low coverage — worth backfilling opportunistically, not urgent.

### Checked and clean (reported so silence doesn't read as "not checked")

- `risk_manager.py`: every DB-touching branch fails closed (`except Exception` →
  `RiskVerdict(False, "db_error:...")`); the dust floor is an absolute $1
  (`signal.notional < 1.0`, line 189), **not** scaled by the global bankroll — confirmed
  correct, no recurrence of the 2026-07-29 wrong-denominator bug.
- No cross-module imports anywhere under `api/modules/*` (verified directly and via the
  `@qa-architecture-quality` agent) — the module-isolation rule is otherwise fully intact.
  All 10 modules have the required sealed structure (`module.py`/`data.py`/
  `module_config.py`/`__init__.py`).
- No bare `except: pass` and zero `.single()` calls anywhere in the repo — the PGRST116
  tripwire class of bug (the one that led to decommissioning `elon_tweets`/`truth_social`)
  is fully gone, not just patched over.
- No `TODO`/`FIXME`/`XXX` markers under `api/`.
- 70 of 79 collectible tests in `tests/` pass; `test_pacing.py`, `test_projection.py`, and
  `test_windows_slug.py` pass in full.

---

## Test run

```
python -m pytest tests/ -q
# 3 files fail to collect (see CRITICAL above): test_risk_manager.py, test_engine.py, test_copy_trading.py
python -m pytest tests/ -q --ignore=tests/test_copy_trading.py --ignore=tests/test_engine.py --ignore=tests/test_risk_manager.py
# 9 failed, 70 passed
```

## Recommendations for human review (no code changes made to trading logic)

1. Find and kill the foreign log writer — highest priority, it's active right now.
2. Restore `tests/test_risk_manager.py`, `tests/test_engine.py`, `tests/test_executor.py`,
   `tests/test_copy_trading.py` to the current APIs before trusting any future PR's green
   CI on money-path code.
3. Root-cause Arb Scanner / S2 Basket-Hold / Copytrader losses before any paper→live flip;
   investigate why Elon Late Arb / Elon Reversion emit zero signals.
4. Remove the `sports_sweep` hardcode in `engine.py` in favor of a generic
   `BaseModule.get_quote_tokens()` method.
5. Delete or fix the two dead `truth_social` script imports.
6. Retrofit the 6 `scripts/canonical/backtest_*.py` scripts with RUN_META, or route future
   backtests through `@backtest-builder` from scratch per CLAUDE.md.
