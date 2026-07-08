"""Crypto hourly Up/Down sweep - PHASE 1: is the LATE FAVORITE efficiently priced?

The make-or-break screen before any heavy L2 pull. For every resolved BTC/ETH/
SOL/XRP hourly up-or-down market we pull the last ~15 min of 1-min price bars
for BOTH sides, then, at a decision time T seconds before resolution, define the
FAVORITE = the side with the higher price at T (NO look-ahead: decision uses
only data <= T; the outcome is used ONLY to score). We then ask:

  Q1  Calibration: for favorites priced in bucket [p, p+): do they actually win
      at rate >= p? (efficient) or > p (crowd underprices the winner = edge)?
  Q2  Taker EV: buying the favorite at its price at T, held to resolution, after
      fees - the FRICTIONLESS UPPER BOUND (real fills only worse).
  Q3  Maker dip: the MIN price the favorite touched in the final window (1-min
      granularity) - a rough proxy for "could a resting bid below fair have
      filled?"; real fill-rate needs tick L2 (Phase 2).

Obeys THE WALL (decide on data <= T; outcome for scoring only). 1-min bars are
coarse (the sub-3s sweep lives finer) so this bounds the crowd-efficiency
question; it does NOT prove/disprove the maker-fill edge (that is Phase 2).

Run: python -u _DataMetricPulls/pacing_backtest/crypto_sweep/phase1_efficiency.py
"""
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import httpx

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
SERIES = {"BTC": 10114, "ETH": 10117, "SOL": 10122, "XRP": 10123}
MAX_PER_SERIES = 100          # Gamma page cap
DECISION_LAGS = [60, 180]     # seconds before resolution to "decide" (1-min data floor ~60s)
FINAL_WINDOW_MIN = 5          # window for the maker-dip proxy
FEE = 0.0                     # maker fee under V2 is zero; taker EV shown fee-free = generous


def discover(series_id: int, limit: int) -> list[dict]:
    out = []
    r = httpx.get(f"{GAMMA}/events", params={
        "series_id": str(series_id), "limit": limit, "closed": "true",
        "order": "endDate", "ascending": "false"}, timeout=40)
    for e in r.json() if r.status_code == 200 else []:
        mk = (e.get("markets") or [{}])[0]
        try:
            toks = json.loads(mk.get("clobTokenIds") or "[]")
            prices = json.loads(mk.get("outcomePrices") or "[]")
        except (TypeError, ValueError):
            continue
        if len(toks) != 2 or len(prices) != 2:
            continue
        if prices[0] not in ("0", "1") or prices[0] == prices[1]:
            continue  # unresolved / ambiguous
        end = datetime.fromisoformat(e["endDate"].replace("Z", "+00:00"))
        out.append({
            "slug": e.get("slug"), "resolve_ts": int(end.timestamp()),
            "up_token": toks[0], "down_token": toks[1],
            "winner": "up" if prices[0] == "1" else "down"})
    return out


def price_series(token: str, start_ts: int, end_ts: int) -> list[tuple[int, float]]:
    try:
        r = httpx.get(f"{CLOB}/prices-history", params={
            "market": token, "startTs": start_ts, "endTs": end_ts, "fidelity": 1},
            timeout=25)
        return [(int(p["t"]), float(p["p"])) for p in r.json().get("history", [])]
    except Exception:
        return []


def price_at(series: list[tuple[int, float]], t: int) -> float | None:
    """Last price with timestamp <= t (no look-ahead)."""
    v = None
    for ts, p in series:
        if ts <= t:
            v = p
        else:
            break
    return v


def main() -> None:
    markets = []
    for sym, sid in SERIES.items():
        ms = discover(sid, MAX_PER_SERIES)
        for m in ms:
            m["sym"] = sym
        markets.extend(ms)
        print(f"discovered {sym}: {len(ms)}", flush=True)
    print(f"total resolved markets: {len(markets)}\n", flush=True)

    # rows: per (market, lag) decision
    rows = []
    for i, m in enumerate(markets):
        r = m["resolve_ts"]
        up = price_series(m["up_token"], r - 20 * 60, r)
        dn = price_series(m["down_token"], r - 20 * 60, r)
        if not up or not dn:
            continue
        for lag in DECISION_LAGS:
            t = r - lag
            pu, pd = price_at(up, t), price_at(dn, t)
            if pu is None or pd is None:
                continue
            fav_side = "up" if pu >= pd else "down"
            fav_price = max(pu, pd)
            won = fav_side == m["winner"]
            # maker-dip proxy: min favorite price in final window
            fav_series = up if fav_side == "up" else dn
            wl = [p for ts, p in fav_series if r - FINAL_WINDOW_MIN * 60 <= ts <= r]
            rows.append({"sym": m["sym"], "lag": lag, "fav_price": fav_price,
                         "won": won, "dip_min": min(wl) if wl else fav_price})
        if (i + 1) % 50 == 0:
            print(f"  processed {i+1}/{len(markets)}", flush=True)
        time.sleep(0.03)

    print(f"\ndecision rows: {len(rows)}\n")
    for lag in DECISION_LAGS:
        sub = [x for x in rows if x["lag"] == lag]
        if not sub:
            continue
        print(f"===== decision at T-{lag}s (n={len(sub)}) =====")
        # Q1 calibration by price bucket
        buckets = [(0.90, 0.95), (0.95, 0.97), (0.97, 0.99), (0.99, 1.001)]
        print(f"  {'fav price':<12}{'n':>5}{'win rate':>10}{'implied':>9}{'edge(WR-p)':>11}")
        for lo, hi in buckets:
            b = [x for x in sub if lo <= x["fav_price"] < hi]
            if not b:
                continue
            wr = sum(x["won"] for x in b) / len(b)
            avg_p = sum(x["fav_price"] for x in b) / len(b)
            print(f"  [{lo:.2f},{hi:.2f}){len(b):>5}{wr:>10.3f}{avg_p:>9.3f}"
                  f"{wr-avg_p:>+11.3f}")
        # Q2 taker EV: buy favorite at fav_price, held to resolution
        fav = [x for x in sub if x["fav_price"] >= 0.97]
        if fav:
            ev = sum((1.0 - x["fav_price"]) if x["won"] else (-x["fav_price"])
                     for x in fav) / len(fav)
            wr = sum(x["won"] for x in fav) / len(fav)
            print(f"  TAKER (buy fav>=0.97 @ market, frictionless): n={len(fav)} "
                  f"win={wr:.3f} EV/contract={ev:+.4f} (${ev*100:+.2f} per $100)")
        # Q3 maker-dip proxy: buy at the 5-min-min favorite price if <= 0.98
        BID = 0.98
        fills = [x for x in sub if x["fav_price"] >= 0.97 and x["dip_min"] <= BID]
        if fills:
            ev = sum((1.0 - BID) if x["won"] else (-BID) for x in fills) / len(fills)
            wr = sum(x["won"] for x in fills) / len(fills)
            print(f"  MAKER proxy (rest {BID} bid, 'fills' if 1-min dip<= {BID}): "
                  f"fills={len(fills)}/{len([x for x in sub if x['fav_price']>=0.97])} "
                  f"win={wr:.3f} EV/fill={ev:+.4f} (${ev*100:+.2f} per $100) "
                  f"[coarse - Phase 2 needed]")
        print()


if __name__ == "__main__":
    main()
