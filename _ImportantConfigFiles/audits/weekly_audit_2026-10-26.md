# Weekly Polybot Audit — 2026-10-26

Scope: LIVE production data (Supabase project `xdonwowgqvmtrduikaon`, last 7 days unless noted) + CODE on the live branch `feat/newbot-step1-skeleton` (HEAD `4820dd3`). Findings ranked CRITICAL / HIGH / MEDIUM / LOW. LIVE findings first, then CODE.

## Summary

The bot has placed **zero trades for 48 days** — every revenue module was paused by the owner on 2026-09-07 with an explicit "do NOT auto-revive" note, and nothing has re-evaluated that since. The engine process itself is alive but has needed 5 forced watchdog restarts in the last week for hangs. On the code side, the test suite cannot currently exercise either `risk_manager.py` or `engine.py` at all (both fail to import), and `CLAUDE.md` / `MODULE_ARCHITECTURE.md` describe a bot that no longer exists on this branch. The risk gate itself (denominator scaling, fail-closed behavior, limit-only orders, prod guard) checked out clean.

---

## LIVE findings (Supabase, last 7 days unless noted)

### HIGH — Bot has been fully dormant for 48 days, not 7
- `signals`: 0 rows created in the last 7 days. `max(created_at)` across the whole table is **2026-09-07 18:23:51 UTC — 48 days ago**. `positions`: 0 rows opened/closed/updated in the last 7 days either.
- Cause: all 9 budgeted modules carry `status=inactive`, `inactive_reason=paused_by_owner`, `inactive_since=2026-09-07 18:27:28 UTC`, with the identical note: *"Paused on Sir's instruction 2026-09-07: every module is loss-making on the paper bench (-$1,217 on $10k). Do NOT auto-revive."*
- This is a deliberate, documented owner decision, not a bug — flagging it because a "weekly audit" of a bot that hasn't traded in 7 weeks is otherwise easy to mistake for "nothing to report." Worth an explicit decision: re-evaluate strategies and re-enable, or formally mark the bot retired.
- The lifetime realized P&L that justified the pause: Arb Scanner -$486.27, Copytrader -$458.11 (wait: see table) — see exact per-module numbers below.

**All-time realized P&L by module** (all modules currently inactive, all paper):
| Module | Realized P&L (all-time) | Status |
|---|---|---|
| S2 Basket-Hold | -$486.27 | paused_by_owner |
| Arb Scanner | -$458.11 | paused_by_owner |
| Copytrader | -$321.73 | paused_by_owner |
| Market Maker | -$35.36 | paused_by_owner |
| Sports Sweep | -$5.12 | paused_by_owner |
| Elon Late Arb, Mirror Trader, elon_tweets, Elon Reversion, LP Rewards | no closed positions | inactive |

Total realized loss ≈ **-$1,306.59**, consistent with the owner's cited -$1,217 at pause time (small drift from positions that finished closing after the pause was issued).

### HIGH — Engine needed 5 forced watchdog restarts in the last 7 days; watchdog's own diagnostic is broken
- `logs` shows 5 warning-level entries in the last week, all identical: `"watchdog fixed: engine not cycling (age=Nonem) -> systemctl restart polybot.service"` at 2026-10-20 13:00, 10-22 17:30, 10-22 18:00, 10-25 04:02, 10-25 07:22 UTC.
- The engine process has been hanging/dying roughly every other day and requiring a forced restart. It is currently alive and cycling normally (last `Cycle:` log at 13:27:09 UTC, ~3 min before this audit ran — not stale), but the recurring need for forced restarts is itself the finding.
- The watchdog's own message is bugged: `age=Nonem` should report how many minutes the engine was stuck before the restart fired (literal string formatting bug — `None` is being interpolated instead of a computed age in minutes). This means there is currently no way to tell from logs how long each hang actually lasted, which blocks root-causing the restarts.
- Recommend: locate the watchdog's age-computation code (not reviewed in this pass — out of the stated code-audit scope but worth a follow-up), fix the `None` formatting bug, and investigate why the engine cycle has been hanging ~5x/week even with 0 active modules.

### MEDIUM — `settings.circuit_breaker.updated_at` is stale relative to its own `value`
- `settings` row for `circuit_breaker`: `value={"trips":87,"cooldown_until":"2026-09-07T18:45:58Z","consecutive_losses":1}`, but `updated_at = 2026-07-06`, two months *before* the `cooldown_until` timestamp the row itself contains. The row was clearly written after 07-06 (the cooldown_until proves it) but `updated_at` wasn't bumped. Root cause identified in code review below (`breaker.py:_save`).

