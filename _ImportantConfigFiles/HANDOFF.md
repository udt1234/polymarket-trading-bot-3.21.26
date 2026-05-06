# PolyMarket Bot — Handoff

## Current State (2026-05-05 evening)
Bot LIVE on Trump + Elon + Spike Trading (all paper-trading; global `PAPER_MODE=true`). Big day — many things shipped. Snapshot:

### Shipped today (in commit order)
1. **Spike Trading v2 module** — `api/modules/spike_trading/` (commits `8a4f818` → `c2fc4bd`). Module row id `4faba37c-906b-405f-ad49-737b12e75b16`. Migrations `010_spike_positions.sql` + `011_archive_trump_elon_history.sql` + `012_status_simplification.sql` applied.
2. **Polymarket Series API discovery** (`542ccc3`) — replaces xTracker as primary auction source; sees auctions ~2 days before xTracker activates.
3. **Adaptive prices + pacing classifier + slow-bleed exit** (`66fa41c`) — buy at 12¢/0.5¢ ladder, sell multipliers `[1.5, 2.0, 4.0, 8.0]` of fill price, auto-exit on bracket-bust extrapolation, no manual stuck-position intervention.
4. **Status model simplified** (`b4161be`) — `paused`/`killed`/`scaffold` collapsed to `inactive` + structured `inactive_reason` + `inactive_since` + `inactive_detail`. Three badges: Real $Trades / Paper Trades / Inactive.
5. **Trump+Elon trading history archived** (in `b4161be` migration 011) — 18 positions / 3,121 orders / 3,121 trades / 2,323 signals / 1,486 pending → `*_archive_20260505` tables. Live tables clean. **Preserved**: truth_social_posts (32,880 backfilled), post_count_snapshots, price_snapshots, logs, modules, backfill_progress.
6. **Per-module executor routing + status dropdown** (`9142da9`) — global PAPER is override-only; module status decides paper-vs-live per signal. Single dropdown replaces Pause+Kill (Kill removed from UI; API kept).
7. **Window-day filter for dashboard auctions** (`f5c1080`) — Spike Trading dropdown only shows 2-day Elon auctions, not the 7d/31d series.
8. **Pacing-config crash fix** (`1b78905`) — non-ensemble modules no longer crash the page.
9. **Schema-driven editable config** (`dda4c58`) — Spike's config is fully editable from the dashboard via `BaseModule.get_config_schema()`. New modules get free editable UI by declaring their schema. See `MODULE_ARCHITECTURE.md` for the convention.

### Removed
- `shadow_mode` config knob — was redundant with Paper Trading.
- `paused` / `killed` / `scaffold` status values — collapsed into `inactive`.

### Open work / next
- Trump + Elon strategy recalibration on the 3.5-year parquet dataset (see TODO section below).
- Trump + Elon ensemble config UI is still the hand-built React component; could migrate to the schema-driven form for consistency, but no functional benefit yet.

### Spike Rider v1 revert checklist (done 2026-05-05)
- ✅ Module row deleted from `modules` table
- ✅ `auction_series` and `position_exit_state` tables dropped
- ✅ All `spike_rider` code reverted via revert commit on master
- ✅ Trump + Elon modules untouched
- See `SPIKE_RIDER_SPEC.md` for the v1 rebuild plan (informed v2 architecture)

## ⭐ NEW: Full 3.5-Year Polymarket History via Parquet (2026-05-05)
We now have free streaming access to the **complete Polymarket trade history** (Nov 2022 → present, 766M trades, 1M markets) via the SII-WANGZJ HuggingFace dataset.

**Tooling added** (in `_DataMetricPulls/`):
- `duckdb_remote.py` — DuckDB connection helper. Streams Parquet files from HF over HTTPS, caches metadata locally, exposes `markets` / `quant` / `trades` SQL views.
- `full_history_analysis.py` — strict-recurring classification + flip-pattern ranking using the full 3.5y dataset.
- `duckdb_cache/polymarket_remote.duckdb` — persistent DuckDB cache (materialized tables live here, ~150MB).
- HF token stored at `~/.credentials/shared.env` as `HF_TOKEN`.

**vs the previous LuciferForge $9 buy** (which we kept):
| Source | Cost | Time | Trades | Markets |
|---|---|---|---|---|
| LuciferForge SQLite | $9 | 30 days (Mar–Apr 2026) | 8M | 9.5K |
| SII-WANGZJ Parquet | $0 | 3.5 years | **766M** | **1M** |

Use `duckdb_remote` whenever you need historical context beyond the bot's own `price_snapshots` table (~3 months) or the LuciferForge sample (30 days).

---

## TODO — Update Trump + Elon Modules with Parquet Data
**Added: 2026-05-05**

We now have access to the **full SII-WANGZJ Polymarket dataset** via DuckDB+HuggingFace streaming (3.5 years of trade history, 766M trade events, 1M markets — see `_DataMetricPulls/duckdb_remote.py` and `_DataMetricPulls/full_history_analysis.py`).

**Goal**: refit/recalibrate the existing Trump and Elon modules using this data instead of the 30-day LuciferForge sample we initially used.

Specific tasks:
1. **Re-run Elon `<40` flip analysis** on full 3.5-year history — confirm or refute the +194% median peak finding from the 19-auction sample.
2. **Recalibrate sell rule thresholds** for Elon module — the Target 2× rule was tuned on 30 days; verify on 3.5 years.
3. **Recompute Trump bracket-level priors** using the full historical price data — feed into ensemble model weights.
4. **Build a "pacing-aware sell rule"** using the full per-trade timestamps (we couldn't do this with 15-min snapshots).
5. **Backfill Trump+Elon `price_snapshots` table** with longer history (currently only Feb-May 2026 for Trump; Mar-May 2026 for Elon) — 3+ years of additional bracket prices available from parquet.

Reference files:
- `_DataMetricPulls/duckdb_remote.py` — DuckDB connection helper with HF token
- `_DataMetricPulls/full_history_analysis.py` — strict-recurring classification + ranking
- `_DataMetricPulls/full_history/STRICT_recurring_full_ranked.csv` — output (when run completes)
- HF token: stored in `~/.credentials/shared.env` as `HF_TOKEN`

---

## Key Config
- Trump module: `e858d9ed-da0d-4e9a-8bef-2c2830686a5a` (Truth Social Posts)
- Elon module: `cac300cb-5af2-4c25-a7df-3069478aefdb` (Elon Tweets)
- Spike module: `4faba37c-906b-405f-ad49-737b12e75b16` (Spike Trading)
- Slippage tolerance: 0.05 | Auto-pause: 5 consecutive losses | Order TTL: 5min (24h for Spike BUYs)
- Dashboard widths: full / 1/2 / 1/3 (CSS grid)
- Daily Slack digests fire at 9 AM ET + 5 PM ET (UTC 13:00 + 21:00)

## URLs
- Dashboard: polybot-dashboard.up.railway.app
- API: polymarket-trading-bot-32126-production.up.railway.app
- Prod Supabase: xdonwowgqvmtrduikaon.supabase.co

## Operational notes
- Trump backfill: ✅ complete (32,880 posts, walked to 2022). `backfill_progress.is_complete=true`.
- IFTTT webhook for Elon X: needs `WEBHOOK_SECRET` env var; payload spec in `api/routers/webhooks.py`.
- Backfill scripts: `scripts/backfill_xtracker_history.py` (idempotent, ~5min) and `scripts/backfill_truth_social.py` (idempotent, 8-24h, supports `--forward` for incremental).
- Pre-2026-05-05 session history preserved in git history (`git log --before=2026-05-05`).
