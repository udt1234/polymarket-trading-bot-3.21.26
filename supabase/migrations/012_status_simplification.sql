-- 012: Module status simplification (2026-05-05)
-- Collapse paused/killed/scaffold -> 'inactive' + structured reason.
-- Final allowed values: 'active', 'paper', 'inactive'.

alter table modules add column if not exists inactive_reason text;
alter table modules add column if not exists inactive_since timestamptz;
alter table modules add column if not exists inactive_detail text;

-- Backfill: collapse old statuses into 'inactive' with appropriate reason
update modules set
  inactive_reason = 'kill_switch',
  inactive_since = coalesce(inactive_since, updated_at, now()),
  status = 'inactive'
where status = 'killed';

update modules set
  inactive_reason = 'manual_pause',
  inactive_since = coalesce(inactive_since, updated_at, now()),
  status = 'inactive'
where status = 'paused';

update modules set
  inactive_reason = 'scaffold',
  inactive_since = coalesce(inactive_since, updated_at, now()),
  status = 'inactive'
where status = 'scaffold';

-- Drop old constraint if present, recreate with simplified set
do $$ begin
  if exists (select 1 from pg_constraint where conname = 'modules_status_check') then
    alter table modules drop constraint modules_status_check;
  end if;
end $$;

alter table modules add constraint modules_status_check
  check (status in ('active', 'paper', 'inactive'));
