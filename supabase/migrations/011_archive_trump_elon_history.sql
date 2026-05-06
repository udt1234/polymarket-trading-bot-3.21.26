-- 011: Soft-archive Trump + Elon trading history (2026-05-05)
-- Per user: reset trading P&L for Trump (Truth Social Posts) and Elon (Elon Tweets)
-- modules so they start fresh. Preserve all non-trading data
-- (truth_social_posts, post_count_snapshots, price_snapshots, logs, etc.).
-- Soft = copy to dated archive tables first, then delete.

-- Module IDs:
--   Truth Social Posts: e858d9ed-da0d-4e9a-8bef-2c2830686a5a
--   Elon Tweets:        cac300cb-5af2-4c25-a7df-3069478aefdb

-- 1) Archive: copy rows to *_archive_20260505 tables
create table if not exists positions_archive_20260505 as
  select * from positions
  where module_id in (
    'e858d9ed-da0d-4e9a-8bef-2c2830686a5a',
    'cac300cb-5af2-4c25-a7df-3069478aefdb'
  );

create table if not exists orders_archive_20260505 as
  select * from orders
  where module_id in (
    'e858d9ed-da0d-4e9a-8bef-2c2830686a5a',
    'cac300cb-5af2-4c25-a7df-3069478aefdb'
  );

create table if not exists trades_archive_20260505 as
  select * from trades
  where module_id in (
    'e858d9ed-da0d-4e9a-8bef-2c2830686a5a',
    'cac300cb-5af2-4c25-a7df-3069478aefdb'
  );

create table if not exists signals_archive_20260505 as
  select * from signals
  where module_id in (
    'e858d9ed-da0d-4e9a-8bef-2c2830686a5a',
    'cac300cb-5af2-4c25-a7df-3069478aefdb'
  );

create table if not exists pending_signals_archive_20260505 as
  select * from pending_signals
  where module_id in (
    'e858d9ed-da0d-4e9a-8bef-2c2830686a5a',
    'cac300cb-5af2-4c25-a7df-3069478aefdb'
  );

-- 2) Delete from live tables
delete from pending_signals
  where module_id in (
    'e858d9ed-da0d-4e9a-8bef-2c2830686a5a',
    'cac300cb-5af2-4c25-a7df-3069478aefdb'
  );

delete from trades
  where module_id in (
    'e858d9ed-da0d-4e9a-8bef-2c2830686a5a',
    'cac300cb-5af2-4c25-a7df-3069478aefdb'
  );

delete from orders
  where module_id in (
    'e858d9ed-da0d-4e9a-8bef-2c2830686a5a',
    'cac300cb-5af2-4c25-a7df-3069478aefdb'
  );

delete from positions
  where module_id in (
    'e858d9ed-da0d-4e9a-8bef-2c2830686a5a',
    'cac300cb-5af2-4c25-a7df-3069478aefdb'
  );

delete from signals
  where module_id in (
    'e858d9ed-da0d-4e9a-8bef-2c2830686a5a',
    'cac300cb-5af2-4c25-a7df-3069478aefdb'
  );

-- 3) Reset per-module circuit breaker / risk state in settings (if any)
delete from settings
  where key like 'circuit_breaker:%e858d9ed%'
     or key like 'circuit_breaker:%cac300cb%'
     or key like 'risk_state:%e858d9ed%'
     or key like 'risk_state:%cac300cb%';
