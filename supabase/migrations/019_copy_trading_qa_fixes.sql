-- 019: Copy Trading QA fixes — adds 'skipped_shadow' to copy_trade_log
-- action enum so shadow-mode decisions don't poison the dedupe index.
-- See QA report C-1 for full context.

alter table copy_trade_log
  drop constraint if exists copy_trade_log_our_action_check;

alter table copy_trade_log
  add constraint copy_trade_log_our_action_check
  check (our_action in (
    'mirrored', 'skipped_stale', 'skipped_drift', 'skipped_cap',
    'skipped_dedupe', 'skipped_circuit', 'skipped_perf_gate',
    'skipped_no_position', 'skipped_zero_size', 'skipped_error',
    'skipped_shadow'
  ));

-- M-5: document the weight_pct multiplier semantics so dashboard / SQL
-- users don't accidentally set it as a percentage (50.0 instead of 0.5).
comment on column copy_trade_wallets.weight_pct is
  'Multiplier on the whale''s size%, NOT a percentage. 1.0 = full mirror, 0.5 = half size, 0.0 = disabled mirror.';
