"""Whale movement tracker + auto-classifier (2026-07-24).

For every wallet in the whale registry: pull its recent trades from the Polymarket
data-api, append new ones to the whale_movements table (deduped), refresh its profile,
and AUTO-CLASSIFY its strategy archetype from behaviour. Runs on a systemd timer so we
build a movement history over time - the raw material for learning how profitable
wallets actually operate.

  python scripts/track_whales.py                 # track all registered whales
  python scripts/track_whales.py --classify 0x.. # print a classification for one wallet
"""
import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from api.dependencies import get_supabase  # noqa: E402
from api.modules.shared import whale_registry  # noqa: E402

DATA = "https://data-api.polymarket.com"


def _activity(wallet: str, limit: int = 300) -> list[dict]:
    try:
        r = httpx.get(f"{DATA}/activity", params={"user": wallet, "limit": limit}, timeout=30)
        r.raise_for_status()
        return r.json() or []
    except Exception:
        return []


def _value(wallet: str) -> float | None:
    try:
        r = httpx.get(f"{DATA}/value", params={"user": wallet}, timeout=20)
        d = r.json() or []
        return float(d[0]["value"]) if d else None
    except Exception:
        return None


def classify(acts: list[dict]) -> str:
    """Infer a strategy archetype from recent activity behaviour."""
    trades = [a for a in acts if a.get("type") == "TRADE"]
    if not trades:
        return "other"
    n = len(trades)
    rebates = sum(1 for a in acts if a.get("type") in ("MAKER_REBATE", "TAKER_REBATE", "REWARD"))
    titles = [(a.get("title") or "").lower() for a in trades]
    tweet_frac = sum(1 for t in titles if "tweet" in t or "posts" in t or "of tweets" in t) / n
    # both-sided-ness: same market traded BUY and SELL
    by_mkt = {}
    for a in trades:
        m = a.get("conditionId") or a.get("market") or ""
        by_mkt.setdefault(m, set()).add(a.get("side"))
    two_sided = sum(1 for s in by_mkt.values() if len(s) >= 2)
    distinct_mkts = len(by_mkt)
    # timing clusters (arb: many legs within a few seconds)
    ts = sorted(int(a["timestamp"]) for a in trades if a.get("timestamp"))
    tight = sum(1 for i in range(1, len(ts)) if ts[i] - ts[i - 1] <= 2)

    if tweet_frac >= 0.5:
        return "tweet"
    if rebates >= max(3, n * 0.05) and two_sided >= 3:
        return "market_maker" if distinct_mkts >= 8 else "lp_reward"
    if tight >= max(5, n * 0.15):
        return "arbitrage"
    if two_sided >= 5 and distinct_mkts >= 10:
        return "market_maker"
    return "other"


def track_one(sb, wallet: str, meta: dict) -> int:
    acts = _activity(wallet)
    archetype = meta.get("archetype") or classify(acts)
    rows = []
    for a in acts:
        if a.get("type") != "TRADE":
            continue
        ts = a.get("timestamp")
        tx_ts = dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).isoformat() if ts else None
        price = a.get("price"); size = a.get("size")
        rows.append({
            "wallet": wallet, "archetype": archetype,
            "market_id": a.get("conditionId") or a.get("market"),
            "title": (a.get("title") or "")[:120], "side": a.get("side"),
            "outcome": a.get("outcome"),
            "price": float(price) if price is not None else None,
            "size": float(size) if size is not None else None,
            "usd": (float(price) * float(size)) if (price is not None and size is not None) else None,
            "tx_ts": tx_ts})
    inserted = 0
    for i in range(0, len(rows), 100):
        try:
            # upsert on the dedupe index -> only new movements land
            sb.table("whale_movements").upsert(
                rows[i:i + 100],
                on_conflict="wallet,market_id,side,price,size,tx_ts").execute()
            inserted += len(rows[i:i + 100])
        except Exception:
            pass
    # refresh profile (only columns known to exist on whale_wallet_profiles)
    try:
        val = _value(wallet)
        if val is not None:
            sb.table("whale_wallet_profiles").upsert(
                {"wallet": wallet, "portfolio_value": val}, on_conflict="wallet").execute()
    except Exception:
        pass
    # write back an auto-classification if the registry entry had none
    if not meta.get("archetype"):
        whale_registry.add(wallet, archetype, meta.get("label", ""), "auto")
    return archetype, len(rows), inserted


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--classify", help="classify one wallet and exit")
    a = ap.parse_args()
    if a.classify:
        print(a.classify, "->", classify(_activity(a.classify)))
        return
    sb = get_supabase()
    reg = whale_registry.load()
    if not reg:
        print("whale registry empty - add whales first")
        return
    summary = []
    for wallet, meta in reg.items():
        arch, seen, ins = track_one(sb, wallet, meta)
        summary.append(f"{wallet[:10]}({arch}): {seen} trades, {ins} upserted")
    print("track_whales:", " | ".join(summary))


if __name__ == "__main__":
    main()
