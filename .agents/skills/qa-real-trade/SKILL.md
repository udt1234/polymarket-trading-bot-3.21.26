---
name: qa-real-trade
description: Prove the bot can actually execute a round-trip trade end-to-end on the LIVE deployed Railway instance. NOT a pipeline check, NOT a code review — forces a real signal through risk → executor → orders table → positions table → SELL → realized P&L. Use whenever Sir asks "is this ready to trade", "can it actually buy", "verify trades work", before flipping any module from paper → active, or before declaring a strategy/executor change shipped. The /verify-bot and /qa-functional-verifier checks are pipeline-level; this skill is the ONLY thing that proves trades actually happen.
---

# /qa-real-trade — Round-Trip Trade Verification

## Why this skill exists
vAI has repeatedly told Sir "ready to trade" after running pipeline-level QA (verify-bot, qa-functional-verifier). Every time, real trades have broken on something the pipeline check could not catch:
- Phantom `spike_positions` rows blocking entry
- `OrderArgs` / `ApiCreds` dataclass contract drift in py_clob_client
- `copy_trading` missing `get_handle()`
- Risk-manager kelly_pct cap exploding on neg_risk markets (min_tick=0.001)
- Open positions blocking ladder re-emission with no operator-visible reason

Code-level QA proves the car starts. This skill drives it around the block.

## What counts as PASS
A PASS requires **all six** of these, in order, observed on the **LIVE Railway-deployed instance** (not local):

1. **Signal emit**: a fresh BUY signal lands in Supabase `signals` table for the target module/market with `created_at` inside the verification window
2. **Risk accept**: the same signal is logged with `decision='accepted'` (no rejection) in the decision log
3. **Order placed**: an `orders` row appears with `status='filled'` (paper executor) OR `status='submitted'` then `filled` (live executor), `side='BUY'`, matching market_id + bracket
4. **Position opened**: a `positions` row appears with `size > 0` and `status='open'`, linked to the order
5. **SELL round-trip**: force a SELL signal on the same position. Order fills. Position flips to `status='closed'` with a non-null `realized_pnl`
6. **Audit trail clean**: no `severity='error'` log rows fire on the test module during the window

ANY missing step = FAIL. Do not soften this. Do not say "mostly working."

## Pre-flight (before forcing any test signal)
- Confirm Railway env vars on the live instance: `PAPER_MODE` (advisory), Supabase keys, polymarket creds for live profiles
- Confirm target module exists in `modules` table and `status` is set as expected (`paper` for paper-mode round-trip, `active` only with explicit Sir authorization)
- Confirm the target market exists, is open, has non-zero `best_bid` and `best_ask`, and is not at the tick floor
- Confirm no existing OPEN position for the target market+bracket (clear or pick a different bracket)
- Confirm engine cycle is running (last `Cycle:` log within 10 min)

If any pre-flight fails: STOP. Report the blocker. Do not proceed to forcing a signal.

## How to force a signal
Two paths — prefer A:

**A. Bot-driven (cleanest):** wait for the next natural cycle on a fresh auction. Verify the bot emits a BUY signal on its own. This is the most authentic test because it exercises the real discovery + decision path. Time-bounded to one full cycle window (typically 5 min).

**B. Manually-inserted (when no fresh auction available):** insert a Signal row directly via the `/api/admin/test-signal` endpoint if it exists, OR write directly to `signals` table with a known-good market_id + bracket + token_id + price. Mark `metadata.test_signal=true` so it can be cleaned up later. NEVER use Path B on a live (real-money) module.

## How to verify each step
Run these queries via the Supabase REST API (service key) against the live database:

```
-- 1. Signal emit
GET /rest/v1/signals?module_id=eq.{ID}&created_at=gte.{WINDOW_START}&order=created_at.desc&limit=5

-- 2. Risk decision
GET /rest/v1/logs?module_id=eq.{ID}&log_type=eq.risk&created_at=gte.{WINDOW_START}&order=created_at.desc

-- 3. Order placed
GET /rest/v1/orders?module_id=eq.{ID}&created_at=gte.{WINDOW_START}&side=eq.BUY&order=created_at.desc

-- 4. Position opened
GET /rest/v1/positions?module_id=eq.{ID}&status=eq.open&order=created_at.desc&limit=5

-- 5. After SELL: position closed
GET /rest/v1/positions?id=eq.{POSITION_ID}
   expect status=closed, realized_pnl not null

-- 6. Error scan
GET /rest/v1/logs?module_id=eq.{ID}&severity=eq.error&created_at=gte.{WINDOW_START}
   expect zero rows
```

