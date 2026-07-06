-- Atomic exit claim (BUILD_SPEC E5): UPDATE .. SET status='closing' WHERE status='open'
ALTER TABLE positions DROP CONSTRAINT IF EXISTS positions_status_check;
ALTER TABLE positions ADD CONSTRAINT positions_status_check CHECK (status IN ('open','closing','closed'));
