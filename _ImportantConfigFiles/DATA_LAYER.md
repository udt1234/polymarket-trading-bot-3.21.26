# Data Layer: Retention Archive and Canonical Tables

Moved from CLAUDE.md on 2026-10-27. CLAUDE.md keeps a pointer to each section and the "Rules for new backtests".

## Retention + Parquet Archive (2026-05-22)
Supabase free tier choked on Disk IO 2026-05-22 (GoTrue auth hung, dashboard login broke). Permanent fix: retention policy + parquet archive.

**Live retention windows (rows older than this are deleted from Supabase):**
- `price_snapshots`: 180 days (used live by `price_timing.py` + `exit_manager.py`)
- `post_count_snapshots`: 90 days (used live by `whale_snapshot.py` for projections)
- `order_book_snapshots`: 30 days (dashboard only, no trading-logic reads)
- `logs` system: 30 days (`engine.py:952` reads "New Auction" markers)
- `logs` other: 14 days (last 20-50 reads only)
- `pending_signals`: 7 days

**Archive location**: `_DataMetricPulls/historical/supabase_archive/<table>/<YYYY-MM>.parquet`

**Schedulers running in bot process**:
- Daily cleanup: 03:30 UTC: DELETEs old rows
- Weekly archive: Sunday 03:00 UTC: dumps last 7d to parquet

**Reading older-than-live data**: use `api.modules.shared.parquet_archive.read_table_range(table, since, until, ts_col, filters)`. Returns pandas DataFrame or None.

**Already-wired modules**: `price_timing.py` (price_snapshots merge) + `whale_snapshot.py` (post_count_snapshots merge). When adding new analysis code that reads >live window, follow the same pattern.

**One-time backup script**: `scripts/archive_supabase_to_parquet.py`: full dump of all 4 tables to parquet. Run before any retention changes.

## Canonical Data Layer (2026-05-28): Single Source of Truth for ALL Backtests

**`_DataMetricPulls/canonical/` is the ONLY data source backtests may read from.**
Built 2026-05-28 by consolidating 113 messy parquet/csv/json sources into 3 clean partitioned tables. The old `elon_max_return/`, `elon_regime/`, `fed_decision/`, `hf_polymarket/`, `historical/`, etc. were deleted (2.8 GB freed).

### Three canonical tables (all parquet, partitioned by handle/YYYY-MM):

| Table | Path | One row per | Coverage |
|---|---|---|---|
| **posts** | `canonical/posts/{handle}/{YYYY-MM}.parquet` | each tweet/truth | Trump: Feb 2022 → Apr 2026 (32,837). Elon: Oct 2025 → May 2026 (9,105) |
| **auctions** | `canonical/auctions/{handle}/{YYYY-MM}.parquet` | each resolved auction | 304 total (220 Elon + 84 Trump), back to mid-2024 |
| **prices** | `canonical/prices/{handle}/{YYYY-MM}.parquet` | each (auction, bucket, hour) | hourly OHLC + trade-derived orderbook proxies |

### Key columns
- **All timestamps are dual-stored: `ts_utc` (canonical) + `ts_et` (America/New_York, DST-correct via `zoneinfo`)**
- `posts.counts_for_auction` (bool): applies xTracker rules (Trump: no pure replies; Elon: no pure replies + no community reposts)
- `auctions.duration_type`: `2-day`, `7-day`, `monthly`, `point`, `unknown`: parsed from filename, not hours_in
- `auctions.winning_bucket` + `resolution_status` (`resolved_yes` | `inferred_close_ge_95` | `unresolved` | `ambiguous_N`) + `confidence` (high/medium/low)
- `prices.derived_spread`, `derived_fill_minutes`, `derived_depth_buy_low`, `derived_depth_sell_high`: trade-derived orderbook proxies (no L2 history exists pre-Mar 2026)

### Raw trade archive
- `canonical/_raw_imports/api_trades_v2/`: one parquet per auction (300 files on 2026-10-27), the source for auctions + prices. Written only by builders 10 (fresh rebuild), 11, 12 (recover) and 14 (repair); never hand-edit. Builder 09 (re-pull) writes `_raw_imports/api_trades/` instead, which 03 and 04 do NOT read (`_canon.RAW_DIR` is `api_trades_v2`): a 09 pull is ignored by every rebuild until it is copied into `api_trades_v2/`. The old `whale_analysis/` folder no longer exists.
- `canonical/_audit/source_inventory.csv`: historical inventory of the 113 pre-canonical sources for reference.

### Reading canonical data
```python
import pandas as pd
from pathlib import Path
CANON = Path("_DataMetricPulls/canonical")
# Load all Trump auctions in 2025:
trump_2025 = pd.concat([pd.read_parquet(p) for p in (CANON/"auctions/realDonaldTrump").glob("2025-*.parquet")])
# All Elon hourly prices for May 2026:
elon_may = pd.read_parquet(CANON/"prices/elonmusk/2026-05.parquet")
```

### Builder scripts (idempotent, re-run any time)
- `scripts/canonical/01_audit_sources.py`: re-scan for source inventory (read-only)
- `scripts/canonical/02_build_posts.py`: rebuild posts from raw parquets
- `scripts/canonical/03_build_auctions.py`: rebuild auctions from api_trades_v2
- `scripts/canonical/04_build_prices.py`: rebuild hourly OHLC + proxies (prints winner-coverage at the end)
- `scripts/canonical/05_nuclear_delete.py`: clean up non-canonical sources (dry-run by default)
- `scripts/canonical/14_repair_bracket_coverage.py`: pull brackets Gamma lists but raw is missing/truncated
- `scripts/canonical/15_verify_winner_coverage.py`: coverage gate; exit 1 below 95%; `--demote` to exclude the rest

**Order matters: anything that touches `_raw_imports/` must be followed by `04_build_prices.py`.** `prices` is derived; leaving it stale is what produced the 2026-07 winner-coverage bug.

### Canonical QA Sheet
- [PolyMarket Canonical Data: Source Inventory](https://docs.google.com/spreadsheets/d/1bXBnXz4a1Nn44ZLORNo2cNqZx6pnqER3rcoTUZMC1Q8/edit): sample tabs for posts/auctions/prices both handles, plus the legacy source inventory
