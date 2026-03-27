import asyncio
import json
import logging
import websockets
from api.ws.feeds import broadcast

log = logging.getLogger(__name__)

CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

_tasks: list[asyncio.Task] = []


async def subscribe_to_market(token_id: str, market_id: str):
    while True:
        try:
            async with websockets.connect(CLOB_WS_URL) as ws:
                sub_msg = json.dumps({
                    "type": "subscribe",
                    "channel": "market",
                    "assets_ids": [token_id],
                })
                await ws.send(sub_msg)
                log.info(f"CLOB WS subscribed to {token_id}")

                async for message in ws:
                    try:
                        data = json.loads(message)
                        await broadcast("market_update", {
                            "market_id": market_id,
                            "token_id": token_id,
                            "data": data,
                        })
                    except json.JSONDecodeError:
                        continue

        except websockets.ConnectionClosed:
            log.warning(f"CLOB WS disconnected for {token_id}, reconnecting in 5s...")
            await asyncio.sleep(5)
        except Exception as e:
            log.error(f"CLOB WS error for {token_id}: {e}")
            await asyncio.sleep(10)


def start_clob_subscriptions(token_ids: dict[str, str]):
    for token_id, market_id in token_ids.items():
        task = asyncio.create_task(subscribe_to_market(token_id, market_id))
        _tasks.append(task)
    log.info(f"Started {len(token_ids)} CLOB WS subscriptions")


def stop_clob_subscriptions():
    for task in _tasks:
        task.cancel()
    _tasks.clear()
