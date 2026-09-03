"""Sweeper edge, done RIGHT: TAKER lifting cheap asks in the final seconds.

Sir's actual ask (corrected): the sweeper bots come in at the very last few
SECONDS and TAKE (lift) resting asks that sit BELOW fair on the near-certain
winner, capturing (1.0 - ask). A taker always fills (up to ask size), so the
"no sellers" problem of the maker version does not apply. The only questions:
  (a) how often is there an ask BELOW 1.0 on the favorite in the final 1-3s?
  (b) when you lift it, does the favorite actually win? (EV after the capture)

Generalized across ANY 2-outcome daily/hourly series (crypto, sports, weather).
Favorite = the token with the higher best_bid at decision time T (no look-ahead);
winner from Gamma outcomePrices. At T = resolve - LAG, read the favorite's
best_ask from the tick stream (last event <= T) and the ask ladder depth.

Sweep opportunity = best_ask <= CEIL (something below par to grab). Taker EV per
sweep = (1.0 - ask) if favorite won else (-ask). Reports the opportunity rate +
EV by market type, so we can see WHICH markets leave cheap asks late.

Run: python -u phase3_ask_sweep.py <series_id> <label> [hours_back]
"""
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import duckdb
import httpx

GAMMA = "https://gamma-api.polymarket.com"
PMXT = "https://r2v2.pmxt.dev/polymarket_orderbook_{hour}.parquet"
LAGS = [1, 3, 5, 30]


def discover(series_id: int, limit: int = 200) -> list[dict]:
    out = []
    for off in (0, 100):
        r = httpx.get(f"{GAMMA}/events", params={
            "series_id": str(series_id), "limit": 100, "offset": off,
            "closed": "true", "order": "endDate", "ascending": "false"}, timeout=40)
        evs = r.json() if r.status_code == 200 else []
        for e in evs:
            for mk in (e.get("markets") or []):
                try:
                    toks = json.loads(mk.get("clobTokenIds") or "[]")
                    prices = json.loads(mk.get("outcomePrices") or "[]")
                except (TypeError, ValueError):
                    continue
                if len(toks) != 2 or len(prices) != 2:
                    continue
                if prices[0] not in ("0", "1") or prices[0] == prices[1]:
                    continue
                end = datetime.fromisoformat(e["endDate"].replace("Z", "+00:00"))
                if end < datetime(2026, 4, 14, tzinfo=timezone.utc):
                    continue  # pmxt coverage starts ~Apr 13
                out.append({"slug": e.get("slug"), "resolve": end,
                            "resolve_ts": int(end.timestamp()),
                            "up_token": toks[0], "down_token": toks[1],
                            "winner_token": toks[0] if prices[0] == "1" else toks[1]})
        if len(evs) < 100:
            break
    return out


def main() -> None:
    series_id, label = int(sys.argv[1]), sys.argv[2]
    hours_back = int(sys.argv[3]) if len(sys.argv) > 3 else 30
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    markets = discover(series_id)
    markets.sort(key=lambda m: m["resolve_ts"], reverse=True)
    hours = sorted({m["resolve"].strftime("%Y-%m-%dT%H") for m in markets}, reverse=True)[:hours_back]
    hset = set(hours)
    markets = [m for m in markets if m["resolve"].strftime("%Y-%m-%dT%H") in hset]
    by_hour = defaultdict(list)
    for m in markets:
        by_hour[m["resolve"].strftime("%Y-%m-%dT%H")].append(m)
    print(f"[{label}] markets={len(markets)} across {len(by_hour)} hours", flush=True)

    # stats[lag] = list of (best_ask, won, ask_size)
    obs = defaultdict(list)
    for res_hour, ms in sorted(by_hour.items(), reverse=True):
        file_hour = (datetime.strptime(res_hour, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
                     - timedelta(hours=1)).strftime("%Y-%m-%dT%H")
        url = PMXT.format(hour=file_hour)
        assets = [t for m in ms for t in (m["up_token"], m["down_token"])]
        alist = "(" + ",".join("'" + a + "'" for a in assets) + ")"
        try:
            df = con.execute(f"""
                SELECT CAST(asset_id AS VARCHAR) aid, best_bid, best_ask, asks,
                       epoch(timestamp) AS ts
                FROM read_parquet('{url}')
                WHERE CAST(asset_id AS VARCHAR) IN {alist}
                  AND best_ask IS NOT NULL
            """).fetchdf()
        except Exception as ex:
            print(f"  skip {file_hour}: {str(ex)[:60]}", flush=True)
            continue
        for m in ms:
            r = m["resolve_ts"]
            for lag in LAGS:
                T = r - lag
                bb, ba = {}, {}
                for tok in (m["up_token"], m["down_token"]):
                    sub = df[(df.aid == tok) & (df.ts <= T)]
                    if len(sub):
                        bb[tok] = sub.best_bid.iloc[-1]
                        ba[tok] = sub.best_ask.iloc[-1]
                if len(bb) < 2 or any(v is None for v in bb.values()):
                    continue
                fav = max(bb, key=lambda k: bb[k])
                if bb[fav] is None or bb[fav] < 0.90:
                    continue
                won = fav == m["winner_token"]
                obs[lag].append((float(ba[fav]), won))
        print(f"  {res_hour}: {len(ms)} done", flush=True)

    print(f"\n===== [{label}] ASK-SWEEP OPPORTUNITY =====")
    print(f"{'lag':>4}{'n':>5}{'ask<1.0':>9}{'ask<=.99':>10}{'ask<=.97':>10}"
          f"{'avg cap*':>9}{'win%':>7}{'EV/sweep*':>11}")
    for lag in LAGS:
        o = obs[lag]
        if not o:
            continue
        n = len(o)
        below1 = sum(1 for a, w in o if a < 1.0)
        below99 = sum(1 for a, w in o if a <= 0.99)
        below97 = sum(1 for a, w in o if a <= 0.97)
        # sweep the ask whenever it's below 1.0 (something to capture)
        sweeps = [(a, w) for a, w in o if a < 1.0]
        if sweeps:
            cap = sum((1.0 - a) for a, w in sweeps) / len(sweeps)
            wr = sum(w for a, w in sweeps) / len(sweeps)
            ev = sum((1.0 - a) if w else (-a) for a, w in sweeps) / len(sweeps)
        else:
            cap = wr = ev = 0.0
        print(f"{lag:>4}{n:>5}{100*below1/n:>8.0f}%{100*below99/n:>9.0f}%"
              f"{100*below97/n:>9.0f}%{cap:>+9.4f}{100*wr:>6.0f}%{ev:>+11.4f}")
    print("* over sweeps where best_ask<1.0. EV/sweep in $ per $1 (x100 = per $100).")


if __name__ == "__main__":
    main()
