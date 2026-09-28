# Weekly Audit — 2026-09-28

Instructed branch: `feat/newbot-step1-skeleton` ("the live production code... NOT master, the retired old bot").
**This instruction is contradicted by the evidence below (P-1).** The CODE section audits both branches;
the LIVE section is branch-agnostic (Supabase project `xdonwowgqvmtrduikaon`).

## TL;DR

- **P-1 CRITICAL (process) — the branch this task is told is "live" is not what's actually deployed.**
  `feat/newbot-step1-skeleton` is 77 commits behind `master` and is missing safety fixes that are
  demonstrably live right now. Six prior weekly audits (2026-07-29 → 2026-08-31) were all merged into
  `master`, not this branch. See P-1 below before trusting any branch-specific finding in future audits.
- **C-1 CRITICAL (code, on the instructed branch) — a real, currently-dormant landmine.**
  `feat/newbot-step1-skeleton`'s `scripts/watchdog.py` will auto-revive every `paused_by_owner` module
  to paper mode within 15 minutes of running, directly contradicting the owner's explicit
  "Do NOT auto-revive" instruction. `master` already fixed this. If anyone ever redeploys from
  `feat/newbot-step1-skeleton` (plausible — it's the branch this task calls "live"), the fix regresses.
- **L-1 (informational, not a bug) — all 11 modules have been paused for 3 weeks, on purpose.** Owner
  paused everything 2026-09-07 18:27 UTC after paper-bench losses (-$1,217/$10k); explicitly marked
  "Do NOT auto-revive." Confirmed still in that state, confirmed intentional, confirmed correctly
  reported by the (master) watchdog as a note, not an alert. No action needed unless the owner wants
  to revisit it.
- **B-1 HIGH (code, both branches — file is identical) — `taker_speed_sweep.py` substitutes 0.5 for
  missing vwap instead of excluding the row, and emits no RUN_META.** Any number from it is unaudited
  by construction; do not quote it.
- Module isolation is clean on both branches. No foreign-writer bot in `logs`. No hardcoded secrets,
  no market orders, no bare `except: pass` in money-touching paths.
- Test suite (on `master`): 3 of ~10 test files fail to even collect (stale imports — `TradingEngine`,
  `RiskManager`, `api.modules.copy_trading` no longer exist under those names); of the tests that do
  collect, 9/79 fail, concentrated in `test_executor.py` (API drift, `LiveExecutor(profile=...)` no
  longer a valid kwarg) and two `test_signals.py` assertions that look like genuine logic mismatches
  worth a second look (S-1).

---

## P-1. CRITICAL — Branch-of-record mismatch between this task's instructions and actual production

This task states: *"the LIVE production code is branch `feat/newbot-step1-skeleton` (NOT master, the
retired old bot)."* Every piece of evidence gathered this session says the opposite:

- `git log feat/newbot-step1-skeleton..master --oneline` returns **77 commits**; `master..feat/newbot-step1-skeleton`
  returns **0**. `feat/newbot-step1-skeleton` is frozen exactly at its merge-base with `master`
  (commit `4820dd3`) — it has not moved since master's "new maker-only bot" branch was merged in
  (PR #95) and then continued forward without this branch.
- Master's tip (`4279435`, 2026-09-11, *"fix(watchdog): bench-paused is a NOTE, not a red alert"*)
  changes `scripts/watchdog.py`'s log message for the zero-active-modules state to exactly
  `"watchdog: healthy (bench paused: 0 active modules, not trading by design)"`. That exact string
  does not exist anywhere in `feat/newbot-step1-skeleton`. It **is** the message currently being
  written to `public.logs` every ~15 minutes right now (last seen 2026-09-28 13:37:28 UTC). The
  running watchdog is executing master's code, not this branch's.
- Master also already contains the fix for C-1 below (`paused_by_owner` added to the auto-revive
  skip-list, commit `59da928`) — which matches the live DB state (modules have stayed paused for
  3 weeks despite a watchdog that runs every 15 min and would otherwise revive them).
- `_ImportantConfigFiles/audits/` on `master` contains six prior weekly audits (2026-07-29 through
  2026-08-31), each merged via PR into `master`. `feat/newbot-step1-skeleton` has zero audit history.
  The 2026-08-31 audit's own header says *"Branch audited: `feat/newbot-step1-skeleton` (live
  production code)"* — so this mismatch (audit the skeleton branch, but land every resulting fix on
  `master`) has been the recurring pattern for at least a month, with `feat/newbot-step1-skeleton`
  quietly falling further behind each cycle instead of receiving the fixes.

