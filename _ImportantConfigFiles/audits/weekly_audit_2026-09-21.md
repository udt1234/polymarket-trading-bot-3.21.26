# Weekly Audit — 2026-09-21

Branch audited: `feat/newbot-step1-skeleton` @ `4820dd3` (live production code).
Live data: Supabase project `xdonwowgqvmtrduikaon`, last 7 days (2026-09-14 → 2026-09-21).
Report only — no trading logic, risk limits, or module behavior changed. All findings below are
recommendations for human review.

## Headline

The fleet has now been fully paused for **two weeks straight** (since 2026-09-07, deliberate
owner action, correctly honored — no bug there). With almost no live signal to audit, this week's
substantive findings are all on the **code** side, and one of them is new and serious: the
live-fill reconciliation path (`api/services/fills.py`) is never started anywhere in the app, so
if any module is flipped back to live trading today, **no live order would ever be recorded as
filled**, and every submitted order would permanently eat into that module's exposure cap. This
was not flagged in either of the last two audits and should block re-activation until fixed. The
three broken test files, the `sports_sweep` engine hardcode, and the Spike-trading backtest
RUN_META gap flagged on 2026-09-07 are all still unresolved three weeks later. Separately, this
week's architecture review confirmed the repo's own documentation (CLAUDE.md's pinned "Spike
Trading" section, `MODULE_ARCHITECTURE.md`, `ARCHITECTURE.md`) describes a bot that was torn down
and rebuilt on 2026-06-16 and was never updated — including advising every session to surface
bracket recommendations for a module (`spike_trading`) that has no code on this branch at all.

---

## LIVE (Supabase, last 7 days)

### [INFO] Fleet still paused, week 2 — working as designed
`signals_7d = 0`, `approved_7d = 0` across all 11 `modules` rows. This is not the "approved≈0
while signals>0" gate-bug class the audit is designed to catch — zero signals were even generated,
because 9 of 11 modules carry `status='inactive'`, `inactive_reason='paused_by_owner'`,
`inactive_since=2026-09-07 18:27:28 UTC`, with the identical `inactive_detail` on every row:
> "Paused on Sir's instruction 2026-09-07: every module is loss-making on the paper bench
> (-$1,217 on $10k). Do NOT auto-revive."
The last signal ever written to the `signals` table (377,385 lifetime rows) is timestamped
`2026-09-07 18:23:51 UTC` — 4 minutes before the pause took effect. `engine.py` cycles have logged
`modules: 0, signals: 0, approved: 0` on every single cycle since, 24/7, for two full weeks
straight (spot-checked hourly buckets 2026-09-19 → 2026-09-21, 11-12 cycles/hour, zero gaps) — the
pause is being honored correctly, and "Do NOT auto-revive" has not been violated.

### [MEDIUM] All-time realized P&L, unchanged since last week — same 3 persistent losers, still unfixed
No positions closed this week (nothing to close — fleet paused), so 7-day P&L is flat/null for
every module. All-time realized P&L by module:

| Module | Status | All-time P&L | Open positions |
|---|---|---|---|
| S2 Basket-Hold | paused_by_owner | **-$486.27** | 0 |
| Arb Scanner | paused_by_owner | **-$456.31** | 1 |
| Copytrader | paused_by_owner | **-$321.73** | 0 |
| Market Maker | paused_by_owner | -$35.36 | 0 |
| Sports Sweep | paused_by_owner | -$5.12 | 0 |
| Elon Late Arb / Elon Reversion / LP Rewards / elon_tweets / truth_social / Mirror Trader | inactive | $0 (no closed positions on record) | 0 |

Sum of all-time realized losses across the 5 modules with trade history: **-$1,304.79**, against
the "-$1,217 on $10k" the owner cited when pausing on 2026-09-07 — the small gap is most likely a
snapshot-timing difference (a handful of exits may have closed in the minutes between the owner's
note and the mass pause), not evidence of new post-pause activity; `signals_7d=0` rules out any
new trading. Same three worst modules flagged in both prior audits (S2 Basket-Hold, Arb Scanner,
Copytrader) — unchanged, because they've simply been sitting paused rather than fixed or
re-validated. Repeating last week's recommendation: require a fresh `@backtest-builder` /
`@backtest-auditor` pass against current canonical data before any of these three go back live —
a bare unpause would resume trading a strategy nobody has re-validated in 2+ weeks.

### [PASS] Engine liveness
Newest `logs` `Cycle: {...}` row: `2026-09-21 13:22:35 UTC`; well under the 20-minute staleness
threshold, and has been landing every ~5 minutes around the clock all week.

### [LOW] Watchdog auto-restarted the engine 5 times this week, and every alert is undiagnosable
`systemctl restart polybot.service` fired via watchdog on 2026-09-16, 2026-09-15 (×3), and
2026-09-20 — each preceded by a `warning`-level "engine not cycling" log, and each followed by the
engine resuming cycling normally (no gap longer than the ~5-min cadence found in any of the
around-restart windows checked). The restart mechanism itself appears to be working. However every
one of these alerts, this week and in prior weeks, reads:
```
watchdog fixed: engine not cycling (age=Nonem) -> systemctl restart polybot.service
```
`age` is `None` when this message is built and `"m"` (minutes) is appended with no null-guard, so
the alert can never actually say *how* stale the engine was before the restart fired — every
occurrence prints the literal string `Nonem`. Low severity (the restart itself works), but it
means nobody can tell from the log whether these are 2-minute blips or multi-hour outages. One-line
fix in whatever service formats this message (not located precisely this week — grep for the
`"engine not cycling"` string in the watchdog/systemd service code, which is outside this repo's
`api/` tree if not found there).

### [RESOLVED, still confirmed] Foreign "enabled_wallets" writer remains dead
No `logs` rows matching `%enabled_wallets%` since `2026-09-07 17:39:02 UTC` (5 most recent hits
checked, all from that date or earlier) — consistent with the 2026-09-14 audit's confirmation that
this was Polybot's own Railway `JaxBot` service, killed the same day. No further action.

### [LOW] 3 orphaned per-module circuit-breaker settings rows — dead data, not dead code risk
`settings` contains `circuit_breaker:<module_id>` rows for Copytrader, Arb Scanner, and S2
Basket-Hold (all last updated 2026-09-07 or earlier). Grepped the full `api/` tree: nothing reads
or writes the `circuit_breaker:{module_id}` key pattern — the only live breaker is
`api/services/breaker.py`'s single global `"circuit_breaker"` key (fail-closed, correctly
implemented, 87 all-time trips, last updated 2026-07-06 — consistent with the fleet having been
either untripped or paused since). These 3 rows are leftover state from a retired per-module
breaker design; safe to delete, cosmetic only.

