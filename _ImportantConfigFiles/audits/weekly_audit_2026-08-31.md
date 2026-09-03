# Weekly Audit — 2026-08-31

Branch audited: `feat/newbot-step1-skeleton` (live production code). Supabase project `xdonwowgqvmtrduikaon`.
Auditor could not run direct SQL against Supabase from this sandbox (Postgres port not reachable; management/logs API only) — this materially limited the LIVE section. See L-1.

## TL;DR

- **L-1 CRITICAL — Supabase has been down for the bot for 16–24+ hours, ongoing.** PostgREST can't load its schema cache; every request 503s with "statement timeout." The bot's own traffic (reading `modules`, writing `telegram_alert_state`) is failing live, right now. Needs hands-on Supabase intervention — this audit cannot fix it.
- **L-2 CRITICAL — the watchdog can't tell you when this happens.** `scripts/watchdog.py` has an unguarded Supabase call that crashes `main()` before it reaches the alert/notify code, specifically during a total-DB-outage failure mode. It likely did not alert anyone about L-1.
- **C-1 CRITICAL (code) — paper and live P&L/exposure are commingled** in every risk-manager gate. Loss limits can stay green while real money is down.
- **Backtest layer is unauditable by its own standard**: RUN_META (built 2026-07-22 specifically to gate this) is wired into zero backtests.
- **CLAUDE.md's "Spike Trading" section is stale**: that module was deleted in the very first commit of this branch. The file still instructs every session to surface it first.
- Module sealing (no cross-module imports, per-module config) is genuinely clean — the leaks are in the engine layer, not the modules.

---

## LIVE (Supabase, `xdonwowgqvmtrduikaon`)

