-- Spike Rider module
-- Buys cheap brackets early on recurring count auctions and exits via the
-- multi-stage / target-multiplier / trailing-stop sell rule chosen in the
-- offline simulator (see scripts/simulate_sell_rules.py).
--
-- Scaffolded for Elon's tweet-count auctions but designed to apply to any
-- recurring "# of X per period" series via the auction_series table.

create table if not exists auction_series (
  id uuid primary key default gen_random_uuid(),
  module_id uuid references modules(id) on delete cascade,
  -- Which xTracker handle / Polymarket tag identifies the series
  handle text not null,
  -- Filter substring matched against xTracker tracking title (lowercase)
  -- e.g. "tweets" for Elon, "truth social" for Trump
  title_filter text not null,
  -- Which xTracker platform: "x" for Twitter/X, "truthsocial" for Truth Social
  platform text not null default 'x',
  -- Strategy preset to apply when scaffolding new modules from this series
  strategy_preset text not null default 'spike_rider' check (
    strategy_preset in ('spike_rider', 'wait_for_dip', 'arbitrage_only')
  ),
  enabled boolean default true,
  notes text,
  created_at timestamptz default now()
);

create unique index if not exists idx_auction_series_handle_title
  on auction_series(handle, title_filter);

alter table auction_series enable row level security;
create policy "auth_all_auction_series" on auction_series
  for all to authenticated using (true) with check (true);

-- Position-level tracking for multi-stage exits.
-- Multi-stage rules can fire multiple partial sells; track which tranches
-- have already been triggered so a restart doesn't double-sell.
create table if not exists position_exit_state (
  position_id uuid primary key references positions(id) on delete cascade,
  stage_1_done boolean default false,
  stage_2_done boolean default false,
  stage_3_done boolean default false,
  peak_price numeric,
  -- Snapshot of original size so we can sell exact fractions even after partials
  original_size numeric,
  updated_at timestamptz default now()
);

alter table position_exit_state enable row level security;
create policy "auth_all_position_exit_state" on position_exit_state
  for all to authenticated using (true) with check (true);

-- Seed Spike Rider module for Elon (paper mode by default).
-- Uses the same xTracker market_slug as Elon Tweets — they trade the same
-- auctions but with different strategies and separate position books.
insert into modules (name, market_slug, strategy, budget, max_position_pct, status)
values (
  'Spike Rider — Elon',
  null,                  -- resolved at runtime from xTracker active tracking
  'spike_rider',
  100,                   -- $100 paper bankroll to start
  0.10,                  -- 10% max single-bracket exposure
  'paper'
)
on conflict do nothing;

-- Seed the auction_series row pointing this module at Elon's xTracker handle
insert into auction_series (module_id, handle, title_filter, platform, strategy_preset)
select id, 'elonmusk', 'tweets', 'x', 'spike_rider'
from modules where name = 'Spike Rider — Elon'
on conflict do nothing;
