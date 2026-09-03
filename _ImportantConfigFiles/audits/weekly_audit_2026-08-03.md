# Weekly Audit — 2026-08-03

Scope: LIVE production data (Supabase project `xdonwowgqvmtrduikaon`, last 7 days) + code on branch
`feat/newbot-step1-skeleton` (the live production bot; `master` is the retired old bot and is referenced
below only as the source of a live incident).

Read-only audit. No trading logic, risk limits, or module behavior was modified. All findings below are
recommendations for human review.

---

## Executive summary

1. **CRITICAL — the retired `master`-branch bot is still running in production**, writing decision-cycle
   logs into the exact same `module_id` as the new bot's live "Copytrader" module, continuously, right up
   to the moment of this audit.
2. **CRITICAL — live order fills are never reconciled.** `api/services/fills.py` (`reconcile_open_orders`,
   `UserChannelStream`) is not started anywhere in the running app. In live mode, submitted orders never
   advance past `status='submitted'`, so positions never open and budget is never released.
3. **CRITICAL — the arb strategy's hedge legs are structurally un-placeable.** The duplicate-order guard
   keys on `(module_id, market_id, bracket)` only; both legs of a complement-pair arb share that key, so
   the second leg is always rejected. Every "arb" position Arb Scanner has ever opened is actually a naked
   directional bet. This is the mechanical explanation for its -$78 all-time P&L.
4. **CRITICAL — the CLAUDE.md "Spike Trading" bracket table is unauditable and describes a module that
   does not exist.** Its source files (`arc_brief.md`, `arc_2day.csv`) are absent from the repo and were
   never committed; there is no `api/modules/spike_trading` on this branch; three mutually contradictory
   strategy specs exist in the repo, none live.
5. Every currently active module lost money over the last 7 days; the test suite has 13 collection errors
   because it still imports pre-refactor names (`copy_trading`, `TradingEngine`, `RiskManager`), meaning
   the money-path code (executor, risk manager) currently has **zero executing test coverage**.

No code changes are included in this PR beyond the report itself — see "Low-risk cleanup candidates"
at the end for items a human could safely action separately.

---

## PART 1 — LIVE (Supabase, last 7 days unless noted)

### 1.1 Foreign/legacy writer on the shared DB — CRITICAL, ACTIVE INCIDENT

The retired `master` branch (NOT the deployed `feat/newbot-step1-skeleton` code) contains
`api/modules/copy_trading/module.py:190`:
```python
f"Cycle: enabled_wallets={len(wallets)} shadow_mode={cfg.get('shadow_mode')}",
```
This exact string is being written to `logs` right now:
- 1,971 rows in the last 7 days, `log_type='decision'`, spaced ~5 minutes apart, `earliest 2026-07-27
  13:34:02`, **`latest 2026-08-03 13:29:00`** — i.e. still running at the moment this audit ran.
- All 4,032 all-time rows of this message carry **`module_id = 2611efa9-8042-4b16-9b67-b70e60460b1f`**,
  which is the *exact same UUID* as the live `modules.name = 'Copytrader'` row (currently `status='paper'`,
  `budget=$500`), spanning 2026-07-20 → now.

The new bot's own "Copytrader" module (`api/modules/copytrader/`) is a different, rewritten
implementation. Two independent, unsynchronized codebases are both actively writing into the identical
module row in the shared database.

**Why this matters:** Copytrader is currently `status='paper'`, so real capital is not yet doubled. But
if a human flips Copytrader to `active` (as the normal "promote a healthy module" workflow), **both bots
would place real orders against the same $500 budget with no shared state**, and the module's own signal
counts / approval rate / P&L (3,141 signals, 85 approved, +$7.32 all-time) may already be an unreconcilable
mix of both bots' decisions — any read of "is Copytrader profitable" for a promotion decision is unreliable
until this is resolved.

**Recommendation:** Locate and stop the old bot's deployment (very likely a separate Railway service still
running `master`) immediately. Do not flip Copytrader — or any module — to `active` status until confirmed
stopped. This audit has no Railway/infra tool access to check or stop the deployment directly.

### 1.2 Approval health

| Module | Signals (7d) | Approved | Approval rate |
|---|---|---|---|
| Arb Scanner | 39,660 | 58 | 0.15% |
| Market Maker | 5,966 | 86 | 1.4% |
| Copytrader | 3,141 | 85 | 2.7% |
| S2 Basket-Hold | 558 | 244 | 43.7% |
| Sports Sweep | 457 | 27 | 5.9% |

