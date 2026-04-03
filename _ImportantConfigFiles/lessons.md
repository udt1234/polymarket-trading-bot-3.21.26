# PolyMarket Bot — Lessons Learned

Living mistake log. After every bug fix or correction, append a rule here.

## Format
```
### [DATE] — Short title
**What happened**: Description of the bug or mistake
**Root cause**: Why it happened
**Rule**: What to do differently going forward
```

---

### 2026-04-01 — Risk Auditor Found 6 Critical Issues
**What happened**: First full risk audit revealed 3 UNSAFE checks and 3 partially safe.
**Root cause**: Checks were scaffolded but never wired to live data or execution flow.
**Issues found**:
1. Circuit breaker `record_loss()`/`record_win()` never called from engine — breaker is dead code
2. Spread check always returns True — `pass` in rejection branch, uses edge not bid-ask spread
3. Liquidity check is empty stub — `depth_adjusted_size()` exists but never called
4. No global kill switch — only per-module kill, no `POST /api/engine/stop`
5. 7x `except Exception: pass` in risk_manager.py = fail-open on DB errors
6. Order type relies on py-clob-client default — no explicit `type: "GTC"`
**Rule**: Before going live, ALL 15 risk checks must be verified as functional by @risk-auditor. No stubs allowed.

### 2026-04-03 — All 6 Risk Issues Fixed
**What happened**: Implemented all fixes from the 2026-04-01 audit.
**Changes made**:
1. Circuit breaker wired — `record_loss()`/`record_win()` called from `resolution_tracker.py` on position close
2. Spread check — now uses real bid-ask spread from order book, rejects if > slippage_tolerance
3. Liquidity check — now checks order book depth, rejects if order > 30% of available depth
4. Global kill switch — `POST /api/engine/stop` stops engine + closes all positions + logs
5. Fail-closed — all 7 `except Exception: pass` in risk checks now return `False` with error message
6. Explicit GTC — `"type": "GTC"` added to `create_and_post_order` call
7. Signal dataclass — added `best_bid`, `best_ask`, `bid_depth_5`, `ask_depth_5` fields
8. Module — fetches order books for top brackets and passes data to signals
**Rule**: Never scaffold a risk check as a stub. If it can't be implemented yet, it must return False (fail-closed), not True.

### Rules Derived from Architecture Decisions
1. **Always use noon-to-noon boundaries** — xTracker auctions start/end at noon ET, not midnight. Off-by-12h errors silently corrupt projections.
2. **Dedup hourly rows before counting** — Overlapping Tue-Tue and Fri-Fri trackings return the same hours twice. Key = `YYYY-MM-DD|HH`, keep higher count.
3. **CLOB midpoints over Gamma prices** — Gamma prices lag. Use CLOB mid for edge calculation, Gamma as fallback only.
4. **ALWAYS use limit orders, never market orders** — Market orders on Polymarket have unbounded slippage. Every order placement must specify a price. No exceptions.
5. **ENV=production guard before any live execution** — Paper mode is default. Live executor must check `PAPER_MODE != true` before submitting to CLOB.
6. **Rate limit all external APIs** — 300ms between xTracker, 500ms between Gamma, 1s between CLOB history. Bursting gets IP banned.
7. **Google SA key was exposed in early session** — Rotated. Never put credentials in .md files, committed code, or .mcp.json.
