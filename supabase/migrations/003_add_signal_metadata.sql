-- Add metadata JSONB to signals table for storing RSS, regime, model context
alter table signals add column if not exists metadata jsonb default '{}';

-- Add metadata to calibration_log for per-model Brier tracking
alter table calibration_log add column if not exists metadata jsonb default '{}';
