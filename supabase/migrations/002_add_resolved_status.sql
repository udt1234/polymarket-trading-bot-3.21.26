-- Add 'resolved' to modules status constraint
alter table modules drop constraint if exists modules_status_check;
alter table modules add constraint modules_status_check
  check (status in ('active', 'paused', 'paper', 'scaffold', 'resolved', 'killed'));

-- Index for resolution queries
create index if not exists idx_calibration_resolved on calibration_log(resolved_at desc);
create index if not exists idx_calibration_module on calibration_log(module_id);
