-- 022: Keep one active wait-for-dip row per module/market/bracket/side.

with ranked as (
  select
    id,
    row_number() over (
      partition by module_id, market_id, bracket, side
      order by created_at desc
    ) as rn
  from pending_signals
  where status = 'waiting'
)
update pending_signals
set status = 'cancelled',
    resolved_at = now()
where id in (
  select id
  from ranked
  where rn > 1
);

create unique index if not exists idx_pending_one_waiting_signal
  on pending_signals(module_id, market_id, bracket, side)
  where status = 'waiting';
