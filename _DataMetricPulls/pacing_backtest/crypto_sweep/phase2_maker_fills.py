"""Crypto hourly Up/Down sweep - PHASE 2: real maker-fill simulation on tick L2.

Phase 1 (1-min bars) said: taker is dead (efficient); a maker bid below fair
that "fills on a dip" looked +EV very late - but 1-min bars can't tell a real
trade from a bid/ask touch. This measures the REAL thing on pmxt tick data:

  Rest a post-only BUY bid at price B on the FAVORITE (defined at decision time
  T by the higher best_bid in the tick stream - NO look-ahead), placed at T =
  resolve - LAG seconds. It FILLS if a real trade prints at price <= B in
  (T, resolve] (generous: any print <=B, upper bound on fills). P&L per fill =
  (1 - B) if the favorite won else (-B); maker fee = 0 under V2 (+ rebate, not
  added here so the number is conservative). Winner from Gamma outcomePrices.

Decisive metric: FILL RATE (how often a seller actually dumps to us that late)
and win rate on fills. If even this generous fill assumption rarely fills, the
maker sweep is not viable for us.

Run: python -u _DataMetricPulls/pacing_backtest/crypto_sweep/phase2_maker_fills.py [HOURS]
"""
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import duckdb
import httpx

GAMMA = "https://gamma-api.polymarket.com"
SERIES = {"BTC": 10114, "ETH": 10117, "SOL": 10122, "XRP": 10123}
PMXT = "https://r2v2.pmxt.dev/polymarket_orderbook_{hour}.parquet"
LAGS = [10, 30, 60]
BIDS = [0.97, 0.98, 0.99]
HOURS_BACK = int(sys.argv[1]) if len(sys.argv) > 1 else 36


def discover_all() -> list[dict]:
    out = []
    for sym, sid in SERIES.items():
        r = httpx.get(f"{GAMMA}/events", params={
            "series_id": str(sid), "limit": 100, "closed": "true",
            "order": "endDate", "ascending": "false"}, timeout=40)
        for e in r.json() if r.status_code == 200 else []:
            mk = (e.get("markets") or [{}])[0]
            try:
                toks = json.loads(mk.get("clobTokenIds") or "[]")
                prices = json.loads(mk.get("outcomePrices") or "[]")
            except (TypeError, ValueError):
                continue
            if len(toks) != 2 or prices[:1] not in (["0"], ["1"]) or prices[0] == prices[1]:
                continue
            end = datetime.fromisoformat(e["endDate"].replace("Z", "+00:00"))
            out.append({"sym": sym, "slug": e.get("slug"),
                        "resolve": end, "resolve_ts": int(end.timestamp()),
                        "up_token": toks[0], "down_token": toks[1],
                        "winner_token": toks[0] if prices[0] == "1" else toks[1]})
    return out


def main() -> None:
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    markets = discover_all()
    # keep the most recent HOURS_BACK resolution hours
    markets.sort(key=lambda m: m["resolve_ts"], reverse=True)
    hours = sorted({m["resolve"].strftime("%Y-%m-%dT%H") for m in markets}, reverse=True)[:HOURS_BACK]
    hset = set(hours)
    markets = [m for m in markets if m["resolve"].strftime("%Y-%m-%dT%H") in hset]
    by_hour: dict[str, list[dict]] = defaultdict(list)
    for m in markets:
        by_hour[m["resolve"].strftime("%Y-%m-%dT%H")].append(m)
    print(f"markets={len(markets)} across {len(by_hour)} resolution hours "
          f"(pmxt files to pull: {len(by_hour)})", flush=True)

    # stats[(lag,bid)] = [fills, wins, pnl_sum, considered]
    stats = defaultdict(lambda: [0, 0, 0.0, 0])
    no_late_trades = 0
    processed = 0
    for res_hour, ms in sorted(by_hour.items(), reverse=True):
        file_hour = (datetime.strptime(res_hour, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
                     - timedelta(hours=1)).strftime("%Y-%m-%dT%H")
        url = PMXT.format(hour=file_hour)
        assets = [t for m in ms for t in (m["up_token"], m["down_token"])]
        alist = "(" + ",".join("'" + a + "'" for a in assets) + ")"
        try:
            df = con.execute(f"""
                SELECT CAST(asset_id AS VARCHAR) aid, event_type, price, side,
                       best_bid, epoch(timestamp) AS ts
                FROM read_parquet('{url}')
                WHERE CAST(asset_id AS VARCHAR) IN {alist}
            """).fetchdf()
        except Exception as ex:
            print(f"  skip {file_hour}: {ex}", flush=True)
            continue
        for m in ms:
            r = m["resolve_ts"]
            for lag in LAGS:
                T = r - lag
                # favorite = token with higher best_bid at T (no look-ahead)
                bids_at_T = {}
                for tok in (m["up_token"], m["down_token"]):
                    sub = df[(df.aid == tok) & (df.ts <= T) & (df.best_bid.notna())]
                    bids_at_T[tok] = sub.best_bid.iloc[-1] if len(sub) else None
                if bids_at_T[m["up_token"]] is None or bids_at_T[m["down_token"]] is None:
                    continue
                fav = max(bids_at_T, key=lambda k: bids_at_T[k])
                if bids_at_T[fav] < 0.90:
                    continue  # no clear favorite yet
                won = fav == m["winner_token"]
                # trades on the favorite in (T, resolve]
                tr = df[(df.aid == fav) & (df.event_type == "last_trade_price")
                        & (df.ts > T) & (df.ts <= r)]
                if len(tr) == 0 and lag == 30:
                    no_late_trades += 1
                for B in BIDS:
                    key = (lag, B)
                    stats[key][3] += 1  # considered
                    filled = len(tr[tr.price <= B]) > 0
                    if filled:
                        pnl = (1.0 - B) if won else (-B)
                        stats[key][0] += 1
                        stats[key][1] += int(won)
                        stats[key][2] += pnl
            processed += 1
        print(f"  {res_hour}: {len(ms)} mkts done", flush=True)

    print(f"\n===== PHASE 2 RESULTS (markets={processed}) =====")
    print(f"markets with NO favorite-trade in final 30s: {no_late_trades}/{processed} "
          f"({100*no_late_trades/max(processed,1):.0f}%)\n")
    print(f"{'lag':>5}{'bid':>6}{'considered':>11}{'fills':>7}{'fill%':>7}"
          f"{'win%(fills)':>12}{'EV/fill':>9}{'tot P&L/$100':>13}")
    for lag in LAGS:
        for B in BIDS:
            f, w, pnl, c = stats[(lag, B)]
            if c == 0:
                continue
            frate = 100 * f / c
            wr = (100 * w / f) if f else 0
            ev = (pnl / f) if f else 0
            print(f"{lag:>5}{B:>6.2f}{c:>11}{f:>7}{frate:>6.1f}%{wr:>11.1f}%"
                  f"{ev:>+9.4f}{ev*100*f:>+13.2f}")
    print("\nNote: fills are GENEROUS (any trade printed <=B counts). Real "
          "queue position makes fill rate LOWER, not higher.")


if __name__ == "__main__":
    main()
