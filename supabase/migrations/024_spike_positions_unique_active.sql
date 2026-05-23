-- 024: Prevent duplicate active spike_positions rows for the same
-- (module_id, market_id, bracket).
--
-- QA finding #4 (2026-05-23): _sync_spike_position_after_buy does a
-- SELECT-then-UPDATE-or-INSERT. Two concurrent BUY fills (insta-buy +
-- regular cycle racing) can both reach the SELECT, both find no row,
-- both INSERT. Without this index, PnL accounting goes off and
-- _close_spike_position would stamp both rows LIQUIDATED.
--
-- Belt: this unique partial index; suspenders: app-side row-id close path.

-- 1. Clean up any pre-existing duplicates: keep the most-recently-updated
--    active row per (module_id, market_id, bracket); liquidate the rest.
with ranked as (
  select id, row_number() over (
    partition by module_id, market_id, bracket
    order by coalesce(last_decision_at, opened_at, now()) desc
  ) as rn
  from spike_positions
  where state in ('WAITING', 'MONITORING')
)
update spike_positions
set state = 'LIQUIDATED',
    closed_at = now(),
    last_decision = 'AUTO_LIQUIDATE_DUPLICATE_ACTIVE',
    last_decision_at = now()
where id in (select id from ranked where rn > 1);

-- 2. Enforce uniqueness going forward.
create unique index if not exists idx_spike_one_active_per_bracket
  on spike_positions(module_id, market_id, bracket)
  where state in ('WAITING', 'MONITORING');
