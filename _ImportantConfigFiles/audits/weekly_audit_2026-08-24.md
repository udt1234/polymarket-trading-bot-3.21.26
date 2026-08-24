# Weekly Automated Audit — 2026-08-24 (UTC)

Scope: live production DB (Supabase project `xdonwowgqvmtrduikaon`, last 7 days unless noted) +
code on `feat/newbot-step1-skeleton` (the live bot; `master` is the retired old bot).
No trading logic, risk limits, or module behavior was modified. All items below are
recommendations for human review.

---

## LIVE FINDINGS

### CRITICAL — Retired `master`-branch bot is still writing to the shared production DB
The current branch (`feat/newbot-step1-skeleton`) has **zero** `.single()` calls and the string
`enabled_wallets` does not appear anywhere in it. Yet production `logs` show, every ~5 minutes,
continuously, for the full 7-day window:
- **3,186** `severity=error` rows: `Module truth_social error: {'message': 'Cannot coerce the
  result to a single JSON object', 'code': 'PGRST116', ... 'The result contains 0 rows'}` and the
  same for `elon_tweets` (roughly half each), latest at `2026-08-24 13:29:00`.
- **1,575** `Cycle: enabled_wallets=0 shadow_mode=False` decision-log lines, latest at
  `2026-08-24 13:28:59`.

Both patterns trace exactly to code that exists **only on `master`**:
- `master:api/modules/elon_tweets/module.py:81` — `sb.table("modules").select("*").eq("name",
  "Elon Tweets").single().execute()`
- `master:api/modules/truth_social/module.py:134` — same pattern for `"Truth Social Posts"`
- `master:api/modules/copy_trading/module.py:184-190` — `_fetch_enabled_wallets(...)` then logs
  `f"Cycle: enabled_wallets={len(wallets)} shadow_mode={cfg.get('shadow_mode')}"`

The `modules` table rows for these were marked `inactive_reason="decommissioned"` on
`2026-07-11 21:06:06`, with `inactive_detail`: *"Row inserted 2026-07-11 to stop PGRST116
tripwire from engine .single() fetch. Module code retired."* That fix does not work because a
**separate process — almost certainly a stray Railway deployment still running the `master`
branch — is still executing against this same database**, querying modules by old display names
(`"Elon Tweets"`, `"Truth Social Posts"`) that no longer match the current row names
(`elon_tweets`, `truth_social`), which is why every lookup returns 0 rows and crashes.

**Action needed (human):** find and shut down the stray Railway service running `master`. This
session has no browser/Railway dashboard access to do that directly. Until it's stopped, this
will keep spamming ~450 error-severity log rows/day (chewing into the 30-day `system` log
retention window) and — more importantly — means an old, unmaintained copy of the bot is live
against production data.

### CRITICAL — Two active modules have never emitted a signal
`Elon Reversion` (`0906aad5…`, status=`paper`, budget=$500) and `Elon Late Arb`
(`a28d8bad…`, status=`paper`, budget=$500) have **zero rows, ever**, in `signals` — not just in
the last 7 days, all-time. Both are otherwise configured as active paper strategies with budget
allocated. Needs a human check: are these wired into the engine's module registry / evaluate
loop at all, or dead on arrival since creation?

### CRITICAL — Arb Scanner: near-zero approval rate, dominant gate identified
Per the standing instruction to check this exact failure class: `Arb Scanner` produced **33,104**
signals in 7 days, of which only **29 were approved (0.09%)**. Rejection breakdown:
- `module_budget_cap_500` — **24,652 (74.5%)**
- spread-too-wide (`spread_X>tol_0.3`, ~100 distinct buckets) — **~7,700 combined (~23%)**
- `duplicate_resting_order` — 1,960
- `db_error:RemoteProtocolError` — 6

The dominant gate is the **per-module budget cap**, not a misconfigured global one — `risk_manager.py`
was already fixed on 2026-07-29 to scale the dust floor off the per-module budget rather than
global bankroll (see Code Findings, risk gate section — this part is *not* a new bug). What's
worth a human look: with 6 open positions on a $500 budget and a 74.5% budget-cap rejection rate,
confirm the module isn't stuck perpetually "full" against stale/never-expiring resting orders
rather than genuinely running near its allocated capacity.

