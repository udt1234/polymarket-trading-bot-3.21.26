Staged files: !`git diff --cached --name-only`
Staged diff: !`git diff --cached`

Run in sequence. STOP and report if critical issues found:
1. @qa-reviewer — bugs, edge cases, security, consistency
2. @strategy-reviewer — if any files in api/modules/ or api/services/risk* changed
3. @risk-auditor — if any files touching orders, execution, or positions changed
4. @verify-bot — if trading logic changed, run full verification

Only proceed to commit if all checks pass.
Report a summary of findings before committing.
