-- 010: Spike Trading module — per-position state machine + cycle snapshots.
-- Strategy reference: _ImportantConfigFiles/spike_trading_module_spec.md

create table if not exists spike_positions (
  id uuid primary key default gen_random_uuid(),
  module_id uuid references modules(id) on delete cascade,
  market_id text not null,
  bracket text not null,
  state text not null default 'WAITING'
    check (state in ('WAITING', 'MONITORING', 'LIQUIDATED', 'RESOLVED')),
  entry_price numeric,
  entry_size_shares numeric default 0,
  entry_size_usd numeric default 0,
  current_tweets int default 0,
  hours_to_close numeric default 0,
  last_decision text,
  last_decision_at timestamptz,
  ladder_orders jsonb default '[]'::jsonb,
  realized_pnl numeric default 0,
  unrealized_pnl numeric default 0,
  end_price numeric,
  opened_at timestamptz default now(),
  closed_at timestamptz
);

create index if not exists idx_spike_pos_module on spike_positions(module_id);
create index if not exists idx_spike_pos_state on spike_positions(state);
create index if not exists idx_spike_pos_market on spike_positions(market_id);

-- One open position per (module, market, bracket) — enforced by partial unique index
create unique index if not exists idx_spike_pos_one_open
  on spike_positions(module_id, market_id, bracket)
  where state in ('WAITING', 'MONITORING');

create table if not exists spike_state_snapshots (
  id uuid primary key default gen_random_uuid(),
  position_id uuid references spike_positions(id) on delete cascade,
  cum_tweets int,
  hours_to_close numeric,
  current_price numeric,
  decision text,
  captured_at timestamptz default now()
);

create index if not exists idx_spike_snap_pos on spike_state_snapshots(position_id, captured_at desc);

alter table spike_positions enable row level security;
alter table spike_state_snapshots enable row level security;

do $$ begin
  if not exists (select 1 from pg_policies where tablename = 'spike_positions' and policyname = 'auth_all_spike_positions') then
    create policy "auth_all_spike_positions" on spike_positions
      for all to authenticated using (true) with check (true);
  end if;
  if not exists (select 1 from pg_policies where tablename = 'spike_state_snapshots' and policyname = 'auth_all_spike_state_snapshots') then
    create policy "auth_all_spike_state_snapshots" on spike_state_snapshots
      for all to authenticated using (true) with check (true);
  end if;
end $$;