### HIGH — `module_health` table is completely empty
`module_health` (documented: *"Populated by BaseModule._persist_health() at the end of each
evaluate() cycle. Dashboard banner reads this."*) has **0 rows**, despite modules having run
continuously for weeks. The dashboard's per-module health banner (CLAUDE.md rule: *"Each module
surfaces its own health"*) is currently blind for every module — `_persist_health()` is either
never called or silently failing. Needs a code-level check (not done in this pass — flagging for
follow-up).

### HIGH — Persistent losing modules
| Module | All-time realized P&L | Budget | Open positions | Closed positions |
|---|---|---|---|---|
| S2 Basket-Hold | **-$300.22** | $500 | 0 | 53 |
| Copytrader | **-$264.74** | $500 | 0 | 87 |
| Arb Scanner | -$78.10 | $500 | 6 | 7 |
| Market Maker | -$35.36 (7d: +$4.47) | $500 | 0 | 4 |
| Sports Sweep | -$5.68 | $500 | 0 | 8 |

S2 Basket-Hold is down 60% of its allocated budget; Copytrader is down 53%. Both are currently
flat (no open exposure) after accumulating the loss over 53 and 87 closed round-trips
respectively. All-time realized P&L across every module: **-$684.10** over 159 closed positions.
Worth a strategy-level review of whether either should stay in paper rotation as-is.

### HIGH — Market Maker: signal-generation loop re-emits already-resting orders
22,011 signals in 7 days, 8.34% approved. Dominant rejection: `duplicate_resting_order` —
**16,774 (76%)**. The module is re-proposing the same order every cycle even while one is already
resting on the book. Correctly rejected each time (not a safety issue), but it's a wasted-cycle /
noisy-signal-generation bug worth fixing in the module's own signal logic.

### MEDIUM — Circuit breaker trip count
`settings.circuit_breaker`: `{"trips": 69, "cooldown_until": "2026-08-14T22:45:09Z",
"consecutive_losses": 0}`. Cooldown has since expired (not currently tripped), but 69 lifetime
trips is a lot — worth trending this over time to see if it's concentrated in one module/period.

### MEDIUM — Module budgets sum to 3.5× the default bankroll
7 active-budget modules × $500 = $3,500 in per-module budget caps, against
`api/config.py:50` `bankroll: float = 1000.0` (default; may be overridden via env in production —
not verified here). If bankroll is anywhere near the default, per-module budget caps are not the
binding constraint for most modules most of the time — the portfolio-level cap
(`max_portfolio_exposure * bankroll`) is. Worth confirming this is the intended design.

### Engine liveness — OK
Newest `Cycle:` summary log: `2026-08-24 13:32:31` (DB `now()` at query time:
`2026-08-24 13:33:27`) — well under the 20-minute staleness threshold. Latest cycle body:
`{'modules': 7, 'signals': 32, 'approved': 0, 'paper_fills': 0, 'errors': 0}` — 0 approved that
cycle is consistent with the low aggregate approval rates above, not a new anomaly.

### Info — Supabase RLS advisory (out of requested scope, surfacing per tool policy)
4 tables have Row Level Security disabled and are fully exposed to the anon/authenticated roles:
`public.whale_movements`, `public.ghost_trap`, `public.ghost_trap2`, `public.ghost_trap3`. None of
these are in the trading-logic tables this audit was scoped to, so no further investigation was
done, but flagging since Supabase's own advisor surfaced it as `critical`. Remediation SQL
(**do not run without adding policies first, or all access to these tables will break**):
```sql
ALTER TABLE public.whale_movements ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ghost_trap ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ghost_trap2 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ghost_trap3 ENABLE ROW LEVEL SECURITY;
```

---

## CODE FINDINGS

### CRITICAL — Live fill reconciliation is built but never started
`api/services/fills.py` (`UserChannelStream`, `reconcile_open_orders()`) has no caller anywhere in
the running process. `api/main.py`'s lifespan only starts `Engine.start()` and
`tweet_collector.start()`; `Engine.cycle()` only sweeps **paper** fills
(`self.paper.check_fills(...)`, `engine.py:70`). `executor.py:63` even says outright:
*"Submitted != filled (B1). fills.py moves it forward."* — but nothing does.

**Impact:** every module is currently `status=paper`, so this has no live effect today. But the
moment any module is flipped to live/active, `LiveExecutor.execute()` (`executor.py:53`) will
submit real signed orders to the CLOB, and **nothing will ever move them from `submitted` →
`filled`, update `positions`/`trades`, or feed `position_manager`.** Real fills would go
completely untracked. This must be wired in before any module goes live — flagging with highest
severity given CLAUDE.md's own framing of this branch as the live production code.

### HIGH — Hot path execution is also unwired
`api/services/hot_path.py` (`PreSignLoop`, `HotPath`) is fully built but has no caller anywhere.
`engine.py:6` flags this itself: *"Hot path (Step 5) lives beside this, not inside it."* — likely
intentional given the branch name (`newbot-step1-skeleton`), but currently dead code.

### HIGH — Test suite: 3 files fail to even import; 9 more fail against current code
`python -m pytest -q` (after installing `requirements.txt`, which was not pre-installed in this
environment) hits **13 collection errors** before any test can run — 3 are real test/code drift,
the rest are non-test data-analysis scripts under `_DataMetricPulls/` and `scripts/canonical/`
being accidentally collected by pytest's default `*_test.py` glob (hardcoded Windows paths,
missing `google` package — not really tests, should be excluded from test discovery, e.g. via
`testpaths = tests` in a pytest.ini/pyproject.toml).