Arb Scanner's rejection reasons (7d): `module_budget_cap_500` 22,776; `stake_below_floor` 6,427;
`circuit_breaker` 2,760; `duplicate_resting_order` 2,298; ~15 distinct `spread_X>tol_0.3` reasons summing
to ~4,900 more.

**Timeline cross-check against the last commit (`c762636`, 2026-07-29, "decouple dust floor from global
bankroll"):**
- `stake_below_floor`: 1,875 (7/26) → 3,374 (7/27) → 2,859 (7/28) → 2,115 (7/29) → **zero every day since**.
  This confirms the 2026-07-29 fix worked as intended — this was the CLAUDE.md-flagged
  "dust floor scaled by global bankroll not module budget" bug, and it is now fixed.
- `module_budget_cap_500`: 215 (7/26) → 1,243 → 1,650 → 3,025 → **5,672 (7/30)** → 4,993 (7/31) → 2,195 (8/1)
  → 2,248 (8/2) → 2,235 (8/3). This kept climbing straight through and after the 7/29 fix and remains the
  dominant rejection reason today. **This is a separate, still-open bug** — see Part 2.1 for root cause
  (the risk-gate audit traced it to double-counted partial fills and un-decremented stale resting quotes,
  not a wrong denominator).
- `duplicate_resting_order`: negligible 7/26–7/29 (143/258/29/2), then **891 (8/1), 733 (8/2), 537 (8/3)**
  — a new spike with no corresponding code change (no commits since 7/29). See Part 2.1 — this is the
  arb-hedge-leg self-block, and it worsens as more resting orders accumulate over time.

### 1.3 P&L (realized), last 7 days vs all-time

| Module | Closed (7d) | Realized P&L (7d) | Realized P&L (all-time) | Open positions |
|---|---|---|---|---|
| S2 Basket-Hold | 20 | **-$181.20** | -$145.10 | 2 |
| Arb Scanner | 6 | -$76.35 | -$78.10 | 5 |
| Market Maker | 1 | -$39.83 | -$39.83 | 0 |
| Sports Sweep | 4 | -$6.96 | -$6.64 | 0 |
| Copytrader | 28 | -$10.71 | +$7.32 | 11 |

Every active module lost money in the last 7 days; combined 7-day realized P&L across active modules is
**-$315.05**. S2 Basket-Hold is the largest and fastest-growing loser (7-day loss exceeds its all-time
cumulative loss, meaning it was net-positive before the last week and has since given that back plus more)
— worth a dedicated look at what changed for this module around 2026-07-27.

### 1.4 Module health

Inactive modules and reasons (all look intentional, no "bad" reasons found): `elon_tweets` /
`truth_social` — `decommissioned` (2026-07-11); `LP Rewards` / `Mirror Trader` — `dead_thesis`.

**Elon Late Arb** and **Elon Reversion** (both `status='paper'`, created 2026-07-24) emitted **zero**
signals in the last 7 days. Code inspection shows both are gated to only evaluate inside the auction's
final `window_hours` (a "last-6h" design, by name and docstring) — so zero signals over an arbitrary
7-day window is not necessarily a bug. However, for a strategy meant to fire in the final 6h of every
~2-day Elon auction, zero signals across a full week is worth a closer look (confirm `data.live_elon_event()`
is actually returning events and `bracket_full_books()` is returning ≥2 books) — flagged MEDIUM, not
confirmed broken.

### 1.5 Engine liveness

Newest `system`-type `Cycle:` log at time of audit: `2026-08-03 13:24:29` (audit ran ~13:2x-13:5x same
day) — well under the 20-minute staleness threshold. Engine is alive. Cadence is ~5 minutes, consistent
with `default_interval`.

### 1.6 Settings

- `circuit_breaker`: `trips=56` (cumulative), `cooldown_until` in the past relative to now (not currently
  tripped), `consecutive_losses=0`.
- `global_halt`: `{"halted": false, "reason": "selftest_done"}` — not halted.
- Two `alert_repeated_errors` entries from 2026-06-17 record `"Cannot coerce the result to a single JSON
  object"` (PGRST116, a `.single()`-on-non-singleton-result error) for the now-decommissioned `elon_tweets`
  and `truth_social` modules. The code-quality audit (Part 2.3) confirmed **zero `.single()` calls exist
  anywhere in the current codebase** — this was fully removed with those modules' retirement, not a live
  risk today.

---

## PART 2 — CODE (branch `feat/newbot-step1-skeleton`)

### 2.1 Risk gate (`api/services/risk_manager.py`)

Full agent report is authoritative; key points folded into this summary:

**Direct answer on `module_budget_cap_500`:** the denominator is correct — `module_bankroll(module_id)`
reads the real per-module `modules.budget` ($500 for Arb Scanner), not global bankroll. The bug is in the
**numerator** (`_module_exposure`, `risk_manager.py:90-107`):
1. Partial fills are double-counted — a half-filled order's full original `size * price` is counted as
   exposure *and* the position created by the fill is counted again (`executor.py:118-136` never updates
   `size` on partial fill; `size_filled` is written but never read by risk_manager.py).
2. Resting orders that never fill hold budget hostage — the TTL sweep that would release them
   (`engine.py:148-169`) is paper-only, BUY-only, and runs every 6h; live orders are never released at all
   (see CRITICAL #2 below — they can't be, since they never leave `submitted`).
3. `duplicate_resting_order` is checked before `module_budget_cap` in the gate order, so the 22,776
   budget-cap rejections are for *different* brackets than the module's 5 real positions — consistent with
   phantom exposure from (1)+(2), not real over-deployment.

**CRITICAL — arb hedge legs always reject each other.** The duplicate guard keys on
`(module_id, market_id, bracket, side='BUY')` (`risk_manager.py:197-203`), but the complement-pair arb
(`arb_scanner/module.py:100-108`) emits its YES and NO legs under the identical `market_id`+`bracket`,
differing only in `token_id`. The engine evaluates signals sequentially in one loop
(`engine.py:120-130`), so the second leg is rejected every time. **Every Arb Scanner position is a naked
directional bet, not a hedge** — this is the mechanical cause of both the -$78 P&L and the 2,298
`duplicate_resting_order` rejections.

**CRITICAL — live order lifecycle is never driven.** Neither `fills.reconcile_open_orders()` nor
`fills.UserChannelStream` is started by `api/main.py` or `api/services/engine.py` — their only callers
anywhere in the repo are in `scripts/step2_acceptance.py`. `LiveExecutor.execute()` writes
`status='submitted'` and nothing ever advances it. Since position effects only fire on `confirmed`
(`order_state.py:80-81`), **a live order would never open a position, and would permanently consume its
module's budget.** This blocks going live on any module today, independent of the paper-mode symptoms
above.

**Other HIGH findings (see full agent report for file:line detail):**
- Correlated-exposure check matches positions on `market_id` only but the cap is keyed on
  `auction_slug` when present — for any slug-tagged module (Arb Scanner always sets one), correlated
  exposure is silently under-counted. Fails open on a stated non-negotiable.
- Several DB reads that feed loss/drawdown limits (`_realized_pnl_since`, `_open_exposure`,
  `_correlated_exposure`, `_drawdown_exceeded`) are unpaginated `select()` calls with no range — once row
  counts exceed PostgREST's default page cap, these sums silently truncate and loss limits fail open with
  no error. (~5-7 unbounded queries × 39,660 signals/week for Arb Scanner alone is also a plausible
  contributor to the Supabase Disk-IO incident referenced in CLAUDE.md's retention-policy section.)
- Exit/SELL signals bypass every gate including the duplicate check and the kill switch
  (`risk_manager.py:156-157`); Market Maker emits a full-position SELL every cycle with no
  `claim_for_exit` call outside the `resolve_at` path, risking stacked duplicate SELLs / net-short
  exposure in live mode.
- Gate inputs (`spread`, `edge`, `best_bid/ask`) are module-self-attested and can be self-loosened via
  `metadata` overrides; Arb Scanner hardcodes `spread=0.0` for its complete-set leg, bypassing the spread
  gate outright for that branch.
- No settlement-decay gate exists at all (documented in `NEW_BOT_PLAYBOOK.md` as required; survives only
  in a dead test file).
- All portfolio-level caps (single-market 15%, correlated, portfolio, daily/weekly loss, drawdown) scale
  off a hardcoded `bankroll=1000.0` config constant, never reconciled against real wallet collateral
  (`clob.get_collateral_balance()` is called only from an acceptance script, never the risk path).
- The circuit breaker is global across all modules, not per-module — paper losses in one module can halt
  every other (including live) module.
- **Risk-gate test coverage is fake**: `tests/test_risk_manager.py` imports a `RiskManager` class that no
  longer exists in `api/` — zero executable test coverage of the live gate (confirmed independently by
  this session's own `pytest` run, see 2.5).
- Confirmed SAFE: every order path is post-only/limit through `clob.place_post_only`, no market/FAK path
  exists; missing-data/DB-error paths reject (fail closed) except the two items above; no hardcoded
  credentials.

### 2.2 Module architecture (`api/modules/*`)

Full agent report is authoritative. Headline: **module sealing itself is intact** — zero cross-module
imports found anywhere across all 10 packages, all required files present. The real damage is elsewhere:

- **CRITICAL — engine hardcodes a module name, violating CLAUDE.md rule 4.** `api/services/engine.py:188,
  238, 242, 248` imports `api.modules.sports_sweep.data` directly, does `registry.get("sports_sweep")`,
  filters `.eq("strategy", "sports_sweep")`, and reads a `sports_sweep`-specific config key
  (`series_ids`) — while every other module goes through the generic, module-agnostic path
  (`engine.py:202-213`) that this branch should be refactored to match.
- **CRITICAL — registry keyword collisions can silently misroute a module's signals to the wrong
  strategy.** `copytrader` claims keywords `"copy"`/`"whale"`; `mirror_trader` claims
  `"mirror"`/`"copy"`/`"whale"` — a DB row matched by substring fallback (`api/modules/__init__.py:56-60`)
  could bind to the wrong module's code, budget, and config.
- **HIGH — a real import cycle**: modules import `api.services.risk_manager.Signal` /
  `api.services.clob.snap_price`, while `risk_manager.py` imports back into
  `api.modules.shared.config_store`. Survives only because the risk_manager import is function-local.
  `Signal`/`snap_price`/`open_positions` are contracts and belong in `shared/`, not `services/`.
- **HIGH — duplicated strategy logic**: `copytrader/module.py` reimplements
  `s2_basket_hold/decision.py`'s entire projection→Kelly pipeline line-for-line; `arb_scanner` and
  `elon_late_arb` independently implement the same arb math. Per MODULE_ARCHITECTURE.md §7 this belongs
  in `shared/`.
- **HIGH — no shared Polymarket client**: `GAMMA`/`CLOB` base URLs are re-declared in 8 different
  module `data.py` files, bypassing the proxy-aware helper that was supposed to centralize this
  (mandated in MODULE_ARCHITECTURE.md and NEW_BOT_PLAYBOOK.md but never built).
- MEDIUM: 5 modules hand-roll the same "my resting BUYs" query; `market_maker` hardcodes gate values
  that make its own `module_config.py` fields dead; risk-gate metadata overrides use 3 different
  competing key names across modules; the web dashboard bypasses the API layer and recomputes fill
  semantics in TypeScript, a second source of truth for domain logic.
- LOW/doc-drift: `ARCHITECTURE.md` and much of `MODULE_ARCHITECTURE.md`'s method list describe the old
  retired bot, not this codebase — both need a rewrite; several `supabase/migrations` created tables
  (`truth_social_posts`, `elon_tweets`, `copy_trading_*`, etc.) that zero current code reads, and
  `retention.py` runs a daily DELETE against tables nothing writes to.

### 2.3 Silent failures / dead code / spec drift

Full agent report is authoritative. Headline: **`.single()`/PGRST116 pattern is fully clean** — zero
such calls anywhere in `api/`, `scripts/`, `web/`; every single-row read uses `.limit(1)` with a guarded
unwrap. The 2026-06-17 historical errors came from the now-deleted `elon_tweets`/`truth_social` code.

- **CRITICAL — `api/services/fills.py` is orphaned** (cross-confirms the risk-gate finding above from
  an independent read): its two entry points have no caller anywhere in `api/main.py` or `engine.py`.
- **HIGH — `api/services/hot_path.py`** (126 lines): not imported anywhere, and its own comments confirm
  it signs orders with **no risk_manager.check() call at all** — a live-order path that bypasses every
  gate if it were ever wired in. Currently dead code, but flagged as a loaded gun.
- **HIGH — registry keyword collisions** (same finding as 2.2, independently found).
- **HIGH — `module_bankroll()` fails open on a Supabase error**, returning the *global* bankroll instead
  of raising, which would silently inflate every module's effective budget cap on a transient DB error —
  contradicts risk_manager's own stated fail-closed design.
- MEDIUM: ~450 LOC of orphan files with zero importers (`feed_guard.py`, `l2_history.py`,
  `parquet_archive.py`, `heartbeat.py`, the entire `demo/` module — whose own docstring says "delete once
  S2 lands," and S2 has landed); the two Elon Late-Arb/Reversion data fetchers are byte-identical
  duplicates that also skip the shared discovery layer's closed-market filter; a top-of-book fetcher is
  duplicated 4 times; a global halt engaging currently produces no operator-visible log record
  (`halt.py:53-61` swallows the notify/audit-log failure).
- LOW: several unused config keys; an unbounded in-memory set in the tweet stream that never evicts in a
  long-running process; an abandoned "legacy price stop-loss (default OFF)" code path in `sports_sweep`.
- Confirmed compliant: no TODO/FIXME/XXX anywhere in `api/`; limit-orders-only is structurally enforced
  (no market/FAK path exists in `clob.py`); exponential backoff present on both WS reconnects and CLOB
  retries; no hardcoded credentials; dual live-mode guard present in the executor.

### 2.4 Backtest integrity (audited against `.claude/agents/backtest-auditor.md` / THE WALL)

Full agent report is authoritative.

- **BLOCK/UNAUDITABLE — CLAUDE.md's "Spike Trading" bracket recommendation table.** Its cited sources
  (`_DataMetricPulls/elon_arc_analysis/arc_brief.md`, `arc_2day.csv`) **do not exist anywhere in this
  repo or its git history** — not gitignored, not committed, not found on disk. There is **no
  `api/modules/spike_trading` on this branch at all** — the module the section describes isn't
  implemented. Three separate, mutually contradictory Spike-strategy specs exist in the repo (a 2026-05-12
  markdown spec with a take-profit ladder, and two committed-but-uncertain backtest scripts with
  different ladder parameters), none of them live. **Recommend removing or clearly re-labeling this
  CLAUDE.md section as "unvalidated / source missing"** until the source files are regenerated/committed
  and one real module is built to match one spec.
- **WARN, with two FATAL sub-findings, on the live `sports_sweep` module config** (`module_config.py`):
  `decided_winrate: 0.985` prices every real entry's edge but does not match any number any script
  actually emits — the one empirical figure on record (~98% at a 0.95 threshold) predates the live
  config's stricter 0.97 threshold, and nothing was re-run to confirm the number still holds at 0.97.
  Separately, `use_win_prob: True` (the live default) routes live pricing through a continuous
  win-probability model (`shared/game_state.py`) that **has no backtest anywhere in the repo** — it
  postdates every existing backtest script. Recommend re-running the phase6/phase7 scripts filtered at
  the actual live threshold, and backtesting (or disabling) `use_win_prob` before trusting it further.
- Systemic: **zero of the ~64 backtest scripts in the repo emit a RUN_META footer**, despite the
  convention existing — every future audit must manually re-derive provenance until this is retrofitted.
- Confirmed still-open from the repo's own `BACKTEST_RULES.md` status log: `reversion_study.py` still
  uses a forward-looking `burst_after(t)` condition as a selection filter (a WALL violation, previously
  flagged, not yet fixed).
- Confirmed clean: no `resample(`/`.rolling(center=True)`/fixed-bar leaks found across all ~64 scripts
  (the 7 `.rolling()` hits found are all trailing/causal windows); the sports_sweep backtest's fee model
  matches the audited Polymarket fee schedule and correctly labels its taker-volume estimate as an upper
  bound rather than a guarantee.

### 2.5 Test suite

`python -m pytest -q` (after installing missing deps — `pytest`, `pytest-asyncio`, and the full
`requirements.txt` were not pre-installed in this environment): **13 collection errors, 9 failed, 64
passed.**

Root cause of most failures: **the test suite predates a refactor that this branch's own git log confirms
already happened** (module rename `copy_trading` → `copytrader`, `Engine` class rename from
`TradingEngine`, `risk_manager.py` restructured away from a `RiskManager` class, `LiveExecutor`
constructor signature changed). Specifically:
- `tests/test_copy_trading.py`, `tests/test_engine.py`, `tests/test_risk_manager.py` fail to even import.
- `tests/test_executor.py`: 7/7 tests fail — `LiveExecutor(profile=...)` no longer matches the current
  constructor; `api.services.executor.open_position` doesn't exist as an attribute to patch.
- Also failing outside `tests/`: several `_DataMetricPulls/pacing_backtest/*_test.py` files hardcode a
  Windows path (`C:\Users\darwi\...`) instead of a relative repo path, and one canonical consistency test
  imports `google.oauth2` which isn't installed.

**This means the money-path code (executor, risk manager, engine) currently has zero executing automated
test coverage** — any CI gate relying on `pytest` passing would either be silently skipping these files
or already red. Two of the failures on tests that *do* still import look like genuine logic questions
worth a second look rather than pure staleness:
- `test_elapsed_100pct_zeros_kelly` (`tests/test_signals.py`): expects `kelly_sizing(...,
  elapsed_pct=1.0)["kelly_pct"] == 0` (no new sizing once an auction's time has fully elapsed); actual
  result is `0.0171`, not zero.
- `test_returns_top_3` (`tests/test_signals.py`): expects `rank_brackets(...)` to cap at the top 3
  brackets; it currently returns all 5.

**Recommendation:** either restore test coverage for the current API surface (executor, engine,
risk_manager) as a priority follow-up, or explicitly acknowledge in CI config that these files are
known-stale so a red pytest run isn't silently ignored.

---

## Ranked action items for human review

| # | Severity | Item | Source |
|---|---|---|---|
| 1 | CRITICAL | Stop the retired `master`-branch bot — it is still live, writing into the same `Copytrader` module_id as the new bot | Live DB (1.1) |
| 2 | CRITICAL | Do not enable live trading on any module until `fills.py` reconciliation is wired into `main.py`/`engine.py` | Code (2.1, 2.3) |
| 3 | CRITICAL | Fix the arb duplicate-order guard to allow both hedge legs (e.g. key on `token_id` not `bracket`) — Arb Scanner cannot currently hedge at all | Code (2.1) |
| 4 | CRITICAL | Re-validate or retract the CLAUDE.md Spike Trading bracket table — its source data doesn't exist and the module isn't built | Code (2.4) |
| 5 | HIGH | Fix `_module_exposure` double-counting of partial fills + release stale resting-order exposure, to stop `module_budget_cap_500` from starving Arb Scanner | Code (2.1), Live (1.2) |
| 6 | HIGH | Fix correlated-exposure `market_id`-vs-`auction_slug` key mismatch (fails open) | Code (2.1) |
| 7 | HIGH | Re-run `sports_sweep`'s backtest at its actual live 0.97 threshold, or backtest `use_win_prob` before trusting it | Code (2.4) |
| 8 | HIGH | Restore/rewrite the risk-manager, engine, and executor test suites against the current API | Code (2.5) |
| 9 | HIGH | Refactor `engine.py`'s hardcoded `sports_sweep` branch to the generic module-agnostic path | Code (2.2, 2.3) |
| 10 | HIGH | Fix registry keyword collisions (`copy`/`whale`/`mirror`) before they misroute a module | Code (2.2, 2.3) |
| 11 | MEDIUM | Investigate S2 Basket-Hold's -$181 swing over the last 7 days | Live (1.3) |
| 12 | MEDIUM | Confirm Elon Late Arb / Elon Reversion are actually evaluating (not silently stuck) — zero signals in 7 days | Live (1.4) |
| 13 | MEDIUM | Consolidate duplicated strategy math (copytrader/s2_basket_hold, arb_scanner/elon_late_arb) into `shared/` | Code (2.2) |
| 14 | MEDIUM | Add pagination to the risk manager's loss/drawdown/exposure queries before they silently truncate | Code (2.1) |
| 15 | LOW | Retrofit RUN_META into existing backtest scripts | Code (2.4) |

## Low-risk cleanup candidates (not applied in this PR — for human action)

These look safe (no live trading/risk behavior change) but are left for a human to action, per this
audit's read-only mandate:
- Delete `api/modules/demo/` (its own docstring says "delete once S2 lands"; S2 has landed; not imported
  by any live path beyond registry auto-discovery).
- Delete orphan scripts for decommissioned modules: `scripts/backfill_truth_social.py`,
  `scripts/verify_post_count.py`.
- Delete unused `shared/` files with zero `api/` importers: `feed_guard.py`, `l2_history.py`,
  `parquet_archive.py` (note: CLAUDE.md's retention section says `parquet_archive.read_table_range` is
  "already-wired" for `price_timing.py`/`whale_snapshot.py` — re-verify those two callers still exist
  before deleting; the audit agent found zero importers under `api/` but did not check those two files
  specifically).
- Rewrite `_ImportantConfigFiles/ARCHITECTURE.md` and the module-list/method-list sections of
  `MODULE_ARCHITECTURE.md` — both currently describe the retired old bot's module set, not this one.
