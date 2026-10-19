# Weekly Audit — 2026-10-19

Branch audited: `feat/newbot-step1-skeleton` (live production code).
Live data source: Supabase project `xdonwowgqvmtrduikaon`, last 7 days unless noted.

## Summary

Nothing is actively trading right now, and that is intentional (owner paused every
module on 2026-09-07 after a losing paper-bench run). The engine process itself is
healthy. The main actionable findings are on the **code side**: the test suite has
silently rotted — three test files can't even be collected because they reference
classes/modules that no longer exist, which means `risk_manager.py` (the money-path
risk gate) currently has **zero working automated test coverage**. There's also a
large body of pre-`RUN_META` backtest scripts with no auditable provenance.

---

## LIVE FINDINGS

### HIGH — Test suite has 3 files that fail to even collect; risk_manager has no passing tests
`python -m pytest -q tests/` fails collection on:
- `tests/test_risk_manager.py` → `from api.services.risk_manager import RiskManager, Signal` — but `api/services/risk_manager.py` has no `RiskManager` class anymore (it's function-based: `check()`, `Signal`, `RiskVerdict`). The file is importing a dead symbol.
- `tests/test_engine.py` → `from api.services.engine import TradingEngine` — `api/services/engine.py` only defines `Engine`.
- `tests/test_copy_trading.py` → `from api.modules.copy_trading.decision import ...` — the module is named `api/modules/copytrader/`, not `copy_trading`.

Net effect: the risk gate that CLAUDE.md calls non-negotiable ("ALWAYS run all 15
risk checks before order placement") has **no passing regression test** today. A
future change to `check()` could silently break a cap and nothing in CI would
catch it. These are stale tests orphaned by refactors, not new bugs — but they've
clearly been broken for a while and nobody noticed because pytest wasn't even
installed in this environment (had to `pip install pytest -r requirements.txt`
to run anything).

**Recommendation:** rewrite `tests/test_risk_manager.py` against the current
`check()`/`Signal`/`RiskVerdict` API, `tests/test_engine.py` against `Engine`, and
either rewrite or delete `tests/test_copy_trading.py` depending on whether
`copytrader` has an equivalent `decision.py`. This is a CI-wiring fix, not a logic
change — explicitly flagging for human follow-up per the "never modify
risk/trading logic directly" rule, since fixing the tests still means writing
assertions about `check()`'s behavior.

### MEDIUM — 6 more test failures once collection succeeds (non-money-path)
With the 3 broken files excluded, `70 passed / 9 failed`:
- `tests/test_executor.py` — `TestPaperExecutor` (4 tests) patches `api.services.executor.open_position`, which doesn't exist on the module anymore; `TestLiveExecutor` (3 tests) calls `LiveExecutor(profile={...})` but `LiveExecutor.__init__` no longer takes a `profile` kwarg.
- `tests/test_signals.py::TestKellySizing::test_elapsed_100pct_zeros_kelly` — expects `kelly_pct == 0` at `elapsed_pct=1.0`, got `0.0171`. Either the test's expectation is stale or `kelly_sizing` regressed on full-elapsed clamping — needs a human call on which is right (this is signal-sizing logic, in betting-strategy skill territory).
- `tests/test_signals.py::TestRankBrackets::test_returns_top_3` — expects `len(result) <= 3`, got 5. Same ambiguity: did `rank_brackets` drop its top-3 cap, or is the test wrong?

Same pattern as the HIGH finding: drift between tests and implementation, not
necessarily live bugs, but it means `executor.py` and the sizing/ranking helpers
in `signals.py` are currently unverified by CI too.

### LOW — Backtest scripts predate RUN_META, no auditable provenance for ~115 of them
`_DataMetricPulls/pacing_backtest/` has 120 non-test `.py` scripts; roughly 115 of
them (everything before the `RUN_META` emitter landed in `1a09866`) have no
`emit_run_meta`/`RUN_META` reference. Per `.claude/agents/backtest-auditor.md`,
"a backtest with NO RUN_META is a class-C finding in itself" — the auditor's own
rule is to WARN and reconstruct the recipe manually rather than treat it as fatal,
so this isn't new or blocking, just worth tracking: any number quoted from one of
these older scripts should be re-run through a RUN_META-emitting rebuild before
being trusted for a live decision.

### INFO (no action) — Approval-health / "signals vs approved" check: not applicable this week
0 signals were generated in the last 7 days — see Module Health below. The
0-approved-while-signals>0 pathology this check exists to catch did not occur
because no signals exist at all right now.

### INFO (no action) — P&L, last 7 days
Only one position closed in the window: **Arb Scanner**, realized P&L **-$1.80**
(closed 2026-10-19 09:25 UTC, avg_price $0.15, size 0 — looks like a residual
dust-sized close, not a new trade; Arb Scanner has been `inactive` since
2026-09-07). No other module had P&L activity in 7 days — consistent with
everything being paused.

### INFO (no action) — P&L, all-time (worst-to-best by realized P&L)
| Module | Status | Budget | Realized P&L (all-time) | Positions |
|---|---|---|---|---|
| S2 Basket-Hold | inactive | $500 | **-$486.27** | 67 |
| Arb Scanner | inactive | $500 | **-$458.11** | 33 |
| Copytrader | inactive | $500 | **-$321.73** | 100 |
| Market Maker | inactive | $500 | -$35.36 | 4 |
| Sports Sweep | inactive | $500 | -$5.12 | 10 |
| elon_tweets, Mirror Trader, Elon Late Arb, truth_social, Elon Reversion, LP Rewards | inactive | $0 or $500 | $0.00 | 0–1 |

This matches the owner's 2026-09-07 note ("every module is loss-making on the
paper bench, -$1,217 on $10k... do NOT auto-revive"). S2 Basket-Hold, Arb Scanner,
and Copytrader account for -$1,266 of that between them. Nothing here contradicts
the pause decision; flagging only so the persistent-loser ranking is on record for
whenever revival is considered.

### INFO (no action) — Module health
**All 11 modules in `modules` are `status = inactive`.** Breakdown by
`inactive_reason`:
- `paused_by_owner` (7 modules: Market Maker, Sports Sweep, Arb Scanner, Elon
  Reversion, Elon Late Arb, S2 Basket-Hold, Copytrader) — since 2026-09-07,
  `inactive_detail` explicitly says "Do NOT auto-revive." **Honored correctly** —
  nothing in this audit found any code path that flips these back to active.
- `decommissioned` (2: elon_tweets, truth_social) — since 2026-07-11, row kept
  only to stop a `.single()`/PGRST116 tripwire; module code retired. Matches the
  "Daily Backfill Status Check" note in CLAUDE.md that Trump backfill is complete
  and no handle work is pending.
- `dead_thesis` (2: LP Rewards, Mirror Trader) — no `inactive_since` recorded
  (null), no detail. Minor: not harmful, but if someone wants to know *when* these
  died the metadata isn't there.

No module is currently emitting signals while never getting approved — because no
module is emitting signals at all (0 total in `signals` table in the last 7 days;
the all-time table has 343,830 rows but the last one is from 2026-09-07, which
lines up exactly with the pause).

### INFO (no action) — Engine liveness
Newest `Cycle:` log is 2026-10-19 13:05:24 UTC — **~4 minutes old at the time of
this audit**, well under the 20-minute staleness bar. The cycle body itself is
`{'modules': 0, 'signals': 0, 'approved': 0, 'paper_fills': 0, 'errors': 0}` on
every run — the engine loop is alive, it just has nothing to do because every
module is inactive. Two watchdog auto-restarts fired in the last 7 days
(2026-10-17 02:40 UTC and 11:25 UTC, both "engine not cycling (age=None)" →
`systemctl restart polybot.service`, both self-healed). Two restarts in one week
is a bit more than "quiet background noise" — worth a human skim of the Railway
deploy/crash logs around those two timestamps to see if there's a recurring
trigger, even though the watchdog handled it both times.

### INFO (no action) — Foreign writer check
No `logs` rows matching `%enabled_wallets%` in the lookback window (or ever, by
the broader query). No evidence of a legacy/foreign bot writing to this database.

---

## CODE FINDINGS

### Risk gate (`api/services/risk_manager.py`) — looks correct, no new issues found
Read the full 294-line file against the brief:
- **Fail-closed:** confirmed. All exposure/budget/PnL/drawdown checks run inside
  one `try/except Exception` that returns `RiskVerdict(False, "db_error:...")` on
  any failure (lines 192–241). The pre-DB checks (price/size/token_id/spread
  data/edge/dust floor) reject on missing data too, not just on explicit
  violation — e.g. `signal.spread is None or signal.best_ask is None` rejects
  before even checking tolerance (line 174).
- **Limit-only:** `Signal.price` is a required field used directly as the order's
  limit price; nothing in this file synthesizes a market order.
- **Caps coherent:** `max_single_market_exposure` (0.15) < `max_correlated_exposure`
  (0.30) < `max_portfolio_exposure` (0.50); `daily_loss_limit` (0.05) <
  `weekly_loss_limit` (0.10) < `max_drawdown` (0.15) in `api/config.py`. Ordering
  makes sense (tighter blast-radius caps are smaller).
- **Dust-floor denominator — already fixed, not a live bug:** the comment at
  lines 183–190 explicitly documents the exact bug class the task asked me to
  check for ("bankroll 10k -> $10 floor killed sub-$10 quotes, 2026-07-29") and
  the current code uses a flat `signal.notional < 1.0` absolute floor, correctly
  decoupled from `s.bankroll`. The per-module budget cap (line 219–226) separately
  and correctly scales against `module_bankroll(signal.module_id)` (the module's
  own budget), not the global bankroll. I did not find any gate in this file that
  mixes the two denominators.

No fixes applied here — flagging as clean on this pass, not proposing changes.

### Module isolation (`api/modules/*`) — compliant
- No cross-module imports found. Every `module.py` only imports
  `api.modules.base` (the shared base class, not a sibling module) or
  `api.modules.shared.*`.
- Every module directory (`arb_scanner`, `copytrader`, `demo`, `elon_late_arb`,
  `elon_reversion`, `lp_rewards`, `market_maker`, `mirror_trader`,
  `s2_basket_hold`, `sports_sweep`) has all four required files
  (`module.py`, `data.py`, `module_config.py`, `__init__.py`) per
  MODULE_ARCHITECTURE.md / CLAUDE.md.

### Backtest integrity — infra present; historical scripts lack provenance (see LOW finding above)
`BACKTEST_RULES.md`, the `run_meta.py` emitter, and `backtest-auditor.md`'s
4-pass structure are all in place and were added deliberately
(`ee35342`, `1a09866`). No new backtest files were added this week to audit
against THE WALL/fee-truth/zero-edge control directly — the only relevant finding
is the RUN_META-coverage gap noted above, which is already the auditor's own
documented and accepted class-C case.

### Silent failures — none found
- No bare `except: pass` in `api/`.
- No `.single()` calls anywhere in `api/` (the 2026-07-11 PGRST116 lesson about
  `.single()` tripping on empty results appears to have been fully remediated —
  the `elon_tweets`/`truth_social` decommission rows exist specifically because of
  that old bug, and no live code calls `.single()` anymore).
- No `TODO`/`FIXME`/`XXX`/`HACK` markers in `api/services/`, module entry points,
  or `api/modules/shared/`.
- Dead/orphan code: the 3 uncollectable test files and 2 drifted-assertion test
  files (see HIGH/MEDIUM above) are the orphan code found this pass — tests
  pointing at symbols/behavior that no longer exist. No orphan *production* code
  found.

### Tests
`python -m pytest -q` (after installing `pytest` + `requirements.txt`, neither of
which was present in this environment going in):
- 3 files fail to collect (see HIGH finding).
- Of the remaining files: **70 passed, 9 failed** (see MEDIUM finding).

---

## Recommendations for human review (no code changes made beyond this report)

1. Rewrite `tests/test_risk_manager.py`, `tests/test_engine.py` against the
   current `RiskManager`-less / `Engine` APIs; decide whether `test_copy_trading.py`
   maps to `copytrader` or should be deleted. This restores CI coverage on the
   risk gate — treat as urgent given CLAUDE.md's own "ALWAYS run all 15 risk
   checks" rule currently has no automated check behind it.
2. Resolve the `test_executor.py` / `test_signals.py` drift (6 failures) — for
   each, a human needs to decide "test is stale" vs "implementation regressed."
   I did not change `kelly_sizing`, `rank_brackets`, `LiveExecutor`, or
   `PaperExecutor` to make tests pass, per the no-direct-trading-logic-changes
   rule.
3. Consider adding `inactive_since`/`inactive_detail` for the two `dead_thesis`
   modules (LP Rewards, Mirror Trader) for audit-trail completeness — cosmetic,
   low priority.
4. Optional: skim Railway/systemd logs around 2026-10-17 02:40 and 11:25 UTC to
   see why the engine stopped cycling twice in one week, even though the
   watchdog recovered both times automatically.
5. No action needed on the module-pause decision itself — it's intentional,
   explicitly marked "do NOT auto-revive," and the code is honoring it correctly.