---

## CODE (branch `feat/newbot-step1-skeleton`)

### [CRITICAL] Live fills are never reconciled — every live order would permanently eat its exposure cap
`api/services/fills.py` (177 LOC: `handle_user_message()`, `UserChannelStream`,
`reconcile_open_orders()`) is never imported or started anywhere. `api/main.py`'s `lifespan`
(:31-47) starts only `registry.discover()`, `Engine`, and `tweet_collector`; `engine.py` registers
exactly 4 scheduled jobs, none of them a fill reconcile. `LiveExecutor.execute()`
(`executor.py:51-64`) places the order and writes `status="submitted"` — its own docstring says
"fills arrive via fills.py" — but nothing ever promotes a submitted order to filled, so **no live
position would ever actually open**. Worse: `risk_manager._open_exposure()` /
`_module_exposure()` (`risk_manager.py:79-82`, `:102-104`) count orders in `status in
("submitted","open","partially_filled")` toward both the module budget cap and the portfolio cap —
so a submitted-but-never-reconciled order consumes real budget forever, starving every future
signal in that module. This is structurally the same failure class `lessons.md` already documents
for 2026-07 ("unfilled BUYs eat the exposure cap forever"), just via a different root cause (the
reconciler was never wired into the app, not a sizing bug). **This was not flagged in either the
2026-09-07 or 2026-09-14 audit** — confirmed independently this week by grepping every symbol
`fills.py` exports across the whole `api/` tree (zero hits outside the file itself) and reading
`main.py`'s full lifespan. **Recommend: block any module from going `paper → active` until
`reconcile_open_orders()` (at minimum, as a scheduled poll) is wired into the engine's job list.**

### [CRITICAL] Still unresolved, 3 weeks running: `pytest -q` cannot collect
Same three files flagged 2026-09-07 and 2026-09-14, unchanged, despite commits merging on this
branch in the interim:
- `tests/test_copy_trading.py:16` — imports `api.modules.copy_trading.decision`; that package does
  not exist (the live module is `api.modules.copytrader`).
