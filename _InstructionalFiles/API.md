# PolyMarket Bot — Polymarket API Integration

## APIs Used

### 1. CLOB API (Trading)
- **SDK**: `py-clob-client` (Python)
- **Purpose**: Place/cancel orders, get order book, check balances
- **Auth**: API key + secret + passphrase (L2 auth via private key)
- **Base URL**: `https://clob.polymarket.com`

#### Key Endpoints
| Endpoint | Purpose |
|----------|---------|
| `GET /markets` | List all markets |
| `GET /markets/{id}` | Market details + order book |
| `POST /orders` | Place order |
| `DELETE /orders/{id}` | Cancel order |
| `GET /orders` | List user orders |
| `GET /positions` | User positions |
| `GET /balances` | USDC balance |

#### Auth Flow
1. Generate API credentials at polymarket.com (key, secret, passphrase)
2. Sign requests with L2 wallet private key (for order placement)
3. Credentials stored in `.env`:
   ```
   POLYMARKET_API_KEY=...
   POLYMARKET_SECRET=...
   POLYMARKET_PASSPHRASE=...
   POLYMARKET_PRIVATE_KEY=...
   ```

#### Rate Limits
- 100 requests/second per API key
- WebSocket connections: 5 per key
- Order placement: no specific limit but throttle to avoid rejection

### 2. Gamma API (Market Data)
- **Purpose**: Market metadata, snapshots, resolution data
- **Auth**: None (public)
- **Base URL**: `https://gamma-api.polymarket.com`

#### Key Endpoints
| Endpoint | Purpose |
|----------|---------|
| `GET /markets` | All markets with metadata |
| `GET /markets/{id}` | Single market detail |
| `GET /events` | Events (groups of markets) |
| `GET /prices` | Current prices |

#### Usage in This Project
- `nightly_sync.py` pulls market snapshots → SQLite
- 80K+ rows in `polymarket.db`
- Runs nightly via Windows Task Scheduler

### 3. WebSocket Feeds (Phase 4)
- **Purpose**: Real-time price updates, order book changes
- **URL**: `wss://ws-subscriptions-clob.polymarket.com/ws/`
- **Channels**: `market` (price ticks), `user` (order updates)

#### Implementation (bot/core/)
- `websocket_feeds.py` — connection manager
- `book_cache.py` — local order book mirror
- `heartbeat.py` — connection health monitoring

## Data Models

### Market
```python
{
    "condition_id": "0x...",
    "question": "Will NYC temp exceed 50°F on March 25?",
    "tokens": [{"token_id": "...", "outcome": "Yes"}, ...],
    "end_date_iso": "2026-03-25T00:00:00Z",
    "active": true,
    "closed": false
}
```

### Order
```python
{
    "id": "order-uuid",
    "market": "condition_id",
    "asset_id": "token_id",
    "side": "BUY",
    "size": 10.0,
    "price": 0.65,
    "status": "LIVE"  # CREATED → PENDING_NEW → LIVE → FILLED/CANCELLED
}
```

## MCP Server
- Located at `mcp-polymarket/server.py`
- Provides Claude Code access to Polymarket data
- Config in `.mcp.json`

## Key Notes
- All trading on Polygon L2 (USDC)
- Settlement via UMA Optimistic Oracle
- Markets resolve to 0 or 1 (binary outcomes)
- Prices = implied probabilities (0.65 = 65% chance)
- Always validate `PAPER_MODE=true` before any live execution
