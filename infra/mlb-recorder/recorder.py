"""MLB (and other sports) order-book recorder.

Forward-captures tick-level L2 for live sports game markets so we can backtest
the garbage-time sweep on our OWN clean data (independent of the free pmxt
archive) and later feed a live sweep module. Deploy on Railway EU (order-book
reads are fine through the geoblock; only ORDER placement is blocked).

- Discovers live game markets from Gamma every DISCOVER_MIN minutes
  (SERIES_IDS, default MLB=3). Keeps games from ~4h before first pitch to a few
  hours after (garbage time + settlement lag).
- One CLOB market-channel WebSocket, subscribed to all active game tokens
  (re-subscribes on discovery changes). Stall watchdog + backoff reconnect.
- Buffers events and flushes part-parquets to DATA_DIR/<series>/<date>/<hour>_<n>.parquet
  (append-free; a reader globs the parts). Schema mirrors pmxt/the tweet recorder
  so backtests read all three interchangeably.

Env: SERIES_IDS (csv, default "3"), DATA_DIR (default ./data), DISCOVER_MIN=20,
     FLUSH_SEC=30, GAMMA_BASE override optional.
"""
import asyncio
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pandas as pd

# base game moneyline slug, e.g. mlb-col-lad-2026-07-08 (no -first-five/-run-line suffix)
BASE_GAME_RE = re.compile(r"^[a-z]+-[a-z0-9]+-[a-z0-9]+-\d{4}-\d{2}-\d{2}$")

GAMMA = os.getenv("GAMMA_BASE", "https://gamma-api.polymarket.com")
CLOB_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
SERIES_IDS = [s.strip() for s in os.getenv("SERIES_IDS", "3").split(",") if s.strip()]
DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
DISCOVER_MIN = float(os.getenv("DISCOVER_MIN", "20"))
FLUSH_SEC = float(os.getenv("FLUSH_SEC", "30"))
SERIES_LABEL = {"3": "mlb", "1": "nfl", "2": "nba", "4": "nhl"}

_buffer: list[dict] = []
_tokenmap: dict[str, dict] = {}   # asset_id -> {slug, series, cond, outcome}
_flush_n = 0


def log(*a):
    print(f"[recorder {datetime.now(timezone.utc).strftime('%H:%M:%S')}]", *a, flush=True)


async def discover() -> dict[str, dict]:
    """Live MONEYLINE tokens for the CURRENT slate: base game markets (no prop
    suffix) whose game starts within [-8h, +16h] of now (in-progress + about to
    start + settlement lag). Keeps the token set small enough for one WS."""
    tm: dict[str, dict] = {}
    now = datetime.now(timezone.utc)
    async with httpx.AsyncClient(timeout=40) as c:
        for sid in SERIES_IDS:
            label = SERIES_LABEL.get(sid, f"series{sid}")
            try:
                r = await c.get(f"{GAMMA}/events", params={
                    "series_id": sid, "limit": 300, "closed": "false",
                    "order": "startDate", "ascending": "true"})
                evs = r.json() if r.status_code == 200 else []
            except Exception as e:
                log("discover error", sid, e); continue
            for e in evs:
                slug = e.get("slug") or ""
                if not BASE_GAME_RE.match(slug):
                    continue  # skip props / sub-markets, keep the moneyline
                sd = e.get("startDate")
                try:
                    start = datetime.fromisoformat(sd.replace("Z", "+00:00")) if sd else None
                except (TypeError, ValueError):
                    start = None
                if start and not (now - timedelta(hours=8) <= start <= now + timedelta(hours=28)):
                    continue
                for mk in (e.get("markets") or []):
                    if mk.get("closed"):
                        continue
                    try:
                        toks = json.loads(mk.get("clobTokenIds") or "[]")
                        outs = json.loads(mk.get("outcomes") or "[]")
                    except (TypeError, ValueError):
                        continue
                    if len(toks) != 2:
                        continue
                    for i, tok in enumerate(toks):
                        tm[tok] = {"slug": slug, "series": label,
                                   "cond": mk.get("conditionId"),
                                   "outcome": outs[i] if i < len(outs) else ""}
    return tm