**This audit's CODE section below therefore covers `master` as the de-facto live branch**, since
auditing a branch nothing is currently running against would defeat the purpose of the exercise. The
instructed-branch findings (C-1) are reported separately because they represent a live risk *if that
branch is ever the one actually deployed* (which the task's own instructions assert it is).

**Recommended action (human):**
1. Confirm in Railway which branch/commit is actually deployed right now — do not take either this
   task's instructions or this audit's inference as ground truth without checking the dashboard.
2. Fix the stored prompt on the "Polybot Weekly Audit" trigger (`trig_01HEEJGXeecuvEog5XQNEMvJ`) to
   name the correct branch, whichever that turns out to be.
3. Either delete `feat/newbot-step1-skeleton` or fast-forward it to `master` so a future redeploy
   from it (e.g. a rollback) can't silently reintroduce 77 commits of already-fixed bugs, C-1 included.

---

## LIVE (Supabase `xdonwowgqvmtrduikaon`, last 7 days unless noted)

**L-1. Informational — all 11 modules paused since 2026-09-07 18:27:28 UTC, on purpose.**
`modules.inactive_detail` (8 of 11 rows, identical text): *"Paused on Sir's instruction 2026-09-07:
every module is loss-making on the paper bench (-$1,217 on $10k). Do NOT auto-revive."* The other 3
(`elon_tweets`, `truth_social` — decommissioned 2026-07-11; `LP Rewards`, `Mirror Trader` — dead_thesis)
were already off before that. Consequences, all expected given the above:
- Signals: 0 in the last 7 days (55,242 in the 30 days *before* the pause, 11.0% approved — normal
  range, not the "approved ~0" starvation pattern this checklist watches for).
- Realized P&L, all-time, per module (all closed, all paper — no `executor` column exists to
  distinguish paper/live, see B-2): S2 Basket-Hold **-$486.27**, Arb Scanner **-$456.31**,
  Copytrader **-$321.73**, Market Maker **-$35.36**, Sports Sweep **-$5.12**. Total **-$1,304.79**.
  Consistent with the owner's -$1,217 figure from three weeks earlier (further losses realized
  closing out positions after the pause).
- Engine liveness: `Cycle:` heartbeat every ~5 min, latest 2026-09-28 13:33:11 UTC — **not stale**, but
  every cycle reports `'modules': 0` (has for all 14+ days queried). The heartbeat alone would have
  looked "healthy" through this entire episode; only checking module count against zero explains why.
- Foreign writer: no `%enabled_wallets%` messages in `logs` at any retained horizon — clean. (Master's
  history shows this was previously found and killed 2026-09-04 — "our own Railway JaxBot service.")
- One stale, one-time watchdog alert: `settings.watchdog_alert_sent` records an "engine not cycling
  (age=Nonem)" restart action from 2026-09-27 08:33 UTC — a warm-up/health-endpoint blip, not a
  cycling failure (Cycle logs are dense and current); no action needed, note only.
- `settings.circuit_breaker` shows 87 lifetime trips (global) and per-module breaker rows for 3
  modules with 0-2 trips each — all predate or coincide with the 09-07 pause, none since.

