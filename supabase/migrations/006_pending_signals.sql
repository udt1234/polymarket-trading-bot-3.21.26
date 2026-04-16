-- 006: Pending signals for wait-for-dip logic

create table if not exists pending_signals (
  id uuid primary key default gen_random_uuid(),
  module_id uuid references modules(id),
  market_id text not null,
  bracket text not null,
  side text default 'BUY',
  original_price numeric,
  target_price numeric,
  wait_until timestamptz,
  abandon_if_price_above numeric,
  model_prob numeric,
  original_kelly_pct numeric,
  expected_drop_pct numeric,
  analog_count integer,
  signal_metadata jsonb,
  status text default 'waiting',
  created_at timestamptz default now(),
  resolved_at timestamptz
);

create index if not exists idx_pending_module_market on pending_signals(module_id, market_id);
create index if not exists idx_pending_wait on pending_signals(wait_until) where status = 'waiting';
create index if not exists idx_pending_status on pending_signals(status);

alter table pending_signals enable row level security;
create policy "auth_all_pending_signals" on pending_signals
  for all to authenticated using (true) with check (true);
