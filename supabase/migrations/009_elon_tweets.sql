-- Elon X/Twitter posts archive (mirrors truth_social_posts shape).
-- Populated via IFTTT "New tweet by specific user" webhook (real-time).
create table if not exists elon_tweets (
  id text primary key,                  -- tweet ID (string from URL)
  handle text not null default 'elonmusk',
  created_at timestamptz not null,
  url text,
  text text,
  is_reply boolean default false,
  is_retweet boolean default false,
  is_quote boolean default false,
  raw jsonb not null,                   -- full IFTTT payload
  source text default 'ifttt',          -- 'ifttt' | 'manual' | 'api'
  fetched_at timestamptz not null default now()
);

create index if not exists idx_elon_tweets_created on elon_tweets(created_at desc);
create index if not exists idx_elon_tweets_handle on elon_tweets(handle);

alter table elon_tweets enable row level security;
create policy "auth_all_elon_tweets" on elon_tweets
  for all to authenticated using (true) with check (true);
-- Service role bypasses RLS by default (used by webhook endpoint).
