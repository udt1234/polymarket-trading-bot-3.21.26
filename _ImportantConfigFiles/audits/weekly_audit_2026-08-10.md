# Weekly Audit — 2026-08-10

Code audited: `feat/newbot-step1-skeleton` @ `c762636a9fa8f0e18c4dd5d27af4579448f6250c` (live production bot; `master` is the retired old bot).
Live data: Supabase project `xdonwowgqvmtrduikaon`, last 7 days as of 2026-08-10 ~13:58 UTC.

This audit does not modify trading logic, risk limits, or module behavior. All fixes beyond the one clearly-labeled dead-code removal below are written recommendations for human review.

---

## CRITICAL

### C1. Retired old bot is still live and writing into the same production DB under the current Copytrader module's identity
The `logs` table has 4,114 rows matching `%enabled_wallets%` (`log_type='decision'`), spanning **2026-07-27 → 2026-08-10 13:54:17** (14 days, ~5-min cadence, still firing — 4 minutes before this audit ran). The exact message format `"Cycle: enabled_wallets={n} shadow_mode={b}"` only exists in `api/modules/copy_trading/module.py:190` — a module directory that is **present on `master` (the retired old bot) and absent from `feat/newbot-step1-skeleton`** (confirmed via `git show <branch>:api/modules/copy_trading/module.py`). Every one of these rows carries `module_id = 2611efa9-8042-4b16-9b67-b70e60460b1f`, which is the **live** "Copytrader" module's ID (the current bot's `api/modules/copytrader/`, a differently-named/structured package).

This means a second bot process — the old, supposedly-retired codebase — is still deployed somewhere and running its own copy-trading loop against the same Supabase project, tagging its writes with the new bot's Copytrader module_id. It has placed at least 213 paper orders under that module_id (all `executor='paper'`, so indistinguishable from the new bot's own orders by that column). Effects:
- Copytrader's P&L, position count, and exposure figures (used by the risk gate's per-module budget cap) are a **blend of two independent strategies' decisions**, not attributable to either one.
- Copytrader's -$135.57 realized loss in the last 7 days (vs -$128.25 all-time — i.e. nearly its *entire* lifetime loss happened this week) cannot be cleanly attributed to the current `copytrader` module's logic vs. the legacy process.

**Recommendation:** Find and shut down whatever deployment (old Railway service, stale container, forgotten cron) is still running the `master`-branch code. Until it's confirmed dead, treat all Copytrader P&L/exposure numbers as unreliable. Consider giving the current module a distinct `modules.id`/name if the old process can't be killed immediately, to at least stop the data contamination.

### C2. Row Level Security disabled on 4 production tables
Supabase advisory (live, `xdonwowgqvmtrduikaon`): `public.whale_movements` (220,593 rows), `public.ghost_trap`, `public.ghost_trap2`, `public.ghost_trap3` have RLS **disabled**, exposing them to full read/write via the anon and authenticated keys used by client libraries. `ghost_trap*` in particular are unrecognized by both branches' codebases (no code references them) — worth confirming what created them before deciding on a policy.

**Recommendation (do not auto-apply — enabling RLS with no policies will lock out legitimate access):**
```sql
ALTER TABLE public.whale_movements ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ghost_trap ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ghost_trap2 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ghost_trap3 ENABLE ROW LEVEL SECURITY;
```
Add appropriate policies first, then apply. Also worth confirming what `ghost_trap`/`ghost_trap2`/`ghost_trap3` are — they don't correspond to anything in either branch's code.

---

## HIGH

### H1. Arb Scanner: 0.15% signal approval rate — dominant gate is a saturated budget, not a broken gate
42,515 signals in 7 days, only 63 (0.15%) approved. Rejection breakdown: `module_budget_cap_500` = 28,084 (66%), `duplicate_resting_order` = 7,404 (17%), `circuit_breaker` = 2,079 (5%), the remainder spread across ~140 distinct `spread_X>tol_0.3` values. Cross-checked against live positions: Arb Scanner currently holds **$497.39 of open notional against a $500 module budget** — it is essentially always fully deployed, so nearly every new signal is correctly rejected by `risk_manager.py`'s per-module budget cap (`api/services/risk_manager.py:219-226`, which is correctly scoped to `module_bankroll(module_id)`, not the global bankroll — no repeat of the 2026-07-29 dust-floor-scaling incident here). This is not a gate bug; it's a strategy/signal-cadence mismatch: the module keeps re-evaluating and re-signaling markets it structurally can't act on. Recommend throttling Arb Scanner's signal generation (or short-circuiting `evaluate()`) once its own exposure is within some margin of its budget, to cut log/DB churn (30k+ rejected-signal rows/week from one module).

### H2. Elon Late Arb and Elon Reversion have produced zero signals since creation (17 days)
Both modules are `status='paper'`, `budget=500`, `updated_at=2026-07-24`, and the engine's own cycle summary confirms exactly 7 modules are evaluated every ~3-5 min (matching the 7 active-status rows in `modules`) — so both are being called, not skipped. Yet `signals` has **zero rows ever** for either module_id.