## Output format (no persona — Drop Zone)

```
QA-REAL-TRADE RESULT
====================
Target module: <name> (<id>)
Target market: <slug> bracket=<bracket>
Mode: paper | live
Window: <start_iso> -> <end_iso>

Step 1 - Signal emit:    PASS | FAIL [reason]
Step 2 - Risk accept:    PASS | FAIL [reason]
Step 3 - Order filled:   PASS | FAIL [reason]
Step 4 - Position open:  PASS | FAIL [reason]
Step 5 - SELL round-trip: PASS | FAIL [reason]
Step 6 - No errors:      PASS | FAIL [error log rows]

Evidence:
  signal_id: <uuid>
  order_id: <uuid>  status=<filled|...>
  position_id: <uuid>  realized_pnl=<value>

OVERALL: PASS | FAIL
```

## What you DO NOT do
- Do NOT run on localhost. The bot has env+credential drift between local and Railway. PASS on local means nothing.
- Do NOT skip the SELL leg. A BUY-only PASS has never caught real bugs; the SELL path is where exit_manager, position_manager, executor SELL logic, and CLOB SELL minimums actually engage.
- Do NOT declare PASS based on absence of errors. Absence of errors with absence of activity is the default failure mode.
- Do NOT extrapolate from one module to another. PASS on Spike does not mean Elon works. Test each module independently when its code changed.
- Do NOT trust the pre-flight to confirm a real fill. Always check the actual `orders.status` and `positions.size` AFTER the cycle.

## When to invoke
ALWAYS before:
- Flipping a module from `paper` → `active` (real money)
- Saying "the bot is ready" / "ready to trade" / "trades work"
- Closing a PR that touched signal emission, risk_manager, executor, exit_manager, position_manager, or any module's `module.py`
- Cutting a Railway deploy that affects trading
- Investigating "why isn't my bot buying"

Invoke automatically (per AGENTS.md gate behavior) as part of `/pre-commit` when changes touch:
- `api/services/risk_manager.py`
- `api/services/executor.py` or `paper_executor.py`
- `api/services/exit_manager.py`
- `api/services/position_manager.py`
- `api/services/engine.py`
- `api/modules/*/module.py`

## Relationship to other QA agents
- `@qa-code-bug-hunter` — finds bugs in code. Does not run trades.
- `@verify-bot` — checks the pipeline shape. Does not run trades.
- `@qa-functional-verifier` — checks the bot evaluates modules and emits signals. Does NOT verify orders fill or positions open or P&L realizes.
- `qa-real-trade` (this skill) — the ONLY check that proves an actual round-trip trade completes end-to-end. Required as final gate.

The first three are necessary but not sufficient. This skill is the sufficient one.

## Failure semantics
- FAIL on any step = HARD STOP. Do not proceed to subsequent steps.
- Report the FIRST failing step + the evidence (log row, missing row, error message).
- Recommend a concrete next action ("inspect orders.error_reason for order_id={X}", "check executor logs at {timestamp}", etc.).
- Never paper over a partial pass as "good enough" — the user's trust is the cost of every false positive.

## Common failure modes vAI has shipped before (check for each on FAIL)
- Open position blocking new entries → check `spike_positions` / `positions` for the bracket
- Phantom position with size=0 in MONITORING → auto-liquidation may not have run
- `OrderArgs` dataclass shape mismatch → py_clob_client version drift, check imports
- `ApiCreds` passed as dict → executor.py:295 must use the dataclass
- `kelly_pct` exceeds per-trade cap on neg_risk markets → risk_manager rejection log will say so
- `min_tick` floor reached → `_build_buy_ladder_for_profile` drops the entire ladder silently (logs "best_ask at tick floor")
- No `token_id` on signal → executor raises ValueError before order placement
- Module status='paper' but Sir expected 'active' → check `modules.status` column directly
- `strategy='ensemble'` on a Spike row but matches via name fallback → works but brittle, flag it
