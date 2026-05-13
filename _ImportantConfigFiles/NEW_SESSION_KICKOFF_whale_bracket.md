# Kickoff: Whale Watching + Bracket Analysis Cards on Spike Trading V2

**Purpose of this file:** Everything a fresh session needs to start executing the build with zero ramp-up time. Read this FIRST, then read `WHALE_BRACKET_CARDS_SPEC.md` for full implementation details.

---

## Paste-in prompt for the new session

Copy this exactly into a new Claude Code session:

```
read _ImportantConfigFiles/NEW_SESSION_KICKOFF_whale_bracket.md and execute it
```

The session should:
1. Read this file (the one you're reading right now) in full
2. Read `_ImportantConfigFiles/WHALE_BRACKET_CARDS_SPEC.md` in full
3. Confirm scope with the user in 2-3 lines (V1 = Spike Trading V2 only on elonmusk)
4. Create a feature branch `feat/whale-bracket-cards-v2` off `origin/master`
5. Begin Phase 1 (Bracket Analysis card)
6. Commit per sub-phase
7. Stop after each Phase for user review before continuing to next

---

## Scope (single source of truth)

| Question | Answer |
|---|---|
| Which module gets the cards? | **Spike Trading V2 ONLY.** Module identity in Supabase: row in `modules` table with `name = 'Spike Trading V2'`. Underlying Python code is `api/modules/spike_trading/` (the SAME module that Spike Trading V1 uses — they share code, different config rows in Supabase). |
| Which handle? | **`elonmusk`** on x platform, 2-day auction window only |
| Touch V1? | **NO.** V1 is running real trades. Do not modify its config, its dashboard page rendering, or backfill its signals. |
| Other modules? | **NO.** Truth Social, Elon Tweets, etc. — their dashboard pages render no whale/bracket card in v1 |
| Data sources | (1) xTracker for closed-auction `finalValue`; (2) parquets in `_DataMetricPulls/whale_analysis/trades_elon-musk-of-tweets-*.parquet` (220 files) for whale fills; (3) Supabase `signals`/`trades` filtered to V2's `module_id` for "your trade share" columns |
| Phases | **Phase 1 → Phase 2 → Phase 4.** Skip Phase 3 (cross-module generalization) in v1. |
| Branch | `feat/whale-bracket-cards-v2` off `origin/master` |
| Commit cadence | One commit per sub-phase (migration, service, endpoint, components, wiring). User reviews between phases. |

---

## V1 Feature flag (CRITICAL)

The cards render ONLY when the module's name matches `'Spike Trading V2'`. Implement in the dashboard page:

```tsx
// web/app/modules/[id]/page.tsx
const showCards = module.name === 'Spike Trading V2'
return (
  <>
    {/* existing dashboard content */}
    {showCards && <BracketAnalysisCard moduleId={module.id} />}
    {showCards && <WhaleWatchingCard moduleId={module.id} />}
  </>
)
```

This guarantees V1 (and every other module) stays exactly as it is.

---

## Existing infrastructure the next session inherits

### Dashboard components already present
Path: `web/app/modules/[id]/components/`

- `collapsible-card.tsx` — REUSE for both new cards
- `bot-health-banner.tsx`, `live-status-badge.tsx` — existing patterns to match
- `pnl-curve.tsx`, `positions-table.tsx`, `pending-signals-card.tsx` — examples of data-table layout

### Supabase migrations
Latest: `supabase/migrations/012_status_simplification.sql`
Next migration: `013_whale_bracket_cards.sql`

### Parquet inventory
Path: `_DataMetricPulls/whale_analysis/`
Count: **220** files matching `trades_elon-musk-of-tweets-*.parquet`
Format: pandas-readable parquets with columns including `_bucket`, `outcome`, `price`, `hours_in`, `maker`, `taker`, `side`, `size`, `timestamp`

### Spike Trading V2 module code
Path: `api/modules/spike_trading/`
Key files: `module.py` (entry), `data.py`, `module_config.py`, `decision.py`
The Python module `get_handle()` method returns `'elonmusk'` by default — confirmed.

### xTracker API
Endpoint: `https://xtracker.polymarket.com/api/users/elonmusk/trackings`
Returns: list of all `elonmusk` 2-day auctions with `startDate`, `endDate`, `finalValue`, etc.
The bot already uses this in `api/modules/shared/` — pattern exists.

---

## Phase-by-phase plan (with stop points)

### PHASE 1 — Bracket Analysis card (4-6 hours)

**Stop point:** Ship the bracket card visible on Spike Trading V2's dashboard, get user review, THEN move to Phase 2.

Sub-phases (commit after each):

1. **Schema migration** — `supabase/migrations/013_whale_bracket_cards.sql`
   - Add `signal_type` column to `signals` table
   - Add `bracket_stats_cache` table
   - Backfill `signal_type` UPDATE filtered to `module_id = (SELECT id FROM modules WHERE name = 'Spike Trading V2')`
   - Run migration locally and verify against staging Supabase

2. **Backend service** — `api/services/bracket_stats.py`
   - Reads from xTracker for historical bracket win % (years of elonmusk 2-day data)
   - Reads from Supabase `signals` + `trades` for "your trade share" columns
   - Computes EV/trade per bracket
   - Returns the data structure defined in spec's `/brackets` endpoint response

3. **Headlines engine** — `api/services/rules_engine.py`
   - Implement bracket-analysis rule table from spec (7 rules)
   - Generates 3-5 line headline with explicit dollar action arrows
   - Pure functions, no LLM

4. **API endpoint** — `api/routers/modules.py`
   - `GET /api/modules/{module_id}/brackets`
   - Query params: `mode`, `window`, `reserve_pct`
   - Cache 60s

5. **React components** — `web/app/modules/[id]/components/`
   - `bracket-analysis-card.tsx` (main)
   - `bracket-stats-table.tsx`
   - `bracket-comparison-table.tsx`
   - `bracket-allocation.tsx`
   - `card-headline.tsx` (generic, reused for both cards)

6. **Wire into dashboard** — `web/app/modules/[id]/page.tsx`
   - Feature flag check: only render if `module.name === 'Spike Trading V2'`
   - Place new card AFTER existing pnl/positions content

7. **Test end-to-end** — Open V2's dashboard in browser, verify card renders, verify V1's dashboard does NOT show the card.

---

### PHASE 2 — Whale Watching card (6-8 hours)

**Stop point:** Ship whale card + nightly cron. Run initial backfill on 220 parquets. User reviews before Phase 4.

Sub-phases:

1. **Schema migration** — extend `013_whale_bracket_cards.sql` (or new `014_*.sql`)
   - `whale_snapshots` table
   - `whale_wallet_profiles` table
   - Indexes per spec

2. **Whale classifier service** — `api/services/whale_classifier.py`
   - Port logic from existing scripts in `scripts/whale_*.py` if any exist
   - Implement the 5 archetypes per spec rules
   - Cache "career sharpness" per wallet (across all elonmusk parquets)

3. **Snapshot orchestrator** — `api/services/whale_snapshot.py`
   - Reads a parquet file
   - Classifies all wallets active in that auction
   - Writes one `whale_snapshots` row per (handle='elonmusk', auction_slug)
   - Idempotent (UNIQUE constraint handles repeat runs)

4. **Initial backfill script** — `scripts/backfill_whale_snapshots.py`
   - Iterates all 220 elon parquets
   - Runs the orchestrator on each
   - Logs progress every 10 files
   - Total runtime estimate: ~5-15 min

5. **Nightly cron script** — `scripts/refresh_whale_snapshots.py`
   - Only processes auctions that closed in last 24h
   - Handles list: `['elonmusk']` only in v1

6. **API endpoints** — `api/routers/modules.py`
   - `GET /api/modules/{id}/whales`
   - `GET /api/modules/{id}/whales/wallets/{wallet}`

7. **Whale rules engine** — extend `api/services/rules_engine.py`
   - Implement whale-watching rule table from spec (8 rules + always-last action arrow)

8. **React components**
   - `whale-watching-card.tsx` (main)
   - `whale-archetype-bar.tsx`
   - `whale-top-table.tsx`
   - `whale-grid.tsx`
   - `whale-wallet-detail.tsx` (collapsible per-wallet)

9. **Wire into dashboard** — same feature-flag pattern as Phase 1

10. **Railway cron service** — add nightly cron service (similar to the existing `cron-anchor-alert` and `cron-spike-alert` services we set up). Schedule: `0 7 * * *` (3 AM ET in UTC).

---

### PHASE 4 — Polish (2-3 hours)

**Stop point:** Cards are production-ready.

1. Wallet detail expansion (sparkline of per-auction ROI, bucket pref bar chart, hour density heatmap)
2. User-editable `reserve_pct` slider in allocation block
3. Copy-to-clipboard for wallet addresses
4. Mobile responsive layout
5. Loading skeletons during fetch
6. Error states (xTracker down, Supabase down, no parquets found)

---

## Do NOT in v1 (recap)

- Don't modify `api/modules/spike_trading/module.py` code logic — V1 uses the same code path
- Don't render cards on Truth Social or Elon Tweets module pages
- Don't process parquets other than `trades_elon-musk-of-tweets-*.parquet`
- Don't auto-apply allocation recommendations to module config — read-only in v1
- Don't include V1's `module_id` in any backfill SQL — scope strictly to V2's `module_id`
- Don't break the V1 dashboard. Test it after every commit by opening V1's page and confirming nothing changed.

---

## Files the next session will create

### New files (Phase 1)
- `supabase/migrations/013_whale_bracket_cards.sql`
- `api/services/bracket_stats.py`
- `api/services/rules_engine.py`
- `web/app/modules/[id]/components/bracket-analysis-card.tsx`
- `web/app/modules/[id]/components/bracket-stats-table.tsx`
- `web/app/modules/[id]/components/bracket-comparison-table.tsx`
- `web/app/modules/[id]/components/bracket-allocation.tsx`
- `web/app/modules/[id]/components/card-headline.tsx`

### New files (Phase 2)
- `supabase/migrations/014_whale_snapshots.sql` (or extend 013)
- `api/services/whale_classifier.py`
- `api/services/whale_snapshot.py`
- `scripts/backfill_whale_snapshots.py`
- `scripts/refresh_whale_snapshots.py`
- `web/app/modules/[id]/components/whale-watching-card.tsx`
- `web/app/modules/[id]/components/whale-archetype-bar.tsx`
- `web/app/modules/[id]/components/whale-top-table.tsx`
- `web/app/modules/[id]/components/whale-grid.tsx`
- `web/app/modules/[id]/components/whale-wallet-detail.tsx`
- `railway-whale-snapshot-cron.toml` (similar to existing cron configs)

### Modified files (both phases)
- `api/routers/modules.py` — add new endpoints
- `api/modules/shared/base.py` — add `get_market_universe()`, `get_brackets()`, `get_spike_metric()` (default no-op implementations)
- `api/modules/spike_trading/module.py` — override the 3 BaseModule methods (only Spike V2 module overrides them; V1 inherits the no-op defaults, which is fine because V1's dashboard won't render the cards anyway thanks to the feature flag)
- `web/app/modules/[id]/page.tsx` — add feature-flagged card renders

---

## How the next session should START

1. **Acknowledge** by saying: "I've read the kickoff doc and the spec. Scope is Spike Trading V2 only, on elonmusk, with phases 1→2→4. Creating branch `feat/whale-bracket-cards-v2` off `origin/master` and starting Phase 1 sub-phase 1 (schema migration). Will commit per sub-phase and stop for review between phases."
2. **Branch creation:** `git fetch origin && git checkout -b feat/whale-bracket-cards-v2 origin/master`
3. **Begin Phase 1 sub-phase 1:** Write `supabase/migrations/013_whale_bracket_cards.sql`. Get user to confirm migration looks right BEFORE running it against Supabase.
4. **Run migration** locally + production (if user approves).
5. **Continue through sub-phases** with a commit after each.

---

## Anti-patterns from prior sessions to avoid

These came up earlier today — flagging so next session doesn't repeat:

1. **Don't spam Slack on first run.** If anything posts to Slack, use a baseline/dry-run mode for the first execution.
2. **Don't push to wrong row positions in a grid.** Always read the actual structure (BRACKET header row) before writing values. Mismatches earlier today required a 32-cell header-restore script to recover.
3. **Don't mix YES and NO outcomes in price aggregations.** Always filter `outcome == 'Yes'` before computing means on whale fills.
4. **Don't write blanket UPDATEs in SQL.** Always scope to specific `module_id`. Earlier signals migration almost touched V1 by accident.
5. **Don't bury the lede in long files.** Cap markdown files at 150 lines per CLAUDE.md rules. Split if needed.

---

## Open questions for the next session to confirm with user before coding

The next session should ask the user EXPLICITLY in the first message:

1. "Spike Trading V2's `module_id` in Supabase — what's the UUID?" (Or we can query for it via `SELECT id FROM modules WHERE name = 'Spike Trading V2'`.)
2. "When I run the initial parquet backfill (~5-15 min), it'll write ~220 rows to `whale_snapshots`. OK to run that against production Supabase, or only staging?"
3. "Confirm: the migration should NOT touch Spike Trading V1's `module_id`. Will scope all UPDATEs/INSERTs accordingly. OK to proceed?"
4. "Phase 4 polish — do you want it in the same session, or a follow-up after Phases 1+2 are live for a few days?"

Don't proceed past Phase 1 sub-phase 1 (the migration) until these are answered.
