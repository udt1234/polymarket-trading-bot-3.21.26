# PolyMarket Bot — Architecture

## System Overview
```
                    ┌──────────────────────────────────┐
                    │        External Data Sources      │
                    │  xTracker | Gamma | CLOB | News  │
                    │  LunarCrush | Claude | Schedule  │
                    └───────────────┬──────────────────┘
                                    │
┌─────────────────┐     ┌──────────▼─────────┐     ┌─────────────┐
│   Next.js PWA   │────▶│   FastAPI (API)     │────▶│  Supabase   │
│   (web/)        │◀────│   (api/)            │◀────│  (Postgres) │
│   Port 3000     │     │   Port 8000         │     │  + Auth     │
└─────────────────┘     └──────────┬─────────┘     └─────────────┘
                                   │
                        ┌──────────▼──────────┐
                        │   Trading Engine     │
                        │  Scheduler (5min)    │
                        │  Risk Manager (15)   │
                        │  Circuit Breaker     │
                        │  Paper/Live Executor │
                        │  Shadow Mode         │
                        │  Module Registry     │
                        └─────────────────────┘
```

## Signal Pipeline (per cycle)
```
1. Fetch Data ──→ xTracker (counts) + Gamma (prices) + News (4 queries)
                  + LunarCrush (velocity) + Schedule (events)
2. Regime     ──→ Z-score from history + Claude Haiku override from news
3. Pacing     ──→ 5 models: Linear, Bayesian, DOW-Hourly, Historical, Hawkes
4. Weights    ──→ %-based time weights + calibration Brier adjustment
5. Projection ──→ Negative Binomial + Normal → bracket probabilities
6. Normalize  ──→ Cross-bracket sum to 1.0
7. Modify     ──→ Signal = News(50%) + LunarCrush(30%) + Schedule(20%)
8. Rank       ──→ Top 3 brackets by edge × sqrt(liquidity) × confidence
9. Size       ──→ Fractional Kelly (0.25x) with regime + time decay
10. Risk      ──→ 15 checks (all must pass)
11. Execute   ──→ Paper simulate or Live CLOB order
12. Log       ──→ Signal + decision + metadata → Supabase
```

## Module File Map (updated 2026-05-16)
```
api/modules/shared/        # cross-module reusable utilities
├── pacing.py              # 3 pacing functions (linear, bayesian, dow-hourly)
├── enhanced_pacing.py     # Recency weights, DOW variance, pace acceleration
├── hawkes.py              # Self-exciting Hawkes process for burst detection
├── projection.py          # Ensemble weights + bracket probs (NB + Normal)
├── regime.py              # Z-score regime classification
├── signals.py             # Signal modifier + Kelly sizing + bracket ranking
├── polymarket.py          # xTracker + Gamma + CLOB API fetchers
├── news.py                # Google News RSS (4 queries, deduped)
├── news_classifier.py     # Claude Haiku regime override from headlines
├── parquet_history.py     # facade re-exporting parquet helpers (impl in truth_social/)
├── price_timing.py        # Wait-for-dip + historical price patterns
└── module_config_utils.py # Schema validation helpers

api/modules/truth_social/
├── module.py              # Ensemble strategy for realDonaldTrump
├── schedule.py            # Presidential schedule (factba.se + news fallback)
├── trends.py              # Google Trends modifier
├── historical_winners.py  # Bracket winner frequency from auction_archive
├── parquet_history.py     # S3 historical price data (pandas)
├── truthsocial_direct.py  # Direct TruthSocial scrape (xTracker fallback)
└── module_config.py       # Ensemble weights, regime params, parquet toggle

api/modules/elon_tweets/
├── module.py              # Ensemble strategy for elonmusk
├── lunarcrush.py          # LunarCrush sentiment integration
└── module_config.py

api/modules/spike_trading/
├── module.py              # Multi-auction-type lottery-ticket ladder
├── data.py                # Spike-specific data fetchers
├── decision.py            # adaptive_buy_price, slow_bleed_sell_price helpers
├── strategies/            # Pluggable strategy plugins
│   ├── cheap_lottery_pacing.py
│   ├── mid_range_spike.py
│   └── big_hold_monthly.py
└── module_config.py

api/modules/copy_trading/  # Mirrors whale trades from a target wallet
├── module.py
├── data.py
└── module_config.py
```

## Database (Supabase) — 19 Tables (Migrations 001-019)
modules, orders, trades, positions, daily_pnl, signals, logs, settings,
statistical_tests, module_ab_tests, calibration_log, alerts, audit_log,
price_snapshots, post_count_snapshots, truth_social_posts, elon_tweets,
spike_positions, pending_signals, auction_archive, whale_snapshots,
whale_wallet_profiles, copy_trading_* (3 tables), order_book_snapshots,
spike_state_snapshots, signal_type column on signals
(see supabase/migrations/ for the canonical list)

## API Endpoints (Key)
| Endpoint | Purpose |
|----------|---------|
| `/api/dashboard/metrics` | Overview KPIs + RSS/news metadata |
| `/api/modules/{id}` | Module CRUD + auction detail |
| `/api/portfolio/positions` | Open/closed positions + P&L |
| `/api/analytics/summary` | Sharpe, Sortino, calibration |
| `/api/settings/risk` | Risk parameter management |

## Environment Variables (Required)
```
POLYMARKET_API_KEY, SECRET, PASSPHRASE, PRIVATE_KEY
SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY
LUNARCRUSH_API_KEY
ANTHROPIC_API_KEY
```