def _rows_from(msg: dict, recv_ts: float) -> list[dict]:
    """Normalize a market-channel event into recorder rows."""
    et = msg.get("event_type") or msg.get("type") or ""
    aid = msg.get("asset_id") or ""
    meta = _tokenmap.get(aid, {})
    base = {"recv_ts": recv_ts, "ts": int(msg.get("timestamp") or recv_ts * 1000),
            "event_type": et, "asset_id": aid, "market": msg.get("market") or meta.get("cond"),
            "series": meta.get("series"), "slug": meta.get("slug"),
            "outcome": meta.get("outcome"), "best_bid": None, "best_ask": None,
            "price": None, "size": None, "side": None, "bids": None, "asks": None}
    if et == "book":
        bids = msg.get("bids") or msg.get("buys") or []
        asks = msg.get("asks") or msg.get("sells") or []
        base["bids"] = json.dumps(bids); base["asks"] = json.dumps(asks)
        base["best_bid"] = float(bids[-1]["price"]) if bids else None
        base["best_ask"] = float(asks[0]["price"]) if asks else None
        return [base]
    if et in ("price_change", "last_trade_price"):
        for ch in (msg.get("changes") or [msg]):
            row = dict(base)
            row["price"] = float(ch.get("price")) if ch.get("price") is not None else None
            row["size"] = float(ch.get("size")) if ch.get("size") is not None else None
            row["side"] = ch.get("side")
            bb, ba = msg.get("best_bid"), msg.get("best_ask")
            row["best_bid"] = float(bb) if bb is not None else None
            row["best_ask"] = float(ba) if ba is not None else None
            return [row] if et == "last_trade_price" else [row]
    return [base]


def flush():
    global _buffer, _flush_n
    if not _buffer:
        return
    rows, _buffer = _buffer, []
    df = pd.DataFrame(rows)
    now = datetime.now(timezone.utc)
    series = df["series"].dropna().iloc[0] if df["series"].notna().any() else "sports"
    out = DATA_DIR / series / now.strftime("%Y-%m-%d")
    out.mkdir(parents=True, exist_ok=True)
    _flush_n += 1
    path = out / f"{now.strftime('%H')}_{_flush_n:05d}.parquet"
    df.to_parquet(path, index=False)
    log(f"flushed {len(df)} rows -> {path}")


async def flusher():
    while True:
        await asyncio.sleep(FLUSH_SEC)
        try:
            flush()
        except Exception as e:
            log("flush error", e)


async def rediscover():
    global _tokenmap
    while True:
        try:
            tm = await discover()
            if tm:
                _tokenmap = tm
                log(f"discovered {len(tm)} live game tokens "
                    f"({len({v['slug'] for v in tm.values()})} games)")
        except Exception as e:
            log("rediscover error", e)
        await asyncio.sleep(DISCOVER_MIN * 60)


async def stream():
    import websockets
    backoff = 1
    while True:
        toks = list(_tokenmap.keys())
        if not toks:
            await asyncio.sleep(5)
            continue
        try:
            async with websockets.connect(CLOB_WS, ping_interval=10, max_size=8 * 2**20) as ws:
                await ws.send(json.dumps({"assets_ids": toks[:500], "type": "market"}))
                log(f"subscribed to {len(toks)} tokens")
                backoff = 1
                sub_tokens = set(toks)
                last = time.time()
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=45)
                    except asyncio.TimeoutError:
                        log("stall - reconnecting"); break
                    last = time.time()
                    # resubscribe if discovery changed the token set materially
                    cur = set(_tokenmap.keys())
                    if len(cur ^ sub_tokens) > 4:
                        break
                    try:
                        payload = json.loads(raw)
                    except (TypeError, ValueError):
                        continue
                    for msg in (payload if isinstance(payload, list) else [payload]):
                        if isinstance(msg, dict) and msg.get("event_type") != "":
                            _buffer.extend(_rows_from(msg, time.time()))
        except Exception as e:
            log(f"ws dropped ({e}) - reconnect in {backoff}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


async def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log(f"MLB recorder starting; series={SERIES_IDS} data_dir={DATA_DIR}")
    global _tokenmap
    _tokenmap = await discover()
    log(f"initial discovery: {len(_tokenmap)} tokens")
    await asyncio.gather(rediscover(), flusher(), stream())


if __name__ == "__main__":
    asyncio.run(main())
