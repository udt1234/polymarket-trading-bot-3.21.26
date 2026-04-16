-- 005: Infrastructure for new analytics charts

-- Post detection timestamp for signal-to-fill latency histogram
alter table signals add column if not exists post_detected_at timestamptz;

-- Order book snapshots for Order Book Depth chart (every 5min)
create table if not exists order_book_snapshots (
  id uuid primary key default gen_random_uuid(),
  module_id uuid references modules(id),
  market_id text not null,
  bracket text not null,
  best_bid numeric,
  best_ask numeric,
  spread numeric,
  bid_depth_5 numeric,
  ask_depth_5 numeric,
  midpoint numeric,
  snapshot_at timestamptz default now()
);

create index if not exists idx_order_book_module on order_book_snapshots(module_id);
create index if not exists idx_order_book_snapshot_at on order_book_snapshots(snapshot_at desc);
create index if not exists idx_order_book_bracket on order_book_snapshots(bracket);

alter table order_book_snapshots enable row level security;
create policy "auth_all_order_book_snapshots" on order_book_snapshots
  for all to authenticated using (true) with check (true);
