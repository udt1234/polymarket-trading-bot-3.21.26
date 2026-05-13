-- 018: Copy Trading module — mirror whale wallets in real time.
-- Spec: _ImportantConfigFiles/COPY_TRADING_MODULE_SPEC.md

-- One row per tracked wallet × module. Two modules could track the same
-- wallet with different caps (e.g. paper vs live), so the unique key is
-- (module_id, wallet_address).
create table if not exists copy_trade_wallets (
  id uuid primary key default gen_random_uuid(),
  module_id uuid not null references modules(id) on delete cascade,
  wallet_address text not null,
  label text,
  weight_pct numeric not null default 1.0,
  enabled boolean not null default true,
  auto_disabled_at timestamptz,
  auto_disabled_reason text,
  created_at timestamptz default now(),
  unique (module_id, wallet_address)
);

create index if not exists idx_copy_wallets_module on copy_trade_wallets(module_id);
create index if not exists idx_copy_wallets_enabled on copy_trade_wallets(enabled) where enabled = true;

-- Per-wallet polling state. Tracks the last-seen trade so we only emit
-- signals for new activity, plus rolling performance for the whale gate.
create table if not exists copy_trade_state (
  wallet_id uuid primary key references copy_trade_wallets(id) on delete cascade,
  last_seen_trade_ts timestamptz,
  last_polled_at timestamptz,
  consecutive_poll_failures int not null default 0,
  last_known_balance numeric,
  recent_copy_roi_pct numeric,
  recent_copy_count int not null default 0
);

-- Per-copy audit row. Every decision — mirrored OR skipped — gets one row
-- here. The (wallet_id, whale_trade_id) UNIQUE constraint enforces dedupe:
-- replaying the same trade through the cron will collide on the index and
-- the second insert is dropped.
create table if not exists copy_trade_log (
  id uuid primary key default gen_random_uuid(),
  wallet_id uuid not null references copy_trade_wallets(id) on delete cascade,
  module_id uuid not null references modules(id) on delete cascade,
  whale_trade_id text not null,
  whale_trade_ts timestamptz not null,
  whale_side text not null check (whale_side in ('BUY', 'SELL')),
  whale_price numeric,
  whale_size numeric,
  market_id text not null,
  bracket text,
  our_signal_id uuid,
  our_action text not null check (our_action in (
    'mirrored', 'skipped_stale', 'skipped_drift', 'skipped_cap',
    'skipped_dedupe', 'skipped_circuit', 'skipped_perf_gate',
    'skipped_no_position', 'skipped_zero_size', 'skipped_error'
  )),
  skip_reason text,
  realized_pnl numeric,
  created_at timestamptz default now(),
  unique (wallet_id, whale_trade_id)
);

create index if not exists idx_copy_log_wallet_ts on copy_trade_log (wallet_id, whale_trade_ts desc);
create index if not exists idx_copy_log_module on copy_trade_log (module_id, created_at desc);
create index if not exists idx_copy_log_market on copy_trade_log (market_id);

alter table copy_trade_wallets enable row level security;
alter table copy_trade_state enable row level security;
alter table copy_trade_log enable row level security;

do $$ begin
  if not exists (select 1 from pg_policies where tablename = 'copy_trade_wallets' and policyname = 'auth_all_copy_trade_wallets') then
    create policy "auth_all_copy_trade_wallets" on copy_trade_wallets
      for all to authenticated using (true) with check (true);
  end if;
  if not exists (select 1 from pg_policies where tablename = 'copy_trade_state' and policyname = 'auth_all_copy_trade_state') then
    create policy "auth_all_copy_trade_state" on copy_trade_state
      for all to authenticated using (true) with check (true);
  end if;
  if not exists (select 1 from pg_policies where tablename = 'copy_trade_log' and policyname = 'auth_all_copy_trade_log') then
    create policy "auth_all_copy_trade_log" on copy_trade_log
      for all to authenticated using (true) with check (true);
  end if;
end $$;
