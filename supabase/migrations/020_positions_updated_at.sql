-- Adds positions.updated_at + auto-bump trigger so
-- exit_manager.release_stuck_closing_positions can detect rows stuck in
-- status='closing' beyond STUCK_CLOSING_THRESHOLD_MINUTES.
--
-- Before this migration the SELECT errored every cycle with
-- "column positions.updated_at does not exist" and stranded positions
-- never recovered (silent data integrity bug).

ALTER TABLE positions
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Backfill historical rows: use closed_at when present (closed positions),
-- otherwise opened_at (still-open positions). NULL safeguard via COALESCE.
UPDATE positions
SET updated_at = COALESCE(closed_at, opened_at, now())
WHERE updated_at = now()::date::timestamptz OR updated_at IS NULL;

-- Auto-bump trigger on every UPDATE.
CREATE OR REPLACE FUNCTION set_positions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS positions_updated_at_trigger ON positions;

CREATE TRIGGER positions_updated_at_trigger
BEFORE UPDATE ON positions
FOR EACH ROW
EXECUTE FUNCTION set_positions_updated_at();

-- Index for the exit_manager query (status='closing' AND updated_at < cutoff).
CREATE INDEX IF NOT EXISTS idx_positions_closing_updated_at
  ON positions (updated_at) WHERE status = 'closing';
