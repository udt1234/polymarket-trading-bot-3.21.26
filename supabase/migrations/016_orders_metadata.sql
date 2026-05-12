-- Add metadata column to orders table.
-- PR #41 (LiveExecutor) writes `metadata={'profile': ..., 'clob_order_id': ...}`
-- on every order insert/update. Without this column, every live BUY ladder
-- emission crashes with "Could not find the 'metadata' column of 'orders'
-- in the schema cache" — meaning the order audit trail is incomplete AND
-- the trader's primary error path silently swallows. The TTL sweep also
-- relies on `metadata.clob_order_id` to cancel orders at the CLOB.
ALTER TABLE orders ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;
