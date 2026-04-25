-- Post count snapshots: 5-min captures from xTracker + Truth Social Direct
-- Enables post-mortem auditing, source-divergence detection, and replay backtesting.
create table if not exists post_count_snapshots (
  id uuid primary key default gen_random_uuid(),
  module_id uuid references modules(id) on delete cascade,
  source text not null check (source in ('xtracker', 'truthsocial_direct')),
  tracking_id text,
  window_start timestamptz,
  window_end timestamptz,
  count integer,
  latest_post_at timestamptz,
  error text,
  raw_response jsonb,
  captured_at timestamptz not null default now()
);

create index if not exists idx_pcs_module_captured on post_count_snapshots(module_id, captured_at desc);
create index if not exists idx_pcs_source on post_count_snapshots(source);
create index if not exists idx_pcs_tracking on post_count_snapshots(tracking_id);

alter table post_count_snapshots enable row level security;
create policy "auth_all_post_count_snapshots" on post_count_snapshots
  for all to authenticated using (true) with check (true);