Root cause (static code review): both `elon_late_arb/module.py:53-55` and `elon_reversion/module.py:54-58` gate on a `0 < remaining_h <= window_hours` (6h) check, fed by each module's own copy of `live_elon_event()` (`elon_late_arb/data.py:17-27`, `elon_reversion/data.py:17-28`, byte-identical duplicated logic — itself a Module Architecture Rule 3 violation, this belongs in `shared/`). That helper queries Gamma sorted by `startDate desc` and takes the first result — i.e. the **most recently opened** live auction — which is the opposite of what a "last N hours before close" strategy needs; it should pick the auction **closest to expiry** (compare `api/modules/shared/discovery.py:76-86`'s `freshest_auction()`, whose own docstring notes "freshest" is only correct for entry strategies). Separately, both modules call `windows.parse_slug_window()` directly instead of `windows.resolve_window()` (which has an xTracker fallback); `parse_slug_window` returns `None` by design for monthly/7-day slugs, and both modules then silently `return []` — **no exception, no log line**. Either failure mode alone explains 17 days of silence with a healthy-looking engine cycle count.

**Recommendation:** Fix the event-selection logic to target the auction nearest expiry, deduplicate the two copies into `shared/`, and add a log line on the empty-window early return so a future silent failure is visible in `logs` instead of invisible.

### H3. `module_health` table is empty for every module — the documented health-persistence contract was never implemented
The table comment states it's "Populated by `BaseModule._persist_health()` at the end of each `evaluate()` cycle" — no such method exists anywhere in `api/modules/base.py` (79 lines, confirmed by full read) or is called from `api/services/engine.py`. This isn't a regression; it appears to have never been built. Per CLAUDE.md Module Architecture Rule 6 ("Each module surfaces its own health... `BotHealthBanner`... reads `/api/engine/health?module_id=X`"), whatever currently backs that endpoint is not `module_health`, or the banner has no real per-module signal.

### H4. Engine hardcodes a module name and reaches into its private internals
`api/services/engine.py:188,238,242` — `from api.modules.sports_sweep import data as sports_data`, `self.registry.get("sports_sweep")`, `.eq("strategy", "sports_sweep")`. Direct Module Architecture Rule 4 violation ("Engine/router code MUST NOT hardcode module names"), and also reaches into `sports_sweep`'s private `data.py` rather than going through the module's public `BaseModule` API. The generic fallback path at `engine.py:195-213` already handles this case module-agnostically, making 184-194 likely redundant.

### H5. Paper-executor SELL path has no fallback for missing `position_id` — silent-fill risk
`api/services/executor.py:137-140` — `PaperExecutor.check_fills()` marks a paper SELL "filled" and writes `trades`, but only calls `position_manager.apply_sell_fill()` when `metadata.position_id` is present, with no fallback to `apply_sell_fill_by_market()`. The **live** path (`api/services/order_state.py:104-118`) got exactly this fallback after the 2026-07-22 risk audit (F3). If any future module builds a paper exit `Signal` without `position_id` in metadata, the order/trade rows will show a successful fill while the position stays `open` forever and P&L/circuit-breaker never see the loss.

