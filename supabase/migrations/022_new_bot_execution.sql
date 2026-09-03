-- New-bot execution core (BUILD_SPEC E5/E6, PART J Step 2).
-- Orders state machine: submitted -> open -> partially_filled -> filled ->
-- confirmed (on-chain). Adds top-level CLOB ids so the fill poller / user WS
-- can reconcile without digging in metadata.

ALTER TABLE orders ADD COLUMN IF NOT EXISTS token_id text;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS clob_order_id text;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS post_only boolean DEFAULT false;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS order_type text DEFAULT 'GTC';
ALTER TABLE orders ADD COLUMN IF NOT EXISTS size_filled numeric DEFAULT 0;

ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_status_check;
ALTER TABLE orders ADD CONSTRAINT orders_status_check CHECK (status IN (
  'created', 'submitted', 'open', 'live', 'partially_filled', 'filled',
  'confirmed', 'cancelled', 'rejected', 'settled'
));

CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_clob_order_id
  ON orders (clob_order_id) WHERE clob_order_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status);