Real drift, once those are excluded:
- `tests/test_risk_manager.py` imports `RiskManager` — `api/services/risk_manager.py` is
  function-based (`check()`), no such class exists.
- `tests/test_engine.py` imports `TradingEngine` — no such name in `api/services/engine.py`.
- `tests/test_copy_trading.py` imports `api.modules.copy_trading` — that module doesn't exist on
  this branch; it's the **retired `master`-branch module name** (current branch's equivalent is
  `api/modules/copytrader`).

With those 3 files excluded, `tests/` runs 73 tests: **64 passed, 9 failed**:
- `TestPaperExecutor` (4 failures) and `TestLiveExecutor` (3 failures) — all fail because
  `api.services.executor` no longer has an `open_position` attribute to mock, and
  `LiveExecutor.__init__()` no longer accepts a `profile` kwarg. The executor was refactored;
  tests were not updated.
- `TestKellySizing::test_elapsed_100pct_zeros_kelly` — expects `kelly_pct == 0` at
  `elapsed_pct=1.0`; actual code (`signals.py:61-63`) intentionally floors the time-decay
  multiplier at 0.30, so sizing never fully zeros out even at 100% auction elapsed. Test name
  suggests the original spec was "fully zero at close" — needs a human call on which is correct
  (strategy-reviewer territory, not fixed here).
- `TestRankBrackets::test_returns_top_3` — expects `len(result) <= 3`; `rank_brackets()`
  (`signals.py:81`) defaults `top_n=5`. Same test/spec-drift pattern.

**Net: the safety-net for the three most money-critical modules (risk manager, engine, executor)
does not currently run at all**, and the parts that do run have real (if not necessarily
dangerous) drift against the implementation.

### MEDIUM — Engine hardcodes a module name (rule #4 violation)
`api/services/engine.py:238,242`, inside `_active_sports_series()`:
```python
mod = self.registry.get("sports_sweep")
...
rows = (sb.table("modules").select("id,status").eq("strategy", "sports_sweep")
        .neq("status", "inactive").execute().data) or []
```
Hardcodes the literal string `"sports_sweep"` twice to build paper-fill coverage, instead of a
generic `BaseModule` accessor. Scoped to one function, doesn't affect other modules today, but is
exactly the pattern CLAUDE.md rule #4 prohibits — would need editing if `sports_sweep` were
renamed or a second series-based module were added.

### MEDIUM — Backtest integrity
No `api/routers/backtest.py` or `api/services/backtest*` exists. Two separate backtest surfaces
found:
- `backtest/engine.py` (top-level, not under `api/`): **dead/unreachable** — zero importers
  anywhere in the repo, and it reads from `_DataMetricPulls/historical/`, a directory that was
  deleted 2026-05-28 during the canonical-data consolidation (per CLAUDE.md). If it were ever
  revived as-is it would also fail THE WALL: `_select_brackets` and the settlement loop both price
  against the model's own projected probabilities (`probs[b]` / `current_probs.get(b, 0)`), not
  an observed market price — i.e. it grades the model against itself. Zero fee modeling, no
  RUN_META. Currently unreachable, so no live risk, but should either be deleted or fixed, not
  left as a landmine.