**L-1. CRITICAL — Database outage, ongoing, 16–24+ hours.** `query_logs` on `postgrest_logs` shows 10,790 `503` responses between `2026-08-30T14:06:46Z` and the latest visible log entry `2026-08-31T06:33:56Z`, with **zero successful (`200`) requests anywhere in the full 24h log window** — the outage may predate the window. `postgres_logs` shows recurring `canceling statement due to statement timeout` every 1–3 minutes, including on trivial queries (`SELECT setting FROM pg_settings WHERE name='max_connections'`, 10.4s before cancel) and `PGRST002 Could not query the database for the schema cache. Retrying.` Confirmed bot-originated failing calls: `GET /modules?select=id,name,strategy,market_slug&status=neq.inactive` → 503, `POST /telegram_alert_state?on_conflict=key` → 503, `GET /telegram_alert_state?key=eq.manual_watches_v1` → 503 (all `python-httpx/0.28.1`, the bot's own client). This matches the failure shape of the 2026-05-22 Disk IO incident CLAUDE.md already documents (retention policy was the fix for that one — worth checking whether retention cleanup/archive jobs are still running, or whether an unbounded table is behind this recurrence). **Action needed from a human with dashboard access**: check Supabase project compute/disk health, look for a long-running/blocking query or lock, consider a compute restart.
**L-2. CRITICAL — this audit could not complete the standard live checks** (signal approval rates + rejection_reason breakdown, per-module realized P&L 7d/all-time, module health, engine `Cycle:` staleness, foreign-writer `enabled_wallets` scan) because `execute_sql`/`list_tables` time out identically to the bot's own traffic, and this sandbox has no Postgres-port or Railway-domain egress to try an alternate path (dashboard URL fetch returned `EGRESS_BLOCKED`). A search for `%enabled_wallets%` across the visible `postgrest_logs` window returned zero rows — no evidence of the foreign-writer bot in the last 24h, but this is inconclusive given the outage dominates that window.
**L-3. HIGH — the watchdog cannot surface L-1 to a human.** `scripts/watchdog.py:194-204` queries `sb.table("modules")...` with **no try/except**, unlike every other Supabase call in the same function (`_signal_approval_stats`, `_hours_since_last_order`, `_recent_watchdog_restart` are all guarded). During a total outage this call raises and `main()` crashes before reaching the alert-aggregation (`:206-217`), the `logs` insert (`:219-224`), and — critically — the Telegram `notify()` call (`:226-238`) and the daily digest (`:242`). The one scenario `lessons.md` says must never again be silent ("silence must never again mean fine," 2026-05-23 lesson) is exactly the scenario this code path can't get past. **Fix**: wrap `:194-204` in the same `try/except Exception as e: alerts.append(...)` pattern used elsewhere in the file, so a DB-read failure becomes an alert instead of a crash. Low-risk, ops-only change — recommend for immediate human action, not auto-applied here per audit scope.

---

## CODE

### Risk gate — `api/services/risk_manager.py` (via @risk-auditor)

| Sev | Finding | Where |
|---|---|---|
| CRITICAL | Paper and live P&L/exposure share the same rows — `positions` has no `executor` column, so `_realized_pnl_since`, `_drawdown_exceeded`, `_open_exposure`, `_module_exposure` mix paper and live. Daily/weekly/drawdown gates can stay green while real USDC is down; paper resting orders also eat the real portfolio cap. | risk_manager.py:73-87,98-107,136-140,232,235,237,258-260 |
| HIGH | `module_bankroll()` fails **open** on a Supabase error — returns global bankroll instead of rejecting, widening the just-fixed per-module cap (dd077cc) back to the whole bankroll. Same bug class as the c762636 dust-floor fix, not yet applied here. | api/modules/shared/config_store.py:34-36 → risk_manager.py:222-226 |
| HIGH | Correlated-exposure cap (30%) matches `positions.market_id` (a condition_id) against `corr_key` (an auction slug) — never matches once orders fill, so the cap only sees resting orders. When slug is empty it degrades to a no-op (looser than the 15% single-market cap it's supposed to backstop). | risk_manager.py:122-123,206,215 |
| HIGH | All caps key off `config.bankroll = 1000.0` (a static constant), while modules size against Supabase `modules.budget`. Two denominators, never reconciled against actual wallet collateral (`clob.get_collateral_balance()` exists, used only by an acceptance script). | api/config.py:50 |
| MEDIUM | Hot path (`hot_path.py:102-112`) checks live-guard + breaker but not `halt.is_halted()`, and skips `risk_manager.check()` entirely (self-documented). Latent — `HotPath` isn't instantiated anywhere under `api/` today, but ships as-is. | api/services/hot_path.py:93-112 |
| MEDIUM | Two incoherent kill switches: `halt.py` (`global_halt`, cancels resting orders) vs `scripts/kill_switch.py` (`circuit_breaker`, is what the hot path actually reads); `--resume` on the latter wipes a genuine breaker trip. | halt.py; scripts/kill_switch.py:35-42 |
| MEDIUM | Halt is enforced only at the top of the engine cycle, not inside `check()`/`execute()` — any future direct caller bypasses it. | engine.py:101-107 |
| MEDIUM | Depth check sums bid+ask depth for both BUY and SELL orders, inflating the 30%-of-book allowance. | risk_manager.py:280-281 |
| MEDIUM | `spread_tol`/`min_edge` are loosened per-module via untyped `signal.metadata` with no allow-list — any module can widen its own gate (market_maker sets 0.40, several set `min_edge: 0.0`). | risk_manager.py:171 |
| MEDIUM | `aggregate_price_ceiling_ok` (D4 ceiling) is defined but only self-applied by `s2_basket_hold`; no other module is gated by it. | risk_manager.py:287; s2_basket_hold/decision.py:50 |
| MEDIUM | `tests/test_risk_manager.py` imports a `RiskManager` class that no longer exists — zero real test coverage of `check()`. | tests/test_risk_manager.py:4 |
| LOW | `scripts/step2_acceptance.py:123` calls `clob.place_post_only` directly with no paper/live guard and no risk pass. | scripts/step2_acceptance.py:123 |
| **Verified good** | Limit-only enforcement is SAFE — both order-submission paths (`place_post_only`, `post_signed`) run `validate_order` and set `post_only=True`; no market/FOK/FAK path exists anywhere in `api/`. Fail-closed core is SAFE (missing spread/edge, DB exceptions, unreadable book all reject). The c762636 dust-floor fix (module budget, not global bankroll) is genuinely fixed and not regressed. | clob.py:103-136; risk_manager.py:189 |

### Module architecture (via @qa-architecture-quality)

| Sev | Finding | Where |
|---|---|---|
| CRITICAL | Engine hardcodes a module name and imports its internals directly — `from api.modules.sports_sweep import data as sports_data`, `.eq("strategy","sports_sweep")` — a direct breach of CLAUDE.md rule 4. The generic fallback two blocks down (`:195-213`) already handles this correctly for every other module. | engine.py:186-192,235-251 |
| HIGH | Duplicate arb-pricing kernel in two modules (complete-set-taker + complement-pair-maker math), so a pricing fix means editing both. | arb_scanner/module.py:56-108; elon_late_arb/module.py:63-126 |
| HIGH | 9 of 10 modules import `api.services.*` (clob, risk_manager.Signal, position_manager) — the documented dependency direction is `services → modules`, not the reverse. `Signal` is a shared contract type living in the wrong layer. | e.g. elon_reversion/module.py:20-21 |
| HIGH | 5 modules query `orders` directly and re-implement resting-order dedupe that `risk_manager.check()` already does, with differing column sets. | sports_sweep/module.py:51-54; copytrader/module.py:86; lp_rewards/module.py:46; mirror_trader/module.py:72; s2_basket_hold/module.py:70 |
| HIGH | Dashboard bypasses the API entirely and parses engine log strings (`ilike("message","Cycle:%")`) coupled to the exact log format `engine.py` emits — a silent format change breaks the dashboard with no compile-time signal. | web/app/api/terminal/route.ts:22-99,76-77 ↔ engine.py:138-141 |
| MEDIUM | No shared Polymarket client — Gamma/CLOB base URLs redefined in 8 modules' `data.py`; `MODULE_ARCHITECTURE.md` claims this was already built ("Phase B DONE"). It isn't. | e.g. market_maker/data.py:14 |
| MEDIUM | CLAUDE.md rule 6 (per-module `BotHealthBanner`) is unimplemented — nothing in `web/` calls `/api/engine/health`. | api/routers/health.py:29 |
| MEDIUM | Frontend hardcodes module display copy by strategy name (`web/app/page.tsx:69-100`) instead of reading it from `BaseModule`. | web/app/page.tsx:69-100 |
| LOW | Docs badly out of date: `ARCHITECTURE.md` / `MODULE_ARCHITECTURE.md` still describe `truth_social/`, `elon_tweets/`, `spike_trading/`, `copy_trading/` — none exist; the 10 real modules aren't mentioned. | ARCHITECTURE.md:45-89; MODULE_ARCHITECTURE.md:21-50,104-156 |
| LOW | Orphan migrations (008–011, 014, 017–019) with zero code references; `retention.py:14-17` still cleans tables nothing reads. `demo` module auto-registers into the production `/modules` list (harmless, returns `[]`). | supabase/migrations/*.sql |
| **Verified good** | Zero cross-module imports across all 10 modules. Sealed structure 10/10 (all four required files present). Registry is fully name-branch-free (`pkgutil` discovery). Config isolation correct (`module_config:{module_id}` keys, no shared rows). | api/modules/__init__.py:14-61 |

### Backtest integrity (vs `.claude/agents/backtest-auditor.md`)

- **CRITICAL — RUN_META (commit `1a09866`, built 2026-07-22 specifically for this) is imported by zero backtest scripts** — not the 55 files under `pacing_backtest/`, not the 8 `scripts/canonical/backtest_*.py` files, nothing added since. By its own rule, every current backtest is a compliance failure, and the auditor's core enforcement mechanism has never actually run against a real script.
- **CRITICAL — `backtest/engine.py` (580 lines) is fully orphaned**: imported by nothing under `api/`, `tests/`, or `scripts/`; its only data source (`_DataMetricPulls/historical/{handle}/all_trackings.json`) was deleted in the 2026-05-28 canonical-layer consolidation. It would crash if invoked. It's still referenced by `.claude/agents/backtest-agent.md` (`from backtest.engine import run_backtest`), so deleting it isn't zero-risk without also updating/retiring that agent definition — left for human call, not auto-fixed here.
- **HIGH — maker-fill realism unconfirmed on pre-L2 data.** `scripts/canonical/backtest_spike_v2.py:116-144` fills ladder tiers whenever hourly OHLC low/high touches the price, crediting full notional instantly with no depth cap or queue model — on the canonical `prices` table, which CLAUDE.md itself says has no real L2 history before March 2026, while this backtest's universe starts September 2025. Same failure shape as the `phase_wh_maker.py` fill model already blacklisted for this reason (commit `14596d8`).
- **HIGH — no zero-edge control backtest exists** for the bracket strategies actually traded (the one control that exists, `crypto_sweep/phase1_efficiency.py`, is for unrelated BTC/ETH/SOL/XRP markets).
- **MEDIUM — fee model absent, not stated.** No backtest script models Polymarket fees at all; plausibly correct only because both legs are post-only maker orders (matches `executor.py:53,77`), but this is never declared as an assumption.
- Two now-moot bugs in the dead `backtest/engine.py` (fills at the model's own predicted probability rather than a real price; static constants applied with no walk-forward refit — textbook `global_fit` leak) — moot only because nothing calls it.

### Silent failures / dead code — clean overall

- No bare `except:` and no `.single()` calls anywhere in `api/`. No TODO/FIXME/XXX in any money-touching path (executor, risk_manager, position_manager, fills, order_state).
- LOW: `halt.py:53,60` — `except Exception: pass` around the Slack notify + audit-log insert after a halt/unhalt (the state flip itself, `:38`, correctly fails loud — only the alert-about-it can go silent).
- LOW: `engine.py:249` — a malformed `sports_sweep` config row silently drops that series from paper-fill coverage with no log line.
- Dead: `tests/test_engine.py`, `tests/test_copy_trading.py` reference removed classes/modules. `_ImportantConfigFiles/spike_trading_module_spec.md` specs a module that no longer exists. `HANDOFF_DELETE_BOT.md` (repo root, from an apparently-abandoned 2026-06-15 decommission attempt) is stale clutter now that the bot is clearly still live and being rebuilt as `feat/newbot-step1-skeleton`.

### Spec drift vs CLAUDE.md — CONFIRMED STALE

CLAUDE.md's "⭐ SPIKE TRADING" section (dated 2026-05-06) instructs every session to surface `spike_trading` bracket recommendations first. That module was **deleted in commit `06e64a3`, the first commit of this very branch** ("Step 1 skeleton"). None of the 10 live modules reimplement it — `elon_reversion` is a different strategy (OU mean-reversion fade, maker-buys NO). Only traces left: the spec doc, two unused migrations (`010_spike_positions.sql`, `013_signal_type.sql`), and `scripts/canonical/backtest_spike_v2.py`, whose docstring still points at a dead module path. **Recommend a human update CLAUDE.md** to remove or clearly mark this section retired — not changed here, since CLAUDE.md is a project-instructions file, not code.

### Tests

`python -m pytest -q` from repo root fails to collect (13 errors) — no `pytest.ini`/`testpaths`, so it also sweeps unrelated `_DataMetricPulls/**/*_test.py` research scripts with hardcoded paths and a missing dependency. No CI workflow runs pytest at all (`.github/workflows/` has only `sonarcloud.yml`). Scoped to `tests/` minus the three dead-import files above: **9 failed, 64 passed** — `test_executor.py` (7 failures, `LiveExecutor.__init__()` missing a `profile` kwarg the tests don't pass) and `test_signals.py` (2 failures, `kelly_sizing`/`rank_brackets` behavior drift). No evidence this suite gates anything today.

---

## Recommendations (human review — nothing below was applied by this audit)

1. **Now**: get Supabase back — check compute/disk health, hunt for a blocking query/lock, consider a restart (L-1).
2. **Now**: patch `scripts/watchdog.py:194-204` with a try/except so a DB-read failure becomes a Telegram alert instead of a silent crash (L-3) — small, ops-only, high value.
3. Separate paper vs live P&L/exposure (add `positions.executor` and filter every risk-manager aggregate by it) before any module goes live (C-1).
4. Make `module_bankroll()` fail closed on Supabase error (H-2); fix the correlated-exposure key mismatch (H-3); reconcile the static bankroll constant against real wallet collateral (H-4).
5. Move the engine off the sports_sweep special case onto the existing generic fallback (already correct two blocks down).
6. Wire `emit_run_meta` into at least the backtests actually informing live sizing, and build one zero-edge control, before trusting any backtest P&L number again.
7. Update or retire the Spike Trading section of CLAUDE.md; retire `backtest/engine.py` together with `.claude/agents/backtest-agent.md` (or repoint the agent at backtest-builder/backtest-auditor).
8. Fix or delete the three dead-import test files; fix `LiveExecutor`'s test/constructor mismatch; wire pytest into CI so this doesn't silently rot again.

No live trading logic, risk limits, or module behavior was modified by this audit — all findings above are recommendations only.
