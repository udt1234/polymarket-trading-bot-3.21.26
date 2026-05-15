-- Migration: whale_snapshots + whale_wallet_profiles for Phase 2 of
-- WHALE_BRACKET_CARDS_SPEC.md. Created 2026-05-13.
--
-- whale_snapshots: append-only, one row per (handle, auction_slug). Computed
--   nightly by scripts/refresh_whale_snapshots.py from per-market trade
--   history via the Polymarket data-api. Powers the 🐋 Whale Watching card.
--
-- whale_wallet_profiles: slowly-changing wallet identities. Refreshed weekly.
--   Surfaces portfolio_value, ROI, archetype-across-all-auctions for the top
--   wallets shown in the card.

CREATE TABLE IF NOT EXISTS whale_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    handle TEXT NOT NULL,                        -- 'realDonaldTrump', 'elonmusk', etc.
    market_universe TEXT[] NOT NULL,             -- conditionIds scanned for this snapshot
    auction_slug TEXT NOT NULL,                  -- e.g. 'elon-musk-of-tweets-may-2-may-4'
    auction_start TIMESTAMPTZ NOT NULL,
    auction_end TIMESTAMPTZ NOT NULL,
    final_outcome JSONB,                         -- {"winning_bucket": "40-64", "final_value": 55}
    archetype_breakdown JSONB NOT NULL,          -- {"market_maker": 0.38, "tail_scooper": 0.28, ...}
    archetype_dollar_volume JSONB NOT NULL,      -- {"market_maker": 142000, ...}
    top_wallets JSONB NOT NULL,                  -- array of {wallet, archetype, secondary, $flowed, ...}
    grid_metrics JSONB NOT NULL,                 -- archetype-level fill metrics
    computed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (handle, auction_slug)
);

CREATE INDEX IF NOT EXISTS idx_whale_snapshots_handle_end
    ON whale_snapshots (handle, auction_end DESC);

CREATE TABLE IF NOT EXISTS whale_wallet_profiles (
    wallet TEXT PRIMARY KEY,
    portfolio_value NUMERIC,
    cash NUMERIC,
    open_positions INT,
    closed_positions INT,
    win_rate_pct NUMERIC,
    total_invested NUMERIC,
    total_pnl NUMERIC,
    roi_pct NUMERIC,
    name_or_pseudonym TEXT,
    archetype_dominant TEXT,                     -- inferred across all auctions
    archetype_secondary TEXT,
    auctions_seen INT,
    refreshed_at TIMESTAMPTZ DEFAULT NOW()
);
