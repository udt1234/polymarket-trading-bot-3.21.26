-- 023: Clear old Spike tracker rows that were opened before any fill.

update spike_positions
set state = 'LIQUIDATED',
    closed_at = now(),
    last_decision = 'AUTO_LIQUIDATE_NO_SHARES',
    last_decision_at = now()
where state in ('WAITING', 'MONITORING')
  and coalesce(entry_size_shares, 0) <= 0;
