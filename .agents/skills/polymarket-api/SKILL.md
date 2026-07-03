---
name: polymarket-api
description: Auto-load when writing code that calls Polymarket CLOB API, Gamma API, xTracker, or order endpoints. Triggers on files in api/modules/*/data.py, api/services/executor*, api/services/market_data*, or any file importing py-clob-client.
---

You have deep knowledge of the Polymarket CLOB API and related data sources.

## Order Rules (NON-NEGOTIABLE)
- **ALWAYS use limit orders** — NEVER market orders. Every order must specify a `price` parameter.
- Order placement requires `PAPER_MODE != true` guard for live execution
- All orders go through risk manager (15 checks) before submission

## Rate Limits
| API | Delay | Limit |
|-----|-------|-------|
| xTracker | 300ms between calls | — |
| Gamma | 500ms between calls | — |
| CLOB read | — | 100 req/sec |
| CLOB order | 1s between calls | Throttle to avoid rejection |
| WebSocket | — | 5 connections per key |

## Pricing Priority
1. CLOB midpoint (most accurate for live pricing)
2. Gamma outcomePrices (fallback only)

## Auth Flow
- CLOB: API key + secret + passphrase + L2 private key signing
- Gamma: Public (no auth)
- xTracker: Public (no auth)

See references/api-endpoints.md for full endpoint spec.
See references/rate-limits.md for retry logic.
