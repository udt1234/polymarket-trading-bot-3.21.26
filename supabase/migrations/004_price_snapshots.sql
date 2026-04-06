-- Price snapshots: hourly bracket price captures from Gamma API
create table if not exists price_snapshots (
  id uuid primary key default gen_random_uuid(),
  module_id uuid references modules(id),
  bracket text not null,
  price numeric not null,
  volume numeric,
  snapshot_hour timestamptz not null,
  dow smallint not null,
  hour_of_day smallint not null,
  elapsed_days numeric,
  tracking_id text,
  created_at timestamptz default now()
);

create index if not exists idx_price_snap_module on price_snapshots(module_id);
create index if not exists idx_price_snap_hour on price_snapshots(snapshot_hour desc);
create index if not exists idx_price_snap_bracket on price_snapshots(bracket);
create index if not exists idx_price_snap_dow_hour on price_snapshots(dow, hour_of_day);

-- Unique constraint: one snapshot per bracket per hour
create unique index if not exists idx_price_snap_unique
  on price_snapshots(module_id, bracket, snapshot_hour);

alter table price_snapshots enable row level security;
create policy "auth_all_price_snapshots" on price_snapshots
  for all to authenticated using (true) with check (true);