**No action item here** beyond what's already in P-1/C-1 — this state is intentional and correctly
self-reported. Flagging only because the checklist calls for reporting P&L/approval health regardless
of cause, and because "everything is paused" is exactly the kind of state a heartbeat-only check would
miss (as the engine's own `Cycle: {'modules': 0}` logs demonstrate).

---

## CODE

### C-1. CRITICAL (instructed branch only; fixed on master) — auto-revive skip-list omits `paused_by_owner`

`feat/newbot-step1-skeleton`'s `scripts/watchdog.py:192-204` (the systemd-timer self-heal, runs every
15 min per `infra/watchdog/polybot-watchdog.timer`) re-activates any `status='inactive'` module to
`'paper'` unless `inactive_reason` is `decommissioned` or `dead_thesis`:

```python
if (m.get("inactive_reason") or "").lower() in ("decommissioned", "dead_thesis"):
    continue
sb.table("modules").update({"status": "paper", "inactive_reason": None}) \
    .eq("id", m["id"]).execute()
```

`paused_by_owner` — the reason on all 8 currently-paused, budget-bearing modules, with an explicit
"Do NOT auto-revive" instruction in `inactive_detail` — is not in that list. On this branch, the very
first watchdog run after deploy would silently flip all 8 back to `paper` and clear `inactive_reason`,
overriding the owner's instruction with no human in the loop. Master fixed this in commit `59da928`
(`"paused_by_owner"` added to the skip tuple) and the fix is confirmed live (L-1: modules have stayed
paused for 3 weeks under a watchdog that runs every 15 min).
**Not modified here** (this is exactly the kind of change this audit is scoped to recommend, not make).
Recommendation: this is moot once P-1 is resolved (branch deleted/fast-forwarded); until then, do not
deploy from `feat/newbot-step1-skeleton`.

### B-1. HIGH (both branches — file is unmodified between them) — backtest floor-substitution + no RUN_META

`_DataMetricPulls/pacing_backtest/taker_speed_sweep.py:330-331,432` — `df['entry_vwap'].fillna(0.5)`
and the equivalent on `exit_vwap` substitute a neutral 50¢ price for missing vwab data into the fee/PnL
ledger, instead of excluding the row. This is precisely the pattern CLAUDE.md's canonical-data rule 7
and `backtest-auditor.md` Pass A prohibit (a missing price must exclude the auction, never default to
a floor/epsilon — it fabricates the result). Compounding: **zero RUN_META emission** anywhere in the
file (grepped, no hits) — unversioned and unauditable even before the substitution issue. Do not quote
any number from this script; route it through `@backtest-builder`/`@backtest-auditor` before reuse.

`phase_wh_maker.py` is still present, unmodified, and still on `backtest-auditor.md`'s "removed from
trusted exemplars" list (2026-07-23, phantom-fill bug comparing prints to ambient best_bid instead of
the resting-quote price) — not a new finding, confirming it's still a live trap for anyone who copies
it as a template.

`wh_pace_port_backtest.py` and `single_auction_seesaw.py` were sampled and look clean (RUN_META
present; the only `1e-6` epsilons found are share-count zero-guards, not price substitution).

### R-1. Risk gate (`api/services/risk_manager.py`) — no new findings beyond master's own recent fixes

Fail-closed behavior is intact throughout (DB errors, missing spread/edge/depth data all reject).
Dust floor is correctly scaled off the CLOB $1 minimum, not global bankroll (this was fixed 2026-07-29,
still correct). The only functional diff vs the instructed branch is the duplicate-order guard now also
matching `token_id`, not just `bracket` (fixed a permanently one-legged arb bug from 2026-09-04) — good.
Given the current all-modules-paused state, this gate is presently seeing zero live traffic to validate
against; nothing to add beyond what the 2026-08-31 audit already logged as open items for the owner
(paper/live P&L commingling via a shared `positions` table with no `executor` column — **B-2**, still
present, still unresolved as of this diff; static `config.bankroll` constant vs `modules.budget` as two
un-reconciled denominators — still present).

