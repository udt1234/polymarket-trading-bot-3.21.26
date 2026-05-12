-- Add token_id column to positions table.
-- The CLOB (Polymarket order book) requires the ERC-1155 token ID — a
-- 256-bit integer as string — when placing orders. Without this stored
-- on the position, the SELL leg can't reconstruct it.
--
-- Backfill: leave NULL. Existing open positions need a one-time backfill
-- from the corresponding market's clobTokenIds[0]; if a SELL needs to
-- fire before the backfill, LiveExecutor refuses (see executor.py guard).
ALTER TABLE positions ADD COLUMN IF NOT EXISTS token_id TEXT;
CREATE INDEX IF NOT EXISTS idx_positions_token_id ON positions (token_id) WHERE token_id IS NOT NULL;
