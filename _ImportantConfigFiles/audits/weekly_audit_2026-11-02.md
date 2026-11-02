# Weekly Polybot Audit — 2026-11-02

Scope: LIVE production data (Supabase project `xdonwowgqvmtrduikaon`, last 7 days unless noted) + CODE on the live branch `feat/newbot-step1-skeleton` (HEAD `4820dd3`). Findings ranked CRITICAL / HIGH / MEDIUM / LOW. LIVE findings first, then CODE. This is the **9th consecutive weekly audit**; deltas vs. last week (PR #117, `weekly_audit_2026-10-26.md`, unmerged) are called out explicitly rather than re-describing unchanged state at length.

## Summary

The bot has now placed **zero trades for 56 days** (since 2026-09-07, owner-paused, "do NOT auto-revive"). This week only needed **2** forced watchdog restarts (down from 5 last week) and otherwise the engine is healthy. The real news this week is on the **code** side: a fresh read of `api/modules/shared/config_store.py` found that the per-module budget cap — previously confirmed fixed — has a second, un-fixed failure mode: on a DB read error it silently falls back to the **global** bankroll instead of failing closed, reintroducing the exact "wrong denominator" bug class via an error path instead of a missing-row path (**C1**). A second CRITICAL (**C2**) was found in a backtest script that CLAUDE.md's own `backtest-auditor.md` lists as a trusted "do not re-flag" exemplar — it fabricates missing winner-bracket prices as `1e-6`, the exact fabrication rule #7 of the Canonical Data Layer section exists to prevent. Also flagging, again, a **process** problem: 8 of the last 8 weekly-audit PRs (#104–#117) remain open, draft, and unmerged — none of their recommendations, including two prior low-risk dead-code deletions, have actually landed on this branch.

---

## LIVE findings (Supabase, last 7 days unless noted)

### HIGH — Bot has been fully dormant for 56 days; recommendations from 8 prior audits are still unactioned
- `signals`/`positions`: 0 rows in the last 7 days; `max(signals.created_at)` across the whole table is still `2026-09-07 18:23:51 UTC`. All 11 `modules` rows remain `status=inactive`; 9 of them `inactive_reason=paused_by_owner` since `2026-09-07 18:27:28 UTC` with the identical note: *"Paused on Sir's instruction 2026-09-07: every module is loss-making on the paper bench (-$1,217 on $10k). Do NOT auto-revive."* This is a deliberate owner decision and correctly honored by the code (confirmed again this week — see M1 in CODE).
- **All-time realized P&L by module** (unchanged from last week, since nothing has traded): S2 Basket-Hold -$486.27, Arb Scanner -$458.11, Copytrader -$321.73, Market Maker -$35.36, Sports Sweep -$5.12 (total ≈ -$1,306.59). Elon Late Arb, Mirror Trader, elon_tweets, Elon Reversion, LP Rewards have no closed positions.
- **New this week, process-level:** PRs #104, #111, #112, #113, #114, #115, #116, #117 — every weekly audit PR from 2026-09-07 through 2026-10-26 — are still open, still `draft`, **none merged**. This means: (a) the two LOW-RISK dead-code deletions proposed in PR #114 (`api/modules/demo/`) and PR #117 (`api/modules/shared/feed_guard.py`) never actually took effect on this branch — `api/modules/demo/` was still present and had to be re-deleted in this PR (see CODE/L1 below); (b) CRITICAL findings like PR #112's "`fills.py` reconciliation is never wired in" and PR #113's "is `feat/newbot-step1-skeleton` even the deployed branch?" have had no recorded human decision for 6+ weeks. Recommend triaging/closing the backlog (merge the report-only PRs, or consolidate into one doc) so a real finding doesn't get lost in 8 stacked drafts.
- Recommend (repeated from PR #117, still open): make an explicit decision — re-evaluate strategies and re-enable, or formally mark the bot retired. A "weekly audit" of a bot idle for 2 months is easy to mistake for "nothing to report."

### MEDIUM — Watchdog restarts down to 2 this week (was 5 last week), but the `age=Nonem` logging bug is still unfixed
- 2 warning-level `"watchdog fixed: engine not cycling (age=Nonem) -> systemctl restart polybot.service"` entries, both on 2026-10-29 (10:57 and 18:07 UTC). 652 healthy heartbeats otherwise this week (`"watchdog: healthy (bench paused: 0 active modules, not trading by design)"`).
- The `age=Nonem` string-formatting bug flagged in PR #117 is still present verbatim a week later — the watchdog still can't report how long each hang lasted, which still blocks root-causing why the engine cycle intermittently hangs even with 0 active modules. Not independently re-investigated this week (watchdog.py is `infra/`, outside this pass's code-audit scope) — carrying forward as unresolved.

### MEDIUM — `settings.circuit_breaker.updated_at` still stale; two paused modules still missing their audit trail
- `circuit_breaker` row: `value={"trips":87,"cooldown_until":"2026-09-07T18:45:58Z","consecutive_losses":1}`, `updated_at=2026-07-06` — unchanged from last week. Root cause (confirmed again this week, see CODE/M4-adjacent note below): `breaker.py`'s save path doesn't bump `updated_at` on write.
- `Mirror Trader` and `LP Rewards` are still `inactive_reason=dead_thesis` with `inactive_since`/`inactive_detail` both `NULL` — unlike every other paused module, there's still no timestamp or human-readable reason for these two kills. Unchanged from last week.

### LOW — Foreign-writer check: clean
- Zero `logs` rows matching `%enabled_wallets%` this week (and none historically found in this project's logs at all). The legacy/foreign-bot signature this audit watches for continues to be absent.

### Informational — historical signal-approval pattern still looks like legitimate gating, not the "approved≈0" bug class
- Lifetime: 252,382 signals (2026-08-04 → 2026-09-07, the only window with any activity), rejections dominated by `module_budget_cap_500` (Arb Scanner, matches its own $500 budget) and `duplicate_resting_order` (Market Maker's dead-quote pattern, already documented in `lessons.md`), plus a long tail of `spread_X>tol_0.3` wide-book protection. No new activity to re-check this week (0 signals in 7 days, consistent with the pause).

---

## CODE findings (branch `feat/newbot-step1-skeleton`)

### CRITICAL — Per-module budget cap fails OPEN to the wrong (global) denominator on any DB error — contradicts the risk gate's own fail-closed mandate
`api/modules/shared/config_store.py:23-35`:
```python
def module_bankroll(module_id: str) -> float:
    """The bankroll a module sizes against = its modules.budget row ...
    Falls back to the global bankroll setting when unset/unreadable."""
    from api.config import get_settings
    try:
        res = (get_supabase().table("modules").select("budget")
               .eq("id", module_id).limit(1).execute())
        if res.data and res.data[0].get("budget") is not None:
            return float(res.data[0]["budget"])
    except Exception:
        log.exception("budget read failed for %s", module_id)
    return get_settings().bankroll        # <- global bankroll, NOT the module's own budget
```
Called from `risk_manager.check()` (`api/services/risk_manager.py:222-226`) to compute the module exposure cap: `if signal.notional + mod_now > mod_budget: reject("module_budget_cap_{mod_budget}")`.

`risk_manager.py`'s own module docstring states "ALL checks FAIL CLOSED: any DB error, missing price, or missing data rejects the signal." `module_bankroll()` violates that: the `except` block is *inside* this function, so the exception never reaches `check()`'s outer fail-closed handler — instead the function quietly returns the **global** bankroll (`get_settings().bankroll`, default $1000) as the per-module cap. Verified directly (code read 2026-11-02): the fallback path is exactly as described, no re-raise, no sentinel.

**Failure scenario:** a transient Supabase read error on this one query (which other code in the same file, `get_module_config()`, handles correctly by falling back to safe *defaults*, not a different and larger budget) makes a module's exposure cap silently become the full $1000 portfolio bankroll instead of its own ~$500 allocation — i.e. a live recurrence of the "LP Rewards held 65% of the book" starvation bug this exact cap was built to prevent (referenced in `risk_manager.py:94`, 2026-07-22 incident), reintroduced via the error path rather than the missing-row path that was already patched.

**Recommend:** on exception, re-raise (or return `None`/a sentinel) so `check()`'s outer `except` fires its existing `db_error:*` fail-closed rejection, instead of substituting a larger implicit cap. This needs a human/engineer fix — not applied here per the no-touch-money-paths rule.

### CRITICAL — A backtest script that CLAUDE.md's own auditor playbook calls "known-correct" fabricates missing winner-bracket prices as `1e-6`
`_DataMetricPulls/pacing_backtest/odds_vs_market.py:74-77`:
```python
mk={}
for l in order:
    d=Bk.get(l); i=(np.searchsorted(d['ts'],t*1000,'right')-1) if d else -1
    mk[l]=max(d['mid'][i],1e-6) if (d and i>=0) else 1e-6
mt=sum(mk.values()); mk={l:mk[l]/mt for l in mk}
...
rows[H]['mkt_ll'].append(-math.log(max(mk[win],1e-4)))
```
`l` ranges over every bracket including the winning bracket `win`. When a bracket has no price observation before decision time `t` (including the winner), its market price defaults to `1e-6` and gets renormalized into the market's probability distribution, then scored for log-loss. Verified directly (code read 2026-11-02): this is exactly the "fabricates the market's log loss and inverts the result" pattern CLAUDE.md's Canonical Data Layer rule #7 names explicitly — and it is specifically guarded against elsewhere in this same codebase: the sibling script `calibration_test.py:110` does it correctly —
```python
mk={b:v for b,v in mk.items() if v is not None}
if winner not in mk or sum(mk.values())<=0: mkt_ll=mkt_br=None
```
i.e. **excludes** the auction when the winner's price is missing, instead of fabricating one.

**Compounding risk:** `.claude/agents/backtest-auditor.md:14` explicitly lists `odds_vs_market.py` alongside `calibration_test.py` as a "known-CORRECT reference exemplar ... diff against, do NOT re-flag." That instruction is itself wrong for this file. No audit log exists for either script under `_DataMetricPulls/pacing_backtest/audits/`.

**Recommend:** fix `odds_vs_market.py:76` to exclude the auction when `win`'s price is missing (mirror `calibration_test.py:110`'s pattern), and update `backtest-auditor.md`'s trusted-exemplar list to stop pointing future audits away from this bug.

---

### HIGH — `engine.py` still hardcodes the module name `"sports_sweep"` in control flow (Module Architecture Rule #4) — unresolved since at least 2026-09-14, now 7 weeks
`api/services/engine.py:201` (`from api.modules.sports_sweep import data as sports_data`), `:251` (`self.registry.get("sports_sweep")`), `:255` (`.eq("strategy", "sports_sweep")`). Confirmed present verbatim this week — no change since PR #111/#117 flagged it. This is the one place in `engine.py` that special-cases a module name; the surrounding code explicitly comments that "the engine stays module-agnostic" everywhere else.

**Failure scenario:** renaming `sports_sweep` (per `MODULE_ARCHITECTURE.md`'s own rule that module name must match directory name) silently breaks paper-fill quote coverage for every sports module, with `_active_sports_series()` returning `[]` and no error logged.

### HIGH — Module DB-row-to-code mismatches are silently dropped with zero logging (new finding)
`api/services/engine.py:114-118`:
```python
for row in rows:
    module = self.registry.for_db_row(row)
    if module is None:
        continue
```
If a `modules` row's name/strategy matches no registered code module — e.g. the two decommissioned legacy rows `elon_tweets`/`truth_social` (neither has a code package on this branch) — the row is dropped silently: no warning, no counter, nothing distinguishing "0 modules because all inactive" from "0 modules because a row couldn't be matched." If either legacy row (or any future row with a typo'd `strategy`) is ever flipped back to active, it would silently never run.

**Recommend:** log a warning when `for_db_row()` returns `None` for a non-inactive row.

### HIGH — Several hand-written backtest scripts assume naive full fills on hourly bars, emit no RUN_META, and have never been through `@backtest-auditor` (new finding, specific files named)
`scripts/canonical/backtest_spike_v2.py:116-144` walks **hourly** OHLC bars and treats any bar whose low/high merely touches the limit price as a full, instant fill at that price — no L2 depth, no queue position, no fee line. This is exactly the two fatal patterns `backtest-auditor.md` names ("assume our resting order fills at limit is optimistic — flag it" / "resampling an event stream to bars deletes the edge — fatal for speed strategies"). Same gap confirmed in its siblings: `backtest_spike_ladder_vs_floor.py`, `backtest_noovd.py`, `backtest_noovd_model.py`, `backtest_noovd_xapi.py`, `backtest_noovd_calibrated.py` — none emit `RUN_META`, none have a matching file under `_DataMetricPulls/pacing_backtest/audits/`. Per CLAUDE.md's non-negotiable rule, no number from these scripts should be quoted or acted on until routed through `@backtest-builder`/`@backtest-auditor`.

### HIGH — `MODULE_ARCHITECTURE.md`'s documented module layout is still stale (recurring, unresolved since PR #114/#117)
Still documents `api/modules/{truth_social, elon_tweets, spike_trading, copy_trading}/` — none of which exist on this branch. Actual roster: `arb_scanner, copytrader, elon_late_arb, elon_reversion, lp_rewards, market_maker, mirror_trader, s2_basket_hold, sports_sweep` (+ `demo`, removed in this PR — see LOW-RISK FIXES). The BaseModule API/rules section below the stale layout example remains accurate and code-verified.

### HIGH — The 9 current-bot module rows have no corresponding seed migration — roster isn't reconstructable from git (new finding)
`supabase/migrations/*.sql` contains exactly one `insert into modules` statement (`001_initial.sql:238-240`), seeding a `Truth Social Posts` row for a module that doesn't exist in code on this branch. None of the 9 live new-bot modules' rows (`strategy`, `budget`, `status` values) are captured anywhere in version control — only in the live DB. `_ImportantConfigFiles/BUILD_SPEC.md:263` explicitly requires forward-only migrations before code references new state; this applies to the row data too, not just table DDL.

**Recommend:** add a migration (or a committed JSON/SQL snapshot) that seeds/documents the current 11-row module roster, so it survives a DB loss independent of a manual export.

---

### MEDIUM — "0 modules every cycle" reconfirmed correct, not a registry bug — but confirm boot-time registration directly at least once
`engine.cycle()` filters `modules.status != 'inactive'` (`engine.py:62-63`) **before** consulting the module registry — with all 11 DB rows inactive, `rows=[]` follows directly from DB state, independent of code-level registry discovery. Registry discovery itself (`api/main.py:33`, `api/modules/__init__.py`) is structurally correct for all 10 module packages present (each `__init__.py` correctly re-exports `Module`) — verified by reading, not by execution (pytest/deps unavailable in this pass, see TESTS below). `discover()`'s own exception handler (`api/modules/__init__.py:31-32`) silently drops any module that raises on import with only a log line and no visibility in the cycle summary — recommend confirming via Railway boot logs that "Boot complete - 10 module(s) registered: ..." actually lists all 10 at runtime, since this audit cannot execute the import.

### MEDIUM — CLAUDE.md's "all 15 risk checks" is not enumerated anywhere and doesn't match the actual check count (new finding)
Counting the distinct `RiskVerdict(False, ...)` branches in `risk_manager.py:check()` yields 16-18 distinct reject reasons (bad_price, bad_size, missing_token_id, circuit_breaker, no_spread_data, spread>tol, edge<min, dust floor, duplicate_resting_order, single_market_cap, correlated_cap, module_budget_cap, portfolio_cap, daily_loss_limit, weekly_loss_limit, max_drawdown, no_depth_data, depth>fraction) — not 15, and there is no named constant/list anywhere that pins the number. Either CLAUDE.md's number is stale or informal. Recommend enumerating the canonical check list as a constant in `risk_manager.py` that CLAUDE.md can cite, so "all 15" (or whatever the real number is) becomes mechanically checkable.

### MEDIUM — CLAUDE.md's own primary pointer for module work, `_ImportantConfigFiles/MODULE_QUICK_RULES.md`, does not exist (new finding, verified directly)
CLAUDE.md: "Read `_ImportantConfigFiles/MODULE_QUICK_RULES.md` before creating, moving or refactoring any module." Confirmed by direct search (`find . -iname "*MODULE_QUICK*"`): no such file exists anywhere in the repo. This is a broken doc reference in the project's own root instructions file.

**Recommend:** either create the file (presumably meant to be a condensed version of `MODULE_ARCHITECTURE.md`'s 8 rules) or repoint CLAUDE.md solely at `MODULE_ARCHITECTURE.md`.

### MEDIUM — Kill-switch (`halt.py`) and sports-config read failures are silently swallowed with bare `except: pass`, no logging (recurring from PR #117's LOW, re-verified directly this week)
`api/services/halt.py` — the notify-on-halt call and the audit-log insert inside `set_halt()` (confirmed by direct read 2026-11-02) are each wrapped in `except Exception: pass` with zero logging, unlike `is_halted()` in the same file which correctly does `log.exception(...)`. The halt STATE write itself is unguarded (fails loud, correctly), but a failed Slack alert or failed audit-log insert during a real halt event leaves no trace anywhere. Same pattern, lower blast radius, in `engine.py:258-263`'s per-row sports-series config read.

**Recommend:** add `log.exception(...)` to both `halt.py` blocks and the `engine.py` sports-config block, matching the rest of the codebase's convention.

### MEDIUM/Positive — `.single()`/PGRST116 pattern fully eliminated; confirmed clean
`grep -rn "\.single()"` across the entire repo returns zero hits. Every single-row Supabase lookup reviewed (`config_store.py`, `halt.py`, `breaker.py`, `risk_manager.py`) uses `.limit(1).execute()` + an `if res.data:` guard. The historical `elon_tweets`/`truth_social` PGRST116 incident has no live code-side counterpart on this branch. No TODO/FIXME/XXX found anywhere under `api/`.

---

## LOW-RISK FIXES APPLIED in this PR

- **Removed `api/modules/demo/`** (4 files: `__init__.py`, `data.py`, `module.py`, `module_config.py`). Its own docstring said "Delete once S2 lands" — `s2_basket_hold` has had a live DB row and shipped for months. Confirmed zero references anywhere else in the repo (`grep` for `modules.demo`/`modules/demo` before deleting — only the module's own internal imports). This exact deletion was first proposed in PR #114 (2026-10-05) but never took effect because that PR was never merged; applying it directly here since it's unambiguous dead code per CLAUDE.md's "prefer deleting code over adding it."

No other code changes were made. Risk-gate denominator fallback (CRITICAL), backtest fabrication (CRITICAL), and every HIGH/MEDIUM item above are left as written recommendations for human/engineer review — none of them were touched, per this audit's standing no-touch-trading-logic policy.

## TESTS

`python -m pytest -q` / `python3 -m pytest -q`: **could not run** — `pytest` is not installed in this session's sandbox (`requirements.txt` lists `pytest>=8.0.0` but no venv/install was present, and this audit does not pip-install per instructions). This is an environment gap, not a finding about the code itself. For continuity: as of the last audit that could actually run the suite (PR #117, 2026-10-26), `tests/test_risk_manager.py` and `tests/test_engine.py` failed at collection (`RiskManager`/`TradingEngine` classes no longer exist), and 9 of the remaining 79 collectible tests failed against current APIs — that state has not been independently re-confirmed this week. **Recommend the next audit run from an environment with `pip install -r requirements.txt` completed**, since test-suite health (especially over `risk_manager.py`, which this week's CRITICAL C1 finding directly concerns) has now gone two audits without a fresh run.

## Recommended next actions (priority order)

1. Fix `module_bankroll()` (C1) to fail closed (re-raise/sentinel) instead of falling back to the global bankroll on a DB error.
2. Fix `odds_vs_market.py` (C2) to exclude auctions with missing winner price instead of defaulting to `1e-6`, and correct `backtest-auditor.md`'s trusted-exemplar list.
3. Triage the 8-PR audit backlog (#104–#117) — merge, close, or consolidate so future findings don't get buried in stacked unread drafts.
4. Re-run `pytest` with dependencies installed to get a fresh read on risk_manager/engine test coverage (none in 2 audits now).
5. Decide: re-enable modules after reassessment, or formally retire the bot — 56 days idle.
6. Remaining recurring items: fix `engine.py`'s `sports_sweep` hardcode (7 weeks open), rewrite `MODULE_ARCHITECTURE.md`'s module layout, add a migration/snapshot for the live module roster, create or repoint the missing `MODULE_QUICK_RULES.md` reference, fix the watchdog's `age=None` bug, add logging to the `halt.py`/`engine.py` bare `except: pass` blocks.
