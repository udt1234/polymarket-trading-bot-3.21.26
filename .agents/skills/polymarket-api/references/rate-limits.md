# Polymarket Rate Limits & Retry Logic

## Rate Limits by API
| API | Rate | Enforcement |
|-----|------|-------------|
| CLOB read endpoints | 100 req/sec per key | HTTP 429 |
| CLOB order placement | Throttle to 1/sec | Rejection on burst |
| Gamma API | No published limit | 500ms delay recommended |
| xTracker API | No published limit | 300ms delay recommended |
| CLOB WebSocket | 5 connections per key | Connection refused |

## Retry Strategy
- Use exponential backoff: base=1s, max=60s, factor=2
- On HTTP 429: respect `Retry-After` header if present
- On HTTP 5xx: retry up to 3 times with backoff
- On WebSocket disconnect: exponential backoff (1s, 2s, 4s, 8s... max 60s)
- On timeout: retry once after 5s, then fail

## Implementation Pattern
```python
async def fetch_with_retry(url, max_retries=3):
    for attempt in range(max_retries):
        try:
            resp = await client.get(url, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(min(2 ** attempt, 60))
```

## Critical: IP Bans
- Sustained bursting above rate limits may result in IP ban
- xTracker is particularly sensitive — always enforce 300ms delay
- If banned, wait 15 minutes before retrying
