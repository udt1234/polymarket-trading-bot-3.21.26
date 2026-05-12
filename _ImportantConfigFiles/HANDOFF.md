# PolyMarket Bot — Handoff

## Current State (2026-05-11)
Bot LIVE on Trump + Elon (ensemble) + Spike Trading (multi-auction multi-strategy plugin architecture; paper-trading via global `PAPER_MODE=true`). All on Railway.

### 2026-05-11 — Dashboard cleanup + bracket-grid fixes
- **Modules-list P&L** — `/api/modules/` now enriches each row with `pnl` (realized + unrealized for OPEN positions) and `open_positions` count. Card stops showing $0 / 0 placeholder.
- **Bracket Analysis current-grid filter** — `auction_archive` rows are now filtered to the current Polymarket bracket grid (≥50% overlap) before computing stats. Stops mixing Elon's old 0-9/10-19/.../80+ grid into the current `<40, 40-64, ..., 240+` grid. Resilient to empty `bracket_outcomes` by walking back up to 5 rows.
- **Numeric bracket sort everywhere** — `<40` first, `240+` last via `sortBrackets()` helper in `web/lib/utils.ts`. Applied to price heatmaps, auction-deep-dive, bracket_stats backend (`_bracket_lo`).
- **Posting Patterns mega-card** — replaced 4 redundant cards (Post Timing Heatmap, Post Frequency, DOW Averages Heatmap, Hourly Posts Heatmap) with one card + 3 tabs (Day×Hour grid, Hour-of-Day strip, Auction Progress) + plain-English headline. New `historical_daily` field on pacing payload (per-elapsed-day post curve from completed matching-window trackings). Deleted `post-timing-grid.tsx` + `post-frequency-chart.tsx`.

## ⭐ Cross-Module Patterns (apply to ALL modules going forward)

These are architectural patterns proven on Spike Trading. **Other modules should adopt them.** Each module's `module.py` + dashboard surface should match.

### 1. Pluggable Strategy Plugins
- Module picks logic via a `Strategy` subclass registry (`api/modules/spike_trading/strategies/`).
- Each strategy implements `can_enter`, `build_buy_ladder`, `classify`, `sell_targets`, `display_label`, `describe` + sets `DEFAULT_PARAMS`.
- Auto-discovered via `__init_subclass__`. Adding a strategy = drop a file.
- Registry pattern: `api/modules/spike_trading/strategies/__init__.py` (good model to copy).

### 2. Multi-Auction × Multi-Profile Config
- Each module's config has `auction_types: [...]` list — each auction type holds a `bracket_profiles` list.
- Per profile: `strategy_name`, `bracket_max_count`, `params` overrides.
- Module's `_evaluate_async` iterates enabled auction_types × profiles, dispatches to plugin.
- Frontend: `<AuctionTypesEditor>` component (in spike_trading components) handles nested editing.

### 3. Pacing Prior — DOW-Aware + Recent-Regime
- **Lesson** (2026-05-07): historical "weekly_totals" averages are stale. Past 2-day Elon auction means (94.7) didn't reflect his recent 23/day rate.
- **Fix shipped in `api/routers/modules.py:get_pacing`**: blends three priors in this order:
  1. `recency_weighted_averages(weekly_history)` — past matching-window event totals
  2. **Recent flat-rate** — last N days of post counts × auction window length
  3. **DOW-aware** — for each day in the auction window, sum the historical per-DOW avg
- Helper: `fetch_recent_post_history(handle, platform, days=30)` in `polymarket.py` returns daily counts AND by-DOW breakdown.
- Blend weight on recent prior tapers from 0.85 (fresh) to 0.20 (late).
- **Apply to Trump + Elon ensemble**: their pacing endpoints currently only use the historical weekly mean. Should adopt the same recent + DOW prior.

### 4. Polymarket-Native Bracket Discovery
- **Always** pull bracket labels from the actual Polymarket auction (via `fetch_market_prices` + Gamma `/events` fallback for closed markets).
- Don't hardcode bracket grids. Trump's old 11-bracket assumption was wrong for Elon.
- Pattern: `api/routers/modules.py` lines 1080-1110 (computes `dynamic_brackets`).

### 5. Window-Length Filter on Historical Means
- `fetch_historical_weekly_totals(handle, weeks, platform, target_window_days=...)` filters past trackings by matching window length (±0.5d).
- Without this, Elon's 7-day + monthly mixed into a "weekly" mean → garbage 2-day projections.
- Same `target_window_days` param needed in any new module that pulls historical priors.

### 6. Confidence Bands UI — Bot vs Polymarket
- `<ConfidenceBands>` component shows BOT probability AND Polymarket price side-by-side per bracket.
- Highlights edge (signed delta when ≥5pp disagreement).
- Pattern: `web/app/modules/[id]/components/pacing-analysis.tsx`.
- **Apply to Trump + Elon dashboards**: same component, same `marketPrices` prop.

### 7. Schema-Driven Editable Config
- `BaseModule.get_config_schema()` returns field descriptors.
- Frontend `<DynamicConfigForm>` auto-renders editable inputs.
- Adding a config knob = add to schema, no React work.

### 8. Status Model: active / paper / inactive
- 3 states only. `inactive` carries a structured `inactive_reason` (manual_pause / kill_switch / circuit_breaker / data_stale / error / scaffold).
- Single dashboard dropdown: Real $Trades / Paper Trades / Pause.
- Per-module executor routing: env `PAPER_MODE` is override-only; module status decides paper-vs-live per signal.

### 9. Closed-Auction Override
- When `is_complete=True`, projections override to actual outcome (100% on the winning bracket).
- Lesson: never extrapolate past `remaining_days <= 0`.
- Pattern: `api/routers/modules.py:get_pacing` — `if is_complete and running_total > 0` block.