- `tests/test_engine.py:3` — imports `TradingEngine` from `api.services.engine`; the class is
  `Engine`.
- `tests/test_risk_manager.py:4` — imports `RiskManager` from `api.services.risk_manager`; there is
  no such class, only a module-level `check()` function plus `Signal`/`RiskVerdict`.

A bare `python -m pytest -q` still aborts collection entirely (`3 errors during collection`,
`Interrupted!`, 0 tests run), hiding that 70 of the 82 tests that *do* collect currently pass, and
that `tests/test_executor.py` is failing 7/7 against current code (`LiveExecutor.__init__()` no
longer takes a `profile` kwarg — a real, good change per the dual live-guard rule, just untested;
`open_position` referenced by the mocks doesn't exist). **This has now gone three consecutive
weekly audits without a fix.** If CI or `/pre-commit` invokes plain `pytest -q`, it has been
non-functional for at least three weeks.

### [HIGH] Documentation totally describes a bot that no longer exists
`api/modules/` currently contains only: `arb_scanner, copytrader, demo, elon_late_arb,
elon_reversion, lp_rewards, market_maker, mirror_trader, s2_basket_hold, shared, sports_sweep`.
There is **zero occurrence anywhere under `api/`** of `truth_social`, `elon_tweets`,
`spike_trading`, or `copy_trading` — all four are documented as current in
`_ImportantConfigFiles/MODULE_ARCHITECTURE.md` and `ARCHITECTURE.md`, and **CLAUDE.md's pinned #1
section is entirely about Spike Trading bracket recommendations for a module with no code on this
branch.** Root cause is explicit in the repo's own history: `_ImportantConfigFiles/HANDOFF.md`
records "BOT TORN DOWN FOR FRESH REBUILD" on 2026-06-16, with "Cut Spike" as an explicit decision —
none of the three docs were updated after. Concretely wrong/misleading as a result:
- CLAUDE.md instructs "ALWAYS surface [Spike bracket recommendations] first" for a strategy that
  cannot currently be enabled.
- CLAUDE.md's own Module Architecture Rule 4 example, `module.get_search_term()`, does not exist
  anywhere in the current 9-method `BaseModule` contract (`api/modules/base.py`);
  `MODULE_ARCHITECTURE.md` documents ~20 `BaseModule` methods, roughly half of which don't exist.
- `MODULE_ARCHITECTURE.md`/`ARCHITECTURE.md` document a `/api/modules/*`, `/api/dashboard/metrics`,
  `/api/portfolio/positions`, `/api/analytics/summary` FastAPI surface and a
  `Next.js → FastAPI → Supabase` data-flow diagram; `api/main.py:51` registers exactly one router
  (`health`) — none of those endpoints exist, and the web dashboard reads Supabase directly.

**Recommend a single decision from the human owner**: either demote CLAUDE.md's Spike section to
`_ImportantConfigFiles/` as historical research (marked clearly non-actionable), or scope reviving
`spike_trading` as a real module — and either way, rewrite `MODULE_ARCHITECTURE.md`/
`ARCHITECTURE.md` against the real 10-directory tree and the real 9-method `BaseModule`.

### [HIGH] `engine.py` still hardcodes `sports_sweep` — unresolved 3 weeks running
Unchanged since 2026-09-07: `engine.py:201` imports `api.modules.sports_sweep.data` directly;
`:251` does `self.registry.get("sports_sweep")`; `:255` filters `.eq("strategy", "sports_sweep")`.
The module-agnostic pattern this should follow already exists two lines away in the same file
(`engine.py:208-226`'s "GENERIC coverage" block fetches quote tokens for *any* module without
naming a strategy) — the fix pattern is already present, it just wasn't applied here.

### [MEDIUM] Un-audited P&L headline behind CLAUDE.md's most-surfaced section
`scripts/canonical/backtest_spike_v2.py` and `backtest_spike_ladder_vs_floor.py` — the scripts
behind CLAUDE.md's "SPIKE TRADING" bracket table — carry no `RUN_META` block and have no entry in
`_DataMetricPulls/pacing_backtest/audits/`. Per CLAUDE.md's own "Backtest Agents Are The Default"
rule, no number from these should be quoted without an `@backtest-auditor` pass; both also fill on
hourly-bar-touch (a bracket's hourly high/low touching a target price = fill) rather than
event-driven real-L2 maker fills, which `backtest-auditor.md` treats as a fill-rate-inflating
pattern. This compounds the HIGH finding above — the module these numbers describe doesn't exist
in code right now, so at minimum CLAUDE.md's framing of them as an actionable "which brackets
should Spike trade" answer is currently unactionable either way.

### [MEDIUM] Two previously-FAILED backtests still carry their bug, no reaudit on file
`taker_speed_sweep.py:330-331` still does `.fillna(0.5)` on entry/exit VWAP feeding the fee
calculation — the same bug behind its FAIL'd "+4.4/$100 at zero fee" headline
(`audits/taker_speed_sweep_2026-07-22.md`, "CLASS B FATAL"). `wh_pace_port_backtest.py` carries an
inline comment addressing the phantom-fill bug in `phase_wh_maker.py`, but its own prior audit
(`audits/wh_pace_port_backtest_2026-07-24.md`, VERDICT FAIL) found the fix insufficient — a
zero-edge control was still profitable under moderate hardening — and no `_reaudit.md` exists
confirming a real fix since. Per CLAUDE.md, "no exceptions, including negative results" — treat
both scripts' current numbers as still blocked from being quoted.

### [MEDIUM] `ModuleRegistry.for_db_row()` keyword-fallback is a latent misrouting risk (not currently triggering)
`api/modules/__init__.py:43-61` matches a `modules` row to a module by exact `strategy` field
first, falling back to substring keyword matching against the row's display `name` only if
`strategy` doesn't match. Checked against every live row in `modules`: all 11 have a `strategy`
value that exact-matches a registered module name, so the keyword fallback is **not currently
misrouting anything**. It is latent risk, though: `arb_scanner`'s keywords `["arb","scanner"]`
would shadow `elon_late_arb`'s `["late arb","elon arb"]` for any future row whose `strategy` field
is blank or mistyped and whose display `name` contains "arb" — silently running the wrong module's
`evaluate()` against another strategy's budget. Recommend logging + alerting any time the keyword
fallback path is actually taken, so a future typo doesn't route a signal into the wrong module
silently.

### [MEDIUM] Module → service import direction is inverted from the documented layering
Not a Rule 2 violation (cross-module imports are genuinely clean — see below) but all 9 real
modules import `api.services.*` directly (e.g. `arb_scanner/module.py` imports
`api.services.clob` + `api.services.risk_manager`; `copytrader/module.py` and
`market_maker/module.py` import `api.services.position_manager`), where the documented direction
is services depending on modules, not the reverse. Recommend moving the read-only facades
(`Signal`, `snap_price`, `open_positions`) into `api/modules/shared/` so modules stop reaching into
`api/services/` directly.

### [LOW] `elon_late_arb/data.py:63-65` swallows book-fetch errors with no log
```python
except Exception:
    return {"best_bid": None, "best_ask": None}
```
Every sibling module (`arb_scanner`, `elon_reversion`, `mirror_trader`) logs via
`log.exception(...)` on the equivalent failure; this one doesn't. `lessons.md` already documents
this exact module shipping `None` spread/bid/ask that the risk gate correctly fails closed on as
`no_spread_data` — but silently, with no log line to explain why the module produced nothing. Add
`log.exception` so a live recurrence surfaces instead of just going quiet again.

### [LOW] Dropped/unmatched module rows and module-import failures are silent
`engine.py:116-117` — `if module is None: continue`, no log line, no increment to the cycle
summary's `errors` counter. `api/modules/__init__.py:31-32` logs `Failed to load module {name}:
{e}` with no traceback. Both are the same "a module silently stops producing signals and nobody
notices for days" shape that the 2026-09-01 "revive 4 silent modules" fix (`91915ae`) had to catch
manually. Recommend `log.exception` on import failure and a WARNING+alert whenever `for_db_row()`
returns `None` for a row that isn't `status='inactive'`.

### [LOW] Orphaned files with zero importers anywhere in `api/`
`api/services/hot_path.py` (125 LOC), `api/services/heartbeat.py`, and under
`api/modules/shared/`: `canonical_data.py` (461 LOC — the largest file in `api/`), `l2_history.py`,
`parquet_archive.py`, `feed_guard.py`; `pacing.py`/`projection.py`/`signals.py` are referenced only
by their own unit tests, not by any live module. `parquet_archive.py` having zero live callers is
worth a specific check, given CLAUDE.md's "Retention + Parquet Archive" section names it as the
required read path once live data ages out of the Supabase retention window — confirm no module
actually needs pre-retention-window data yet, or this is missing wiring rather than dead code.

### [LOW] Small duplication not yet factored into `shared/`
`GAMMA = "https://gamma-api.polymarket.com"` hardcoded in 7 separate `data.py` files while
`polymarket_proxy.gamma_base()` exists unused for this purpose; a `_f()` float coercer duplicated
3×; `live_elon_event()` near-duplicated between `elon_reversion/data.py` and
`elon_late_arb/data.py`.

### [LOW] `api/modules/demo/` still self-marked dead
`demo/module.py:2` says "Delete once S2 lands" — `s2_basket_hold` has been live for weeks. Still
auto-registered every boot via `pkgutil` discovery.

### What was checked and is clean
- **Risk gate (`api/services/risk_manager.py`), read in full.** Fails closed on every DB-error and
  missing-data path (`db_error:*`, `no_spread_data`, `no_depth_data`); empty realized-P&L history
  is correctly treated as "no constraint" per the file's own stated distinction, not "block all."
  Limit-only throughout — `Signal.price` is required and always used as a resting limit; no
  market-order path exists. Every cap checked against the correct denominator: the dust floor
  (`signal.notional < 1.0`) is a flat $1 CLOB minimum, not scaled by bankroll (fixed 2026-07-29,
  stays fixed); the per-module budget cap compares module notional against `modules.budget`
  directly; only the portfolio/single-market/correlated caps are scaled by global `bankroll`,
  which is correct since those are meant to be portfolio-wide fractions. No wrong-denominator
  regression found.
- **Module isolation.** Zero cross-module imports found across every `api/modules/*/` file (grep
  for `from api.modules.<other>` excluding `shared`/`base`) — every module directory has the
  required `module.py`/`module_config.py`/`__init__.py` and exports `Module`. The registry's
  auto-discovery (`api/modules/__init__.py`) is itself genuinely module-name-agnostic — contrast
  with `engine.py`'s `sports_sweep` special-case above.
- **Silent failures, broadly.** No `.single()` usage anywhere in `api/` (the PGRST116 class of bug
  stays structurally absent — all config loaders use `.limit(1)` + `if res.data`). No
  `TODO`/`FIXME`/`XXX`/`HACK` markers under `api/`. The handful of bare `except: pass` found
  (`api/services/halt.py:53-54,60-61` — notify/log-write only) are non-money-path.

---

## Test run

```
python -m pytest -q tests/
# 3 errors during collection: test_copy_trading.py, test_engine.py, test_risk_manager.py
# Interrupted, 0 tests run

python -m pytest -q tests/ --ignore=tests/test_copy_trading.py --ignore=tests/test_engine.py --ignore=tests/test_risk_manager.py
# 9 failed, 70 passed
```
Environment note: this sandbox had neither `pytest` nor the project's `requirements.txt` installed
by default; both were installed fresh this session (`pip install pytest pytest-asyncio` then
`pip install --ignore-installed -r requirements.txt`) before the above ran against real dependencies
(not skipped/mocked).

---

## Recommended priority order for human follow-up

1. **Wire `reconcile_open_orders()` into the engine's scheduled jobs before any module goes back
   to live trading** — the new CRITICAL finding this week; a live order placed today would never
   be recorded as filled and would permanently eat its module's exposure cap.
2. **Fix the 3 broken test files** (`test_copy_trading.py`, `test_engine.py`,
   `test_risk_manager.py`) — 3 weeks unresolved, and doing this before #1 ships gives the fill-fix
   real test coverage to land against.
3. **One owner decision on Spike Trading**: revive it as a real module, or demote CLAUDE.md's
   pinned section to historical notes — then rewrite `MODULE_ARCHITECTURE.md`/`ARCHITECTURE.md`
   against the real 10-module tree.
4. Remove the `sports_sweep` hardcode in `engine.py` (3 weeks unresolved) in favor of the generic
   pattern already used two lines away in the same file.
5. Everything else (MEDIUM/LOW above) at the team's normal cadence — none is blocking.

No trading logic, risk limits, or module behavior was modified as part of this audit. No
LOW-RISK typo/dead-code fixes were applied either: every item above touches either a money-adjacent
path or state other systems depend on (dead settings rows, hardcoded constants, stale tests),
enough that even a "safe" deletion deserves an explicit human sign-off rather than a batch cleanup
riding along with a report PR.
