-- Migration: auction_archive — canonical record of every resolved auction
-- across ALL modules. One table, scoped by module_id. Created 2026-05-08.
-- Spec: Phase A of post-Phase-1 archive work.

CREATE TABLE IF NOT EXISTS auction_archive (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    module_id UUID REFERENCES modules(id),       -- nullable so parquet backfills
                                                 -- without a matching module row
                                                 -- still land
    handle TEXT NOT NULL,                        -- 'realDonaldTrump', 'elonmusk', etc.
    platform TEXT,                               -- 'truthsocial' | 'x' | future
    auction_slug TEXT NOT NULL,
    tracking_id TEXT,
    window_days NUMERIC NOT NULL,                -- 1, 2, 7, 30 ...
    start_date TIMESTAMPTZ NOT NULL,
    end_date TIMESTAMPTZ NOT NULL,

    -- Final outcome (the source of truth for "did bracket X win?")
    final_value NUMERIC,                         -- e.g. 65 tweets, 78°F, $97k BTC
    winning_bracket TEXT,                        -- e.g. '40-64'
    bracket_outcomes JSONB,                      -- {"<40": false, "40-64": true, ...}
    bracket_end_prices JSONB,                    -- {"<40": 0.02, "40-64": 0.97, ...}

    -- Bot performance on THIS auction (null when source='parquet_backfill')
    bot_traded BOOLEAN DEFAULT FALSE,
    bot_brackets JSONB,                          -- ["<40","40-64"]
    bot_pnl NUMERIC,                             -- realized $ for this auction
    bot_signals_count INT DEFAULT 0,
    bot_won_brackets JSONB,                      -- which of bot_brackets paid out

    -- Polymarket market state
    total_volume NUMERIC,
    market_count INT,

    -- Per-module custom metrics (regime, pace_zscore, news_modifier, etc.)
    -- Each module writes its own keys to this JSONB. Schema never has to
    -- change when a new module wants a new metric.
    metrics JSONB DEFAULT '{}'::jsonb,

    archived_at TIMESTAMPTZ DEFAULT NOW(),
    source TEXT NOT NULL DEFAULT 'live_resolution',
                                                 -- 'parquet_backfill' | 'live_resolution'
                                                 -- | 'manual'

    -- Idempotency: same auction can be re-archived; UPSERT on this key.
    UNIQUE (handle, auction_slug)
);

CREATE INDEX IF NOT EXISTS idx_auction_archive_module_end
    ON auction_archive (module_id, end_date DESC);
CREATE INDEX IF NOT EXISTS idx_auction_archive_handle_window_end
    ON auction_archive (handle, window_days, end_date DESC);
CREATE INDEX IF NOT EXISTS idx_auction_archive_winning_bracket
    ON auction_archive (handle, window_days, winning_bracket);