- The **active** suite, `_DataMetricPulls/pacing_backtest/*.py` (54 scripts) governed by
  `BACKTEST_RULES.md`: of those, only `run_meta.py` (the emitter utility itself) references
  `RUN_META`/`emit_run_meta()` — the scripts that actually produce headline numbers
  (`trade_sim.py`, `bracket_hit_backtest.py`, `real_fill_v5.py`, `seesaw_v3.py`,
  `backtest_clean.py`, etc.) don't call it, despite `BACKTEST_RULES.md` mandating it. No
  zero-edge/null-strategy control was found anywhere in this suite either (grepped for
  `zero_edge`/`null_strategy`/`random_control`/`coin_flip`/`control_group` — no hits).
  `real_fill_v5.py` does use real bid/ask + a per-bucket depth cap, which is the right pattern, but
  fee-correctness wasn't fully traced — flagged for a follow-up, not confirmed broken.

### LOW — Silent failures in the halt (kill-switch) path
`api/services/halt.py:53` and `:60` — bare `except Exception: pass` with no logging, swallowing a
failed operator notification (line 53) and a failed audit-log write (line 60) on engine halt. The
halt mechanism itself (settings upsert + cancel_all) is not swallowed, so halting still works, but
an operator could believe the halt was logged/alerted when it silently wasn't.

### LOW — Stale scaffold module not deleted
`api/modules/demo/module.py:2` — docstring says *"Delete once S2 lands."* `api/modules/s2_basket_hold/`
already exists and is active. `demo/` is still present and auto-discovered by `ModuleRegistry` like
any real module. Per CLAUDE.md ("prefer deleting code over adding it") this should be removed —
not deleted in this pass since module removal changes registry composition and this audit is
report-only.

### LOW — Test discovery pollution
`python -m pytest -q` run from repo root collects one-off local analysis scripts
(`_DataMetricPulls/pacing_backtest/*_test.py`, `scripts/canonical/07_consistency_test.py`) as test
modules purely because of the `*_test.py` naming convention pytest defaults to. They fail to even
import (hardcoded Windows paths from a different machine, missing `google` package) and block a
plain `pytest -q` from completing. Recommend scoping test discovery to `tests/` via
`pyproject.toml`/`pytest.ini` (`testpaths = tests`) so CI/local runs aren't gated on unrelated
scripts.

### Verified clean — no findings
- **Cross-module imports**: zero hits across all 10 non-`shared` modules under `api/modules/`.
- **Module structure**: all 10 modules have the required `module.py` / `data.py` /
  `module_config.py` / `__init__.py`; all subclass `BaseModule`.
- **Config isolation**: every module's config is scoped per-module-id via
  `api/modules/shared/config_store.py`; no shared/default rows found.
- **`.single()` on possibly-empty results**: zero occurrences anywhere in `api/` or `scripts/` on
  this branch (the PGRST116 errors seen live come from the retired `master` process — see Live
  Findings above).
- **Bare `except: pass` in money paths**: `risk_manager.py`, `executor.py`, `clob.py`,
  `position_manager.py`, `order_state.py` all log via `log.exception` or use narrow typed catches
  with explicit fallback — no silent swallowing in sizing/risk/order-placement itself.
- **TODO/FIXME/HACK**: none found anywhere under `api/`.
- **Hardcoded secrets**: none; credentials load via `get_settings()`/env only.
- **Market vs. limit orders**: `clob.py` explicitly documents and enforces post-only limit orders
  only — no market/FAK path exists anywhere.
- **WebSocket reconnect backoff**: exponential backoff present in `tweet_stream.py` (1s→30s cap)
  and `fills.py` (1s→60s cap, though `fills.py` is currently unreachable — see CRITICAL finding
  above).
- **Risk gate fail-closed / correct denominators**: `api/services/risk_manager.py` fails closed on
  any DB error or missing spread/depth data; the per-module budget cap correctly reads
  `module_bankroll(signal.module_id)` (the module's own budget), not global bankroll. The dust
  floor is a flat $1 absolute floor, not a bankroll-scaled fraction — the code comment
  (`risk_manager.py:183-188`) documents this was exactly the "wrong denominator" bug this audit
  was asked to check for, already fixed 2026-07-29. No new instance of that bug found.

---

## Summary

| Severity | Live | Code |
|---|---|---|
| CRITICAL | 3 | 1 |
| HIGH | 2 | 2 |
| MEDIUM | 2 | 2 |
| LOW | — | 3 |

Top priority for human attention: **find and kill the stray `master`-branch deployment still
writing to production**, then wire up `fills.py` before any module goes live, then restore real
test coverage on `risk_manager` / `engine` / `executor`.