### M-1. Module isolation — clean

No cross-module imports found on either branch (`api/modules/*/` — each module only imports its own
directory or `api.modules.shared`). All required files present in every module directory. No hardcoded
module-name branching in engine/router code beyond one pre-existing LOW item (`engine.py`'s
`_active_sports_series` hardcodes `"sports_sweep"` directly rather than going through a `BaseModule`
hook — not a CLAUDE.md-forbidden if/elif chain, just a literal worth generalizing if a second module
needs the same pattern later).

### S-1. MEDIUM — test suite has real coverage gaps from API drift

On `master`, running `python -m pytest tests/` (after installing `pydantic-settings`/`supabase`/etc.
from `requirements.txt`, absent in this sandbox by default):

- **3 files fail to collect** — `tests/test_engine.py` imports `TradingEngine` (no longer exported by
  `api.services.engine`), `tests/test_risk_manager.py` imports `RiskManager` (the module is
  function-based now, `check()`), `tests/test_copy_trading.py` imports `api.modules.copy_trading`
  (the live module is named `copytrader`). These tests have presumably been silently not-run for as
  long as those renames have existed — meaning `engine.py` and `risk_manager.py`, two of the most
  safety-critical files in the repo, currently have **no passing unit test file at all**.
- Of what does collect: **70 passed, 9 failed**. `test_executor.py` (4 paper-executor + 3 live-executor
  failures) look like test-side API drift (`LiveExecutor.__init__() got an unexpected keyword argument
  'profile'` — the test predates a constructor signature change). `test_signals.py` has two failures
  that look like genuine logic/test mismatches worth a human look, not obviously test-side: `kelly_pct`
  returns `0.0171` instead of `0` at `elapsed_pct=1.0` (expected fully-elapsed auctions to zero out
  Kelly sizing), and `rank_brackets` returns 5 brackets instead of the expected top-3 cap.
- Excluded from these counts: several `_DataMetricPulls/**` and `scripts/canonical/**` files pytest
  picked up by naming convention (`*_test.py`/`test_*.py`) that are research scripts, not part of the
  bot's test suite — they fail on missing `duckdb`/`google-cloud` packages or hardcoded Windows paths
  from the original author's machine, not code bugs. Recommend excluding `_DataMetricPulls/` and
  `scripts/canonical/` from pytest's default collection (e.g. `testpaths = tests` in `pytest.ini`) so
  a real CI run isn't drowned in irrelevant collection errors.

### Silent failures / dead code — clean beyond what's above

No bare `except: pass` in money-touching paths; two narrowly-scoped `except Exception: pass` blocks
(`api/services/halt.py:53-61` around halt-notify/audit-log writes, `engine.py:262-263` around one
module's optional config field) are low-impact but would benefit from at least a `log.exception` call
for observability — neither affects the actual safety-critical action (halt flag / cancel-all still
executes either way). No `.single()` PGRST116-risk calls found in `api/`. No TODO/FIXME in
`executor*`/`risk_manager.py`/`*/signals.py`. Order placement confirmed limit-only throughout
(`clob.py:115,129`, explicit `price=` on every call). No hardcoded secrets.

**Not investigated further, low priority:** `settings` holds two stale `alert_repeated_errors:[elon_tweets]...`
/ `[truth_social]...` keys (PGRST116-style "Cannot coerce the result to a single JSON object" errors),
both timestamped 2026-09-07 in the hours before the pause. Both modules were decommissioned 2026-07-11,
so something was still touching them by name two months later; harmless now (nothing has run against
them since the pause and they won't be auto-revived — `decommissioned` is and remains in the watchdog
skip-list on both branches), but worth a quick grep if anyone re-touches those modules.

---

## Scope note

No live trading logic, risk limits, or module behavior was modified. This report and this file are the
only change in this PR.
