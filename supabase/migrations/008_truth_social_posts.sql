-- Truth Social raw posts archive: every post Trump (or any tracked handle) has made
-- Used for verification, backtesting, and recomputing counts for arbitrary windows.
create table if not exists truth_social_posts (
  id text primary key,
  account_id text not null,
  handle text not null,
  created_at timestamptz not null,
  is_reply boolean default false,
  is_reblog boolean default false,
  in_reply_to_id text,
  reblog_of_id text,
  raw jsonb not null,
  fetched_at timestamptz not null default now()
);

create index if not exists idx_tsp_handle_created on truth_social_posts(handle, created_at desc);
create index if not exists idx_tsp_account_created on truth_social_posts(account_id, created_at desc);
create index if not exists idx_tsp_created on truth_social_posts(created_at desc);

alter table truth_social_posts enable row level security;
create policy "auth_all_truth_social_posts" on truth_social_posts
  for all to authenticated using (true) with check (true);

-- Backfill progress checkpoint table (single row per handle)
create table if not exists backfill_progress (
  handle text primary key,
  source text not null,
  oldest_fetched_id text,
  oldest_fetched_at timestamptz,
  newest_fetched_id text,
  newest_fetched_at timestamptz,
  total_pages_fetched integer default 0,
  total_posts_stored integer default 0,
  last_run_at timestamptz default now(),
  is_complete boolean default false,
  last_error text
);

alter table backfill_progress enable row level security;
create policy "auth_all_backfill_progress" on backfill_progress
  for all to authenticated using (true) with check (true);