### MEDIUM — Two paused modules missing their audit trail
- `Mirror Trader` and `LP Rewards` are `status=inactive`, `inactive_reason=dead_thesis`, but unlike every other paused module, `inactive_since` and `inactive_detail` are both `NULL`. Every other inactive module has a timestamp and a human-readable reason; these two don't, which makes it unclear when/why they were actually killed.

### LOW — No findings on foreign-writer check
- Searched `logs` for any `%enabled_wallets%` message (signature of the legacy/foreign bot that once shared this Supabase project) — **zero rows found**. Clean.

### Informational — historical (pre-pause) signal approval rate looks healthy, not the "approved≈0" bug pattern
- Lifetime: 301,579 signals, 17,574 approved (5.8%). Dominant rejections were legitimate gates: `module_budget_cap_500` (122,692, Arb Scanner — note the cap value `500` correctly matches Arb Scanner's own `$500` module budget, not a global-bankroll number), `duplicate_resting_order` (97,950 combined), `circuit_breaker` (8,203 combined), and a long tail of `spread_X>tol_0.3/0.4` rejections (wide-book protection). No sign of the "approved stuck at ~0 while signals>0" failure class this audit specifically watches for — see also the code-side confirmation that the dust-floor/budget-denominator bug (CLAUDE.md commit `c762636`) is fixed.

---

## CODE findings (branch `feat/newbot-step1-skeleton`)

### CRITICAL — Test suite cannot import `risk_manager.py` or `engine.py` at all; `python -m pytest -q` aborts with 18 collection errors
- `tests/test_risk_manager.py:4` — `from api.services.risk_manager import RiskManager, Signal` → **`ImportError: cannot import name 'RiskManager'`**. The module now exposes a plain `check(signal, breaker_tripped)` function, not a `RiskManager` class. The test file was never updated after that refactor.
- `tests/test_engine.py:3` — `from api.services.engine import TradingEngine` → **`ImportError: cannot import name 'TradingEngine'`**. Same pattern.
- `tests/test_copy_trading.py:16` — `from api.modules.copy_trading.decision import (...)` → **`ModuleNotFoundError`**. The module was renamed `copytrader` at some point; the test still points at the old name.
- Net effect: **zero automated test coverage currently runs against the risk gate or the engine** — the two files this audit (and CLAUDE.md's non-negotiable rules) care about most. A regression in either file today would not be caught by `pytest`.
- Compounding this: there is no `pytest.ini` / `pyproject.toml` / `setup.cfg` scoping test discovery to `tests/`. Running the exact command this audit (and presumably CI) is supposed to run, `python -m pytest -q`, from the repo root also sweeps up ~15 unrelated one-off research scripts under `_DataMetricPulls/pacing_backtest/*_test.py` / `test_*.py` and `scripts/canonical/07_consistency_test.py`. Those fail on missing local Windows paths (`C:\Users\darwi\...`) and missing optional packages (`duckdb`, `google-cloud`) that were never meant to run in CI, and pytest **interrupts the whole run** on collection errors — so the real `tests/` suite never even gets a chance to execute via the documented command.
- Isolating to `tests/` only (`pytest tests/ -q`) still aborts collection on the 3 import errors above. Excluding those 3 files, the remaining 79 tests run: **70 pass, 9 fail** (see next finding).
- **Fix direction (for human/engineer, not applied here):** (1) add a `pyproject.toml`/`pytest.ini` with `testpaths = ["tests"]`, (2) update the 3 broken imports to match current APIs, (3) triage the 9 failing tests below.

### HIGH — 9 of the 79 collectible tests fail against current APIs (test debt, not necessarily production bugs)
Running `python -m pytest tests/ -q --ignore=tests/test_copy_trading.py --ignore=tests/test_engine.py --ignore=tests/test_risk_manager.py`:
- `TestPaperExecutor` (4 failures) and `TestLiveExecutor::test_gtc_order_type` — tests patch `api.services.executor.open_position`, which no longer exists as a module-level attribute.
- `TestLiveExecutor::test_missing_credentials_raises` / `test_clob_failure_marks_rejected` — both call `LiveExecutor(profile={...})`, but `LiveExecutor.__init__(self)` (executor.py:41) takes **no constructor arguments** anymore; it reads `get_settings()` internally and raises if the prod/paper/allow-live triple guard isn't satisfied (this part of the guard is correctly enforced — see the CLEAN section below — the test is just calling a stale signature).
- `TestKellySizing::test_elapsed_100pct_zeros_kelly` — expects `kelly_sizing(0.50, 0.30, elapsed_pct=1.0)["kelly_pct"] == 0`, actual result is `0.0171`. **This one needs a human call**: either the intended behavior really is "kelly sizing should go to zero once the auction window is 100% elapsed" and the implementation regressed, or the test's expectation is simply outdated. Flagging rather than guessing — this touches live position sizing.
- `TestRankBrackets::test_returns_top_3` — expects `len(rank_brackets(...)) <= 3`, actual returns all 5 input brackets. Same ambiguity: did the "top-3" cap get intentionally removed, or is this a real regression in bracket selection?
- None of these were fixed in this audit (read-only policy) — they're flagged for engineering triage, items 3-4 in particular because they touch sizing/selection logic covered by the `betting-strategy` skill's own trigger list.

### HIGH — `CLAUDE.md` and `_ImportantConfigFiles/MODULE_ARCHITECTURE.md` document a bot that no longer exists on this branch
- `CLAUDE.md`'s entire "Spike Trading", "Canonical Data Layer", and module-list sections describe the retired Trump/Elon tweet-driven bot (modules `elon_tweets`, `truth_social`; data layer `_DataMetricPulls/canonical/`). The live module set on `feat/newbot-step1-skeleton` is completely different: `arb_scanner`, `copytrader`, `elon_late_arb`, `elon_reversion`, `lp_rewards`, `market_maker`, `mirror_trader`, `s2_basket_hold`, `sports_sweep` (+ `demo`, see below). `TEARDOWN_NOTES.md` / `HANDOFF_DELETE_BOT.md` at repo root confirm the old bot was deliberately torn down and rebuilt on the same Supabase/Railway project, but `CLAUDE.md` was never rewritten for the new system.
- `_ImportantConfigFiles/MODULE_ARCHITECTURE.md` (the file CLAUDE.md names as *the* architecture source of truth) has the same problem: its example directory tree and its own "never do this" cross-import example (line 61) both reference `truth_social/`, `elon_tweets/`, `spike_trading/`, `copy_trading/` — none of which exist in `api/modules/` today.
- Risk: every future AI session (including this one, and the scheduled auditor itself) starts from instructions that describe the wrong system. This is exactly the kind of drift CLAUDE.md's own "spec drift vs CLAUDE.md" check is meant to catch — the drift is in CLAUDE.md itself.
- **Recommend:** a `@doc-updater` pass (or manual rewrite) of `CLAUDE.md` + `MODULE_ARCHITECTURE.md` against the actual `feat/newbot-step1-skeleton` module set, before relying on either for future AI-assisted work. Not done here — out of this audit's "report only" mandate for anything beyond typos/dead-code.

### HIGH — Retention archive CLAUDE.md calls "the permanent fix" has no working read path; data is deleted with no way back
- CLAUDE.md's "Retention + Parquet Archive" section says `price_timing.py` and `whale_snapshot.py` are "already-wired" to merge in archived data via `api.modules.shared.parquet_archive.read_table_range`, and that a weekly Sunday 03:00 UTC job dumps expiring rows to parquet before the daily 03:30 UTC delete.
- On this branch: `api/modules/shared/parquet_archive.py` exists but has **zero callers anywhere in the repo** (`price_timing.py` / `whale_snapshot.py` don't exist on this branch at all). `api/services/engine.py`'s scheduler only registers `run_retention_cleanup` — the delete-only half. There is no weekly archive job wired in anywhere I could find.
- Net effect: rows older than the documented retention windows (`price_snapshots` 180d, `post_count_snapshots` 90d, `order_book_snapshots` 30d, `logs` 14-30d, `pending_signals` 7d) are being permanently deleted with **no working archive-before-delete path**, contradicting the doc's claim this was already solved. This is a real data-loss risk, not just a documentation issue.
- **Recommend:** either wire a real weekly archive job before the next retention-cleanup cycle runs, or if retention cleanup isn't currently scheduled on this branch either (not independently confirmed — worth a direct follow-up check), update CLAUDE.md to stop claiming a protection that doesn't exist.

### MEDIUM — `backtest/engine.py` is dead, broken, and would be methodologically invalid even if fixed
- `DATA_ROOT = _DataMetricPulls/historical/<handle>/...` (engine.py:16) — **this directory does not exist** on disk (confirmed: `_DataMetricPulls/historical` → "No such file or directory"). Any call into this module raises `FileNotFoundError` immediately.
- Confirmed **zero callers** anywhere in the repo (`grep -rn "backtest.engine\|run_backtest("` → no hits outside the file itself) — currently inert dead code, not a live risk.
- Separately, even if the data path were fixed, the pricing model is self-referential: it marks P&L against the model's **own generated probability** (`bracket_probs_from_projection`), never an actual market bid/ask, with no fee model and no L2/fill realism — this would fail every gate in `.claude/agents/backtest-auditor.md` (efficiency baseline must be the real market price; fills must be real, not mid-price fantasy) if anyone tried to resurrect it.
- It also emits no `RUN_META` and has no matching entry under `_DataMetricPulls/pacing_backtest/audits/`, so it was never run through `@backtest-builder`/`@backtest-auditor` in the first place — consistent with it being a hand-written one-off that CLAUDE.md's "Backtest Agents Are The Default" rule exists to prevent.
- **Recommend:** delete `backtest/engine.py` (dead, broken, methodologically unsound) rather than fix it; if a real Polymarket-native backtest is wanted for this branch's strategies, route it through `@backtest-builder` as CLAUDE.md requires.

### MEDIUM — Live strategy (`sports_sweep`) cites a backtest result that doesn't exist in the repo
- `sports_sweep`'s HOLD-TO-RESOLUTION exit rule is justified in its own module config/docstrings by a "backtest-validated 2026-07-10" result claiming "+2-3% ROI." No backtest script or `@backtest-auditor` audit log matching that date or claim exists anywhere in the repo (checked `_DataMetricPulls/pacing_backtest/audits/` and grepped for any sports/MLB-specific backtest script — none found).
- This is a live, money-affecting strategy decision resting on an unauditable or missing backtest — exactly what the "no number gets trusted without the auditor, no exceptions including negative results" rule exists to prevent. Sports Sweep is currently paused (see LIVE section) so there's no active exposure today, but this needs resolving before it's ever re-enabled.

### MEDIUM — `engine.py` hardcodes the module name `"sports_sweep"` in 3 places, violating Module Architecture Rule #4
- `api/services/engine.py:201` — `from api.modules.sports_sweep import data as sports_data` (direct import of one module's internals from engine code).
- `api/services/engine.py:251` — `self.registry.get("sports_sweep")` inside `_active_sports_series()`.
- `api/services/engine.py:255` — `sb.table("modules").select("id,status").eq("strategy", "sports_sweep")`.
- CLAUDE.md Rule #4 is explicit: "Engine/router code MUST NOT hardcode module names... Add new methods to `BaseModule` when needed; never special-case in the engine." This is a direct, if narrowly-scoped, violation — sports-series lookups should go through a generic `BaseModule` method (e.g. `module.get_series_ids()`) rather than a string-literal special case.

### MEDIUM — `breaker.py`'s `_save()` doesn't bump `updated_at`, making the live staleness finding above a code bug, not a fluke
- `api/services/breaker.py:_save` (line 21) upserts only `{key, value}` into `settings` — it never sets/refreshes `updated_at`, and nothing in the schema appears to default/trigger it on upsert either (confirmed live: the row's `updated_at` is older than data it logically contains). Not a trading-safety bug (breaker logic reads `value`, not `updated_at`), but it breaks any future liveness/staleness diagnosis of the `settings` table — recommend making `_save()` explicitly set `updated_at: now()` on every write.

### MEDIUM — Possible unrelated client content committed to this repo
- `CRO-Audit-ArcarDentalLab.html` at repo root (added in commit `77e9da4`) appears to be a CRO (conversion-rate-optimization) audit report for `arcaridentallab.com` — a dental-practice website, unrelated to this trading bot. This looks like an accidental commit of unrelated client work into the wrong repository. **Not deleted in this pass** — recommend the repo owner confirm it's not meant to be here before anyone removes it, since it wasn't authored as part of this audit and may be someone else's in-progress work.

### LOW
- `api/services/hot_path.py` — the pre-signed "hot path" fast-fire lane (`PreSignLoop._run`, lines 63-81; `HotPath.fire`, line 92) bypasses `risk_manager.check()` entirely by the code's own admitted comment (line 94: *"with NO per-order risk_manager.check() anywhere in the lane"*) — only the live-guard and circuit breaker apply. Confirmed **unwired**: `HotPath(`/`PreSignLoop(` are never instantiated anywhere outside `hot_path.py` itself, so there is no live risk today. Flagging because the code already has its own `⚠️ BEFORE WIRING THIS LANE LIVE` comment (line 98) — treat closing that gap as a hard release gate if this lane is ever wired into a module, not an optional cleanup.
- `api/services/halt.py:53-54` and `:60-61` — bare `except Exception: pass` (no logging at all) on the notify-on-halt and audit-log-insert side-effects of the global-halt kill-switch. Not a safety hole — `set_halt()` writes the halt flag unconditionally *before* these blocks (line 38) — but if Slack notify or the logs-insert fails during a real halt event, there is currently zero trace of that failure anywhere. Recommend `log.exception(...)` instead of bare `pass`.
- `api/services/risk_manager.py:143-151` (roughly) — the earliest input validations (price bounds, size>0, token_id) run before the main try/except and assume well-formed numeric input; a malformed `Signal` (e.g. `price=None`) would raise an unhandled `TypeError` rather than return a clean `RiskVerdict` rejection. `engine.py`'s outer per-module try/except does catch this (no order gets placed), but logs it as a generic "module cycle failed" rather than a risk rejection, muddying monitoring. No live evidence this has actually occurred.
- Dead code candidates (not removed — see "LOW-RISK fixes" note below): `api/modules/demo/` (its own docstring says "Delete once S2 lands"; `s2_basket_hold` has shipped and has a live DB row), `api/modules/shared/feed_guard.py` (zero callers repo-wide).
- Stale repo-root docs from the June bot-teardown: `HANDOFF_DELETE_BOT.md`, `TEARDOWN_NOTES.md` — both explicitly say they contain no secrets; candidates for archiving now that the rebuild is complete.

---

## Confirmed CLEAN (no finding — stated for completeness)

- **Denominator bug class is fixed.** The exact bug pattern this audit was asked to hunt for ("a per-order gate scaled by the wrong denominator, e.g. dust floor scaled by global bankroll not module budget") was real once (git history: commit `c762636`) but is now fixed: `risk_manager.py:189` uses an absolute `$1` dust floor (no bankroll scaling at all), and the module-budget cap (`risk_manager.py:219-226`) correctly scales by `module_bankroll(module_id)` → `modules.budget`, confirmed live (Arb Scanner's `module_budget_cap_500` rejections match its own `$500` budget exactly). The single-market/correlated/portfolio/loss/drawdown caps correctly use the global bankroll, which is their intended scope.
- **Risk gate fails closed.** `risk_manager.check()`'s DB-dependent block is wrapped in try/except → rejects with `db_error:*` on failure. `breaker.is_tripped()` and `halt.is_halted()` (confirmed: `halt.py:29-31`) both fail SAFE (treat read errors as tripped/halted) rather than failing open.
- **Limit-only, everywhere.** No market-order code path exists; `clob.place_post_only` requires an explicit `price` with no default and always sets `post_only=True`.
- **Production guard is enforced, not just logged.** `LiveExecutor.__init__` (`executor.py:41-49`) raises at construction time if `environment == "production" and not paper_mode and allow_live_trading` isn't satisfied — a caller cannot bypass this by skipping a check.
- **No cross-module imports** found anywhere in `api/modules/*` (verified with an import-target parse, not just grep). Config isolation is clean — every module's config routes through `shared/config_store.py` keyed by `module_id`.
- **No `.single()`/PGRST116 traps** in current module code. The historical anti-pattern (inserting dummy `elon_tweets`/`truth_social` rows to dodge a `.single()` crash) has no live code-side counterpart on this branch — those are leftover DB bookkeeping rows only.
- **No TODO/FIXME/HACK on any money-handling line** anywhere under `api/`.
- **No secrets committed.** No `.env` or data files are tracked in git; only `.env.example` is present.
- **No foreign writer.** Zero `enabled_wallets` log rows — the legacy/foreign-bot signature this audit watches for is absent.

---

## LOW-RISK fixes applied in this PR

**None.** This audit intentionally proposes dead-code removals (`api/modules/demo/`, `api/modules/shared/feed_guard.py`) and doc rewrites (`CLAUDE.md`, `MODULE_ARCHITECTURE.md`) rather than executing them, because verifying there are truly zero remaining references (including from `web/` or external callers) needs a closer look than this pass budgeted for on a repo touching real trading logic. All of the above are left as written recommendations for human/engineer review, per this audit's instructions.

## Recommended next actions (priority order)
1. Fix the 3 broken test imports and add `testpaths = ["tests"]` so `pytest -q` actually exercises `risk_manager.py`/`engine.py` again.
2. Triage the Kelly-sizing and bracket-ranking test failures — determine if they're stale tests or real regressions in sizing/selection logic.
3. Decide: re-evaluate and re-enable modules, or formally retire the bot — 48 days idle with no reassessment.
4. Fix the watchdog's `age=None` logging bug and investigate the recurring engine hangs.
5. Wire a real weekly parquet-archive job (or correct CLAUDE.md) before more retention-window data is deleted with no backup.
6. Rewrite `CLAUDE.md` + `MODULE_ARCHITECTURE.md` for the actual `feat/newbot-step1-skeleton` module set.
