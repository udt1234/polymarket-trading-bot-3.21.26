-- Migration: add signal_type column to signals + backfill from metadata
-- Created 2026-05-08. Spec: _ImportantConfigFiles/WHALE_BRACKET_CARDS_SPEC.md

ALTER TABLE signals ADD COLUMN IF NOT EXISTS signal_type TEXT;
CREATE INDEX IF NOT EXISTS idx_signals_type_module ON signals (module_id, signal_type);

-- Backfill heuristic (validated against prod data 2026-05-08):
--   metadata.signal_type wins if already set
--   metadata.strategy='spike_trading' -> 'spike'
--   everything else -> 'baseline'
-- This matches reality: the only spike-detector we run today is the Spike
-- Trading module, which always tags its emissions with strategy='spike_trading'.
UPDATE signals
SET signal_type = COALESCE(
    metadata->>'signal_type',
    CASE
        WHEN metadata->>'strategy' = 'spike_trading' THEN 'spike'
        ELSE 'baseline'
    END
)
WHERE signal_type IS NULL;