### 10. Verified-Parquet Ground Truth
- Backtests should pull per-event winners from parquet via `verify_winrate_v2.py` pattern (group by event_stem, find winning bracket per event).
- The `pct_resolved_yes` column in `per_bracket_end_price.csv` is **per-bracket, not per-event** — easy to misread. Always re-verify with per-event grouping.

---

## Module Status

| Module | Strategy | Status | Notes |
|---|---|---|---|
| **Trump (truth_social)** | ensemble (legacy) | active (paper) | NOT touched per user 2026-05-06 |
| **Elon (elon_tweets)** | ensemble (legacy) | active (paper) | NOT touched |
| **Spike Trading** | pluggable plugins | active (paper) | New architecture (commit 75d3567 + hardening 95cbf18) |

### Spike Trading Plugin Inventory
- `Cheap_Lottery_Pacing` — 5-tier descending ladder for `<40` brackets. Pacing classifier + sellnow grid + slow-bleed.
- `Mid_Range_Spike` — 6h delayed entry, mid-priced ladder, absolute sell targets at 30/50/70¢. For arc-tradeable brackets (65-89, 90-114, 40-64).
- `Big_Hold_Monthly` — week-1-only entry, hold to resolution, very loose stop. For monthly 1400+.

Adding a strategy = new file in `api/modules/spike_trading/strategies/`.

---

## Open Work

### 🚦 LIVE-FLIP PROCEDURE (Spike Trading)
1. **Run the token_id backfill** for any pre-existing open positions:
   ```
   python scripts/backfill_position_token_ids.py            # dry-run, prints would-write actions
   python scripts/backfill_position_token_ids.py --apply    # writes
   ```
   Live SELLs refuse to submit when `positions.token_id IS NULL`. Backfill or close any paper-era open positions first.
2. **Apply migration 015** (`positions_token_id.sql`) — adds the `token_id` column.
3. **Verify Railway env vars on Bot-API service**: `PAPER_MODE=false`, `ENV=production`.
4. **Verify `SLACK_WEBHOOK_URL`** (or equivalent — `notifications.py:send_slack`) is set; daily digests run at 9 AM ET + 5 PM ET.
5. **Open the Spike Trading module dashboard** → status dropdown → "Real $ Trades". This writes `status='active'` to the modules row.
6. **Watch the next cycle log** for `"Live executor ready"` and confirm the first signal is routed via LiveExecutor (or rejected with `signal has no token_id` if backfill missed something).

### Whale Watching card (Phase 2 of `WHALE_BRACKET_CARDS_SPEC.md`)
Zero files exist yet. Needs: `whale_snapshots` + `whale_wallet_profiles` Supabase tables, `whale_classifier.py` (5-archetype detection: Market-Maker / Tail Scooper / Spike Trader (=us) / Pace Chaser / Tail Punter), `whale_snapshot.py` orchestrator, nightly Railway cron, `/api/modules/{id}/whales` endpoint, 5 TSX components. Recommend: Spike-only first + 90-day backfill (~half a day). Spec estimate: 8-10 hr full Phase 2.

### Other high priority
- **Apply patterns 3 + 6 to Trump + Elon ensemble modules.** Their pacing prior is stale and their Confidence Bands don't show Polymarket prices. ETA: ~1 day.
- **Bot vs market disagreement gating.** When the bot's top bracket diverges sharply (>30pp) from Polymarket's top, log a warning and reduce signal confidence. Right now we trust the model unconditionally.

### Medium priority
- **Migrate Trump + Elon to multi-auction config**. Currently single-bracket. Could enable Trump-7day-multi-bracket trading with the same architecture.
- **Bracket arc analysis for monthly auctions** — only 6 monthly samples in cache, need more before relying on monthly priors.

### Low priority
- Cache `_first_enabled_auction()` in spike module (QA-flagged perf).
- ThreadPoolExecutor + asyncio refactor (pre-existing structural risk).
- Auth on `/modules/*` router (pre-existing security gap).

---

## Key Config

| | Value |
|---|---|
| Trump module ID | `e858d9ed-da0d-4e9a-8bef-2c2830686a5a` (Truth Social Posts) |
| Elon module ID | `cac300cb-5af2-4c25-a7df-3069478aefdb` (Elon Tweets) |
| Spike module ID | `4faba37c-906b-405f-ad49-737b12e75b16` (Spike Trading) |
| Slippage tolerance | 0.05 |
| Auto-pause threshold | 5 consecutive losses |
| Order TTL | 5min default; 24h for Spike BUYs |
| Dashboard widths | full / 1/2 / 1/3 (CSS grid) |
| Daily Slack digests | 9 AM ET + 5 PM ET (UTC 13:00 + 21:00) |

## URLs
- Dashboard: polybot-dashboard.up.railway.app
- API: polymarket-trading-bot-32126-production.up.railway.app
- Prod Supabase: xdonwowgqvmtrduikaon.supabase.co

## Operational
- Trump backfill: ✅ complete (32,880 posts, walked to 2022). `backfill_progress.is_complete=true`.
- IFTTT webhook for Elon X: needs `WEBHOOK_SECRET` env var; payload spec in `api/routers/webhooks.py`.
- Backfill scripts: `scripts/backfill_xtracker_history.py` (idempotent, ~5min) + `scripts/backfill_truth_social.py` (idempotent, 8-24h, `--forward` for incremental).
- Parquet historical: streamed via `_DataMetricPulls/duckdb_remote.py` — HF token in `~/.credentials/shared.env`.
- Pre-2026-05-05 session history preserved in git (`git log --before=2026-05-05`).
