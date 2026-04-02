# Polymarket API Endpoints Reference

## CLOB API (Trading) — `https://clob.polymarket.com`
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/markets` | GET | List all markets |
| `/markets/{id}` | GET | Market details + order book |
| `/midpoint?token_id={id}` | GET | Live midpoint price |
| `/orders` | POST | Place limit order (NEVER market) |
| `/orders/{id}` | DELETE | Cancel order |
| `/orders` | GET | List user orders |
| `/positions` | GET | User positions |
| `/balances` | GET | USDC balance |

## Gamma API (Market Data) — `https://gamma-api.polymarket.com`
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/markets` | GET | All markets with metadata |
| `/markets/{id}` | GET | Single market detail |
| `/events` | GET | Events (groups of markets) |
| `/events?slug={slug}` | GET | Event by slug |
| `/prices` | GET | Current prices |

## xTracker API — `https://xtracker.polymarket.com/api`
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/users/{handle}/trackings?platform=truthsocial` | GET | Active trackings |
| `/trackings/{id}?includeStats=true` | GET | Hourly breakdown |

## WebSocket — `wss://ws-subscriptions-clob.polymarket.com/ws/`
- Channels: `market` (price ticks), `user` (order updates)
- Must implement exponential backoff on reconnect
- Max 5 connections per API key

## Order Data Model
```python
{
    "id": "order-uuid",
    "market": "condition_id",
    "asset_id": "token_id",
    "side": "BUY",
    "size": 10.0,
    "price": 0.65,  # REQUIRED — never omit
    "status": "LIVE"  # CREATED → PENDING_NEW → LIVE → FILLED/CANCELLED
}
```
