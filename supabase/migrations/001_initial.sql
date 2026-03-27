-- PolyMarket Bot — Initial Schema
-- Run in Supabase SQL Editor or via supabase db push

-- Modules (auction market modules)
create table if not exists modules (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  market_slug text,
  strategy text not null default 'ensemble',
  budget numeric not null default 100,
  max_position_pct numeric not null default 0.15,
  data_sources jsonb default '{}',
  resolution_date timestamptz,
  status text not null default 'active' check (status in ('active', 'paused', 'paper', 'scaffold')),
  auto_pause boolean default false,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- Orders (state machine: created → submitted → live → filled → settled)
create table if not exists orders (
  id uuid primary key default gen_random_uuid(),
  module_id uuid references modules(id),
  market_id text,
  bracket text,
  side text not null check (side in ('BUY', 'SELL')),
  size numeric not null,
  price numeric not null,
  status text not null default 'created'
    check (status in ('created', 'submitted', 'live', 'filled', 'partially_filled', 'cancelled', 'rejected', 'settled')),
  executor text default 'paper',
  created_at timestamptz default now(),
  filled_at timestamptz,
  settled_at timestamptz
);

-- Trades (filled orders)
create table if not exists trades (
  id uuid primary key default gen_random_uuid(),
  order_id uuid references orders(id),
  module_id uuid references modules(id),
  market_id text,
  bracket text,
  side text not null,
  size numeric not null,
  price numeric not null,
  executor text default 'paper',
  executed_at timestamptz default now()
);

-- Positions
create table if not exists positions (
  id uuid primary key default gen_random_uuid(),
  module_id uuid references modules(id),
  market_id text,
  bracket text,
  side text not null,
  size numeric not null default 0,
  avg_price numeric not null default 0,
  exit_price numeric,
  realized_pnl numeric default 0,
  unrealized_pnl numeric default 0,
  status text not null default 'open' check (status in ('open', 'closed')),
  opened_at timestamptz default now(),
  closed_at timestamptz
);

-- Daily P&L snapshots
create table if not exists daily_pnl (
  id uuid primary key default gen_random_uuid(),
  date date not null unique,
  portfolio_value numeric not null default 0,
  daily_return numeric default 0,
  realized_pnl numeric default 0,
  unrealized_pnl numeric default 0,
  total_pnl numeric default 0,
  created_at timestamptz default now()
);

-- Signals (strategy outputs, approved or rejected)
create table if not exists signals (
  id uuid primary key default gen_random_uuid(),
  module_id uuid references modules(id),
  market_id text,
  bracket text,
  side text,
  edge numeric,
  model_prob numeric,
  market_price numeric,
  kelly_pct numeric,
  approved boolean default false,
  rejection_reason text,
  created_at timestamptz default now()
);

-- Logs (decision, execution, system, risk)
create table if not exists logs (
  id uuid primary key default gen_random_uuid(),
  log_type text not null check (log_type in ('decision', 'execution', 'system', 'risk')),
  severity text not null default 'info' check (severity in ('debug', 'info', 'warning', 'error', 'critical')),
  module_id uuid references modules(id),
  message text not null,
  metadata jsonb default '{}',
  created_at timestamptz default now()
);

-- Settings (key-value for risk params, notifications, etc.)
create table if not exists settings (
  key text primary key,
  value jsonb not null default '{}',
  updated_at timestamptz default now()
);

-- Statistical tests (pluggable test configs)
create table if not exists statistical_tests (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  test_type text not null,
  config jsonb not null default '{}',
  enabled boolean default true,
  created_at timestamptz default now()
);

-- Module A/B tests
create table if not exists module_ab_tests (
  id uuid primary key default gen_random_uuid(),
  module_id uuid references modules(id),
  variant_a jsonb not null,
  variant_b jsonb not null,
  budget_split numeric default 0.5,
  status text default 'running' check (status in ('running', 'completed', 'cancelled')),
  results jsonb default '{}',
  created_at timestamptz default now()
);

-- Calibration log (model accuracy tracking)
create table if not exists calibration_log (
  id uuid primary key default gen_random_uuid(),
  module_id uuid references modules(id),
  market_id text,
  bracket text,
  predicted_prob numeric,
  actual_outcome boolean,
  brier_score numeric,
  log_loss numeric,
  resolved_at timestamptz default now()
);

-- Alerts
create table if not exists alerts (
  id uuid primary key default gen_random_uuid(),
  alert_type text not null,
  condition jsonb not null,
  channel text default 'dashboard',
  enabled boolean default true,
  last_triggered timestamptz,
  created_at timestamptz default now()
);

-- Audit log (immutable decision trail)
create table if not exists audit_log (
  id uuid primary key default gen_random_uuid(),
  action text not null,
  actor text default 'engine',
  resource_type text,
  resource_id text,
  details jsonb default '{}',
  created_at timestamptz default now()
);

-- Indexes
create index if not exists idx_orders_module on orders(module_id);
create index if not exists idx_orders_status on orders(status);
create index if not exists idx_trades_module on trades(module_id);
create index if not exists idx_trades_executed on trades(executed_at desc);
create index if not exists idx_positions_status on positions(status);
create index if not exists idx_positions_module on positions(module_id);
create index if not exists idx_logs_type on logs(log_type);
create index if not exists idx_logs_created on logs(created_at desc);
create index if not exists idx_signals_module on signals(module_id);
create index if not exists idx_daily_pnl_date on daily_pnl(date desc);
create index if not exists idx_audit_log_created on audit_log(created_at desc);

-- RLS: enable on all tables, allow authenticated users
alter table modules enable row level security;
alter table orders enable row level security;
alter table trades enable row level security;
alter table positions enable row level security;
alter table daily_pnl enable row level security;
alter table signals enable row level security;
alter table logs enable row level security;
alter table settings enable row level security;
alter table statistical_tests enable row level security;
alter table module_ab_tests enable row level security;
alter table calibration_log enable row level security;
alter table alerts enable row level security;
alter table audit_log enable row level security;

-- Single-user: allow all authenticated access
do $$
declare
  t text;
begin
  for t in select unnest(array[
    'modules','orders','trades','positions','daily_pnl','signals',
    'logs','settings','statistical_tests','module_ab_tests',
    'calibration_log','alerts','audit_log'
  ]) loop
    execute format(
      'create policy "auth_all_%s" on %I for all to authenticated using (true) with check (true)',
      t, t
    );
  end loop;
end $$;

-- Seed default settings
insert into settings (key, value) values
  ('risk', '{
    "bankroll": 1000,
    "max_portfolio_exposure": 0.5,
    "max_single_market_exposure": 0.15,
    "max_correlated_exposure": 0.30,
    "daily_loss_limit": 0.05,
    "weekly_loss_limit": 0.10,
    "max_drawdown": 0.15,
    "min_edge_threshold": 0.02,
    "slippage_tolerance": 0.02,
    "kelly_fraction": 0.25,
    "circuit_breaker_enabled": true,
    "circuit_breaker_max_consecutive_losses": 5,
    "circuit_breaker_cooldown_minutes": 30,
    "shadow_mode": false,
    "paper_mode": true
  }'::jsonb),
  ('notifications', '{"discord": null, "telegram": null, "email": null}'::jsonb)
on conflict (key) do nothing;

-- Seed Truth Social module
insert into modules (name, market_slug, strategy, budget, status) values
  ('Truth Social Posts', 'donald-trump-of-truth-social-posts', 'ensemble', 100, 'scaffold')
on conflict do nothing;
