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

## Module File Map
```
api/modules/truth_social/
├── module.py          # Main evaluate() loop — orchestrates all sub-models
├── pacing.py          # 3 pacing functions (linear, bayesian, dow-hourly)
├── enhanced_pacing.py # Recency weights, DOW variance, pace acceleration
├── hawkes.py          # Self-exciting Hawkes process for burst detection
├── projection.py      # Ensemble weights + bracket probs (NB + Normal)
├── regime.py          # Z-score regime classification
├── signals.py         # Signal modifier + Kelly sizing + bracket ranking
├── data.py            # xTracker + Gamma + CLOB API fetchers
├── news.py            # Google News RSS (4 queries, deduped)
├── news_classifier.py # Claude Haiku regime override from headlines
├── schedule.py        # Presidential schedule (factba.se + news fallback)
├── parquet_history.py # S3 historical price data (pandas)
└── module_config.py   # Runtime config (half-life, regime, parquet toggle)
```

## Database (Supabase) — 13 Tables
modules, orders, trades, positions, daily_pnl, signals, logs, settings,
statistical_tests, module_ab_tests, calibration_log, alerts, audit_log

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
