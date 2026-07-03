Staged files: !`git diff --cached --name-only`
Staged diff: !`git diff --cached`

Run in sequence. STOP and report if critical issues found.

## Step 0 — Detect scope
Check the staged files. If ANY of these paths are touched, the functional gate (Step 5) is REQUIRED:
  - api/modules/* (any module code)
  - api/services/risk_manager.py
  - api/services/exit_manager.py
  - api/services/engine.py
  - api/services/executor.py

Otherwise (docs-only, web/, scripts/, _DataMetricPulls/), Step 5 may be skipped.

If user passed `--skip-functional`, skip Step 5 BUT append a one-line audit entry to
`_ImportantConfigFiles/lessons.md`:
  `### [YYYY-MM-DD] — Functional verification skipped via --skip-functional`

## Step 1 — Code review
@qa-code-bug-hunter — bugs, edge cases, security, performance, trading-specific risks
BLOCK on critical findings.

## Step 2 — Strategy review (conditional)
@strategy-reviewer — if any files in api/modules/ or api/services/risk* changed
BLOCK on critical findings.

## Step 3 — Risk audit (conditional)
@risk-auditor — if any files touching orders, execution, or positions changed
BLOCK on critical findings.

## Step 4 — End-to-end paper trade (conditional)
@verify-bot — if trading logic changed, run full verification
BLOCK on critical findings.

## Step 5 — FUNCTIONAL GATE (HARD BLOCK)
@qa-functional-verifier — REQUIRED if any module/service code in scope (see Step 0).

This agent spins up the bot in paper mode and asserts each touched module:
  - loads without crashing
  - evaluates at least once
  - passes health assertions
  - produces expected behavior (signals on active auctions, etc.)

If functional verifier returns OVERALL: FAIL or ERROR → HARD BLOCK. Commit is rejected.
Code review claims of "fixed" are not sufficient without functional verification.

## Final summary
After all steps pass, post a single block:
  CODE: PASS — bug-hunter / strategy / risk audits clean
  FUNCTIONAL: PASS — bot starts, modules evaluate, health green
  Ready to commit.

If any step blocked, list the specific failure and stop. Do NOT proceed to commit.

NOTE: @qa-code-quality and @qa-architecture-quality are NOT in this chain by design.
They are heavier sweeps meant for periodic audits, NOT every commit. Invoke on demand:
  - Weekly or before major refactors → @qa-code-quality
  - Monthly or before adding a new module → @qa-architecture-quality