### H6. Test suite does not run clean; several tests reference APIs that no longer exist
`python -m pytest -q` from repo root **fails to even collect** (13 errors) — it also picks up unrelated data-analysis scratch scripts under `_DataMetricPulls/pacing_backtest/*_test.py` and `elon_schedule_analysis/test_tz_hypothesis.py` that expect local parquet files at a Windows path (`C:\Users\darwi\...`) that don't exist in this environment, plus `scripts/canonical/07_consistency_test.py` (missing `google` package). Scoped to `tests/` only: **9 failed, 64 passed, 3 collection errors**.
- `tests/test_engine.py`: `ImportError: cannot import name 'TradingEngine' from api.services.engine` — no such class exists in the current engine.
- `tests/test_risk_manager.py`: `ImportError: cannot import name 'RiskManager'` — `risk_manager.py` only exports a module-level `check()` function now.
- `tests/test_copy_trading.py`: imports `api.modules.copy_trading`, which does not exist on this branch (it's the retired module from C1 above — dead test for dead code).
- `tests/test_executor.py` (7 failures): `LiveExecutor(profile=...)` / similar constructor signatures no longer match — API drift, tests not updated.
- `tests/test_signals.py` (2 failures): `rank_brackets()`'s `top_n` default changed to 5 (test asserts ≤3); `kelly_sizing()` floors sizing at 30% even at `elapsed_pct=1.0` (test expects exactly 0) — the code comment states the 30% floor is intentional, so this reads as a stale test rather than a code bug, but it means Kelly sizing near auction close has **zero regression coverage** either way.

None of this is a live-trading bug by itself, but it means the test suite currently provides no real safety net for engine/risk-manager/executor changes — exactly the code CLAUDE.md's `/pre-commit` and `verify-bot` gates are supposed to protect.

---

## MEDIUM

- **All 5 active paper modules are net losers, all-time**: Arb Scanner -$78.10, Copytrader -$128.25 (contaminated per C1), Market Maker -$39.83, S2 Basket-Hold -$216.08 (49 closed trades, its all-time worst), Sports Sweep -$5.68. Paper mode, so no real capital at risk, but worth a strategy review before any module goes live.
- **circuit_breaker.trips = 65** (cumulative counter in `settings`, cooldown last set to expire 2026-08-10T00:30 UTC). No structured "circuit breaker tripped" message pattern was found in `logs` over the last 7 days, so trip frequency/timing isn't independently auditable from the logs table — only the current counter state is visible. Consider logging each trip event explicitly.
- **Backtest integrity gaps** vs `.claude/agents/backtest-auditor.md`: `scripts/canonical/backtest_spike_ladder_vs_floor.py` (lines ~89-110) fills an entire tier's size instantly whenever the hourly low merely touches the limit price — no L2 depth or queue-position modeling, which optimistically inflates the ROI numbers behind the CLAUDE.md Spike-ladder bracket recommendations. No script anywhere in the repo calls `run_meta.emit_run_meta` — every backtest output, including the headline Spike bracket table, is currently unversioned/unauditable provenance. No zero-edge/random-baseline control run exists to benchmark ROI against.
- **Reverse-dependency layering violation**: ~9 modules import `api.services.*` directly (`risk_manager.Signal`, `clob`, `position_manager`) instead of via `BaseModule`/`shared/` — e.g. `elon_reversion/module.py:20-21`, `market_maker/module.py:13-15`, `s2_basket_hold/module.py:59-60`, `sports_sweep/decision.py:15-16`. Not a correctness bug, but inverts the documented `services/ ← modules/` dependency direction.
- **5 modules query the `orders` table directly** instead of through `position_manager`/`order_state` (`mirror_trader`, `sports_sweep`, `s2_basket_hold`, `copytrader`, `lp_rewards`) — duplicated resting-order-state logic across modules.
- **Doc/code drift**: `ARCHITECTURE.md` and `MODULE_ARCHITECTURE.md` still describe `truth_social/`, `elon_tweets/`, `spike_trading/`, `copy_trading/` modules that don't exist on this branch. CLAUDE.md Rule 1 calls `data.py` mandatory; `MODULE_ARCHITECTURE.md:53-56` calls it optional — pick one and align.
- **8 orphan Supabase migrations** (008, 009, 010, 011, 014, 017, 018, 019) create tables no `api/` code currently queries; `retention.py:14-15` still prunes `post_count_snapshots`/`order_book_snapshots`, the latter of which nothing writes (0 rows live, confirmed).
- `base.py`'s `BaseModule` contract is missing ~10 methods that `MODULE_ARCHITECTURE.md:104-156` documents as part of the interface (`get_auction_title_filter`, `get_buy_order_ttl_hours`, `get_market_universe`, `get_brackets`, `get_strategy_metadata`, `archive_resolved_auction`, …); relatedly, buy-order TTL is one global `stale_order_hours` in `engine.py:152`, not per-module as documented.

---

## LOW

- `api/services/halt.py:53-54,60-61` — bare `except Exception: pass` around the halt-notification and halt-audit-log insert in `set_halt()`, with no `log.exception`. A safety-critical kill-switch event could fire silently with no Telegram alert and no audit trail if either call fails.
- `api/services/engine.py:249` — bare `except: pass` swallowing a per-row config-parse error in `_active_sports_series()`; a malformed config would silently drop `sports_sweep` from paper-fill coverage with no trace.
- Class-naming inconsistency: some modules export `Module`, `arb_scanner` exports `XModule` — cosmetic, hurts grep-ability.
- **Removed in this PR** — `api/modules/demo/` was a self-documented placeholder ("Delete once S2 lands" — S2 Basket-Hold has landed), still auto-registered by `pkgutil` discovery with no code referencing it. Confirmed zero external references before deletion.

---

## What's healthy

- `risk_manager.py` fails closed on every DB error / missing price / missing depth data; the dust floor is a correct **absolute** $1 minimum (not scaled by global bankroll — the 2026-07-29 starvation bug stays fixed); the per-module budget cap is correctly scoped to `module_bankroll(module_id)`, not the global bankroll. The exact "wrong denominator" bug class this audit was asked to check for is **not present**.
- **Zero literal cross-module imports** across all 10 current module directories — every non-self import resolves to `base` or `shared`. File layout (`module.py`/`data.py`/`module_config.py`/`__init__.py`) is complete for all modules.
- `engine.cycle()` isolates each module's `evaluate()` call in its own try/except so one module's failure cannot block the others.
- **Engine liveness: healthy.** Latest `Cycle:` heartbeat log at 2026-08-10 13:56:23 UTC, 2 minutes before this audit's query (DB `now()` = 13:58:14 UTC) — well within the 20-minute staleness threshold.
- `global_halt.halted = false`. No active halt.
- No `.single()` calls found anywhere in the codebase — the PGRST116 incident class documented in `lessons.md` (`elon_tweets`/`truth_social` rows) appears fully remediated.
- No TODO/FIXME/HACK found in any money-touching file under `api/services/` or `api/modules/`.
