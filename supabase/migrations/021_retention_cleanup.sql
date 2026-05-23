-- Retention cleanup for high-traffic tables.
-- Triggered 2026-05-22 by free-tier Disk IO budget exhaustion that broke
-- GoTrue auth (Sir couldn't log into the dashboard). Smaller tables = smaller
-- indexes = less random IO per write = sustainable on Supabase free tier.
--
-- Retention policy (live in Supabase = recent; parquet archive = historical):
--   price_snapshots:       180 days  (read live by price_timing + exit_manager)
--   post_count_snapshots:   90 days  (read live by whale_snapshot for projections)
--   order_book_snapshots:   30 days  (dashboard only, not read by trading logic)
--   logs (system):          30 days  (engine reads "New Auction" markers)
--   logs (others):          14 days  (decision/risk/execution — only last 20-50 read)
--   pending_signals:         7 days  (live queue, resolved rows quickly stale)
--
-- Older data lives in parquet at
--   _DataMetricPulls/historical/supabase_archive/<table>/<YYYY-MM>.parquet
-- Run scripts/archive_supabase_to_parquet.py BEFORE this migration to back up.

BEGIN;

-- 1. price_snapshots — 180 days
DELETE FROM price_snapshots
WHERE snapshot_hour < (NOW() - INTERVAL '180 days');

-- 2. post_count_snapshots — 90 days
DELETE FROM post_count_snapshots
WHERE captured_at < (NOW() - INTERVAL '90 days');

-- 3. order_book_snapshots — 30 days
DELETE FROM order_book_snapshots
WHERE snapshot_at < (NOW() - INTERVAL '30 days');

-- 4a. logs (system) — 30 days
DELETE FROM logs
WHERE log_type = 'system'
  AND created_at < (NOW() - INTERVAL '30 days');

-- 4b. logs (everything else) — 14 days
DELETE FROM logs
WHERE log_type != 'system'
  AND created_at < (NOW() - INTERVAL '14 days');

-- 5. pending_signals — 7 days (only resolved/expired rows; live ones stay).
-- status != 'waiting' protects unresolved live signals from being deleted
-- mid-defer. The runtime DELETE in api/services/retention.py mirrors this.
-- QA finding 4 (2026-05-22): without this filter, a future config bump
-- raising the max defer window would silently kill live signals.
DELETE FROM pending_signals
WHERE created_at < (NOW() - INTERVAL '7 days')
  AND status != 'waiting';

COMMIT;

-- Reclaim disk space. Required after a large DELETE — without VACUUM the
-- table file stays the same size, defeating the IO-relief purpose.
-- VACUUM FULL would lock the table; plain VACUUM is online-safe.
VACUUM ANALYZE price_snapshots;
VACUUM ANALYZE post_count_snapshots;
VACUUM ANALYZE order_book_snapshots;
VACUUM ANALYZE logs;
VACUUM ANALYZE pending_signals;
