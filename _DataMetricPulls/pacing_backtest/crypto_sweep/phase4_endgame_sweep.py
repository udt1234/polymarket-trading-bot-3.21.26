"""Endgame sweep, banded: is there ANY market + ask-price band where lifting the
near-certain winner's cheap asks is reliably +EV?

Anchors on the REAL resolution time (closedTime for sports, endDate for crypto/
weather). Over the final WINDOW minutes before resolution, for the eventual
WINNER token, collects every distinct best_ask observation while the winner was
already the favorite (best_bid >= 0.90 -> the outcome is ~decided). Buckets each
by ask-price band and reports the taker EV of lifting at that ask:
  EV = (1.0 - ask) if winner (always, since we condition on the winner token)
  ... but we must NOT condition fills on the outcome. So instead: at each obs we
  define favorite by best_bid (no look-ahead) and score with the true winner.

Run: python -u phase4_endgame_sweep.py <series_id> <label> <window_min> [n_markets]
"""
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import duckdb
import httpx

GAMMA = "https://gamma-api.polymarket.com"
PMXT = "https://r2v2.pmxt.dev/polymarket_orderbook_{hour}.parquet"
BANDS = [(0.995, 1.0), (0.99, 0.995), (0.98, 0.99), (0.95, 0.98), (0.90, 0.95), (0.0, 0.90)]


def discover(series_id: int) -> list[dict]:
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
                if len(toks) != 2 or prices[0] not in ("0", "1") or prices[0] == prices[1]:
                    continue
                ct = mk.get("closedTime") or mk.get("umaEndDate") or e.get("endDate")
                try:
                    res = datetime.fromisoformat(ct.replace("Z", "+00:00").replace(" ", "T"))
                except (TypeError, ValueError, AttributeError):
                    continue
                if res.tzinfo is None:
                    res = res.replace(tzinfo=timezone.utc)
                if res < datetime(2026, 4, 14, tzinfo=timezone.utc) or res > datetime.now(timezone.utc):
                    continue
                out.append({"slug": e.get("slug"), "res": res, "res_ts": res.timestamp(),
                            "up_token": toks[0], "down_token": toks[1],
                            "winner_token": toks[0] if prices[0] == "1" else toks[1]})
        if len(evs) < 100:
            break
    return out


def main() -> None:
    series_id, label, window_min = int(sys.argv[1]), sys.argv[2], float(sys.argv[3])
    n_markets = int(sys.argv[4]) if len(sys.argv) > 4 else 40
    con = duckdb.connect(); con.execute("INSTALL httpfs; LOAD httpfs;")
    markets = sorted(discover(series_id), key=lambda m: m["res_ts"], reverse=True)[:n_markets]
    by_hour = defaultdict(list)
    for m in markets:
        by_hour[m["res"].strftime("%Y-%m-%dT%H")].append(m)
    print(f"[{label}] markets={len(markets)} hours={len(by_hour)} window={window_min}m", flush=True)

    band_stats = defaultdict(lambda: [0, 0, 0.0])  # band -> [n, wins, ev_sum]
    swept_markets = 0
    n_hours = max(3, int(window_min // 60) + 6)  # cover batch-delayed resolution
    for res_hour, ms in sorted(by_hour.items(), reverse=True):
        base = datetime.strptime(res_hour, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
        files = [PMXT.format(hour=(base - timedelta(hours=h)).strftime("%Y-%m-%dT%H"))
                 for h in range(n_hours)]
        flist = "[" + ",".join("'" + f + "'" for f in files) + "]"
        assets = [t for m in ms for t in (m["up_token"], m["down_token"])]
        alist = "(" + ",".join("'" + a + "'" for a in assets) + ")"
        try:
            df = con.execute(f"""
                SELECT CAST(asset_id AS VARCHAR) aid, best_bid, best_ask,
                       epoch(timestamp) AS ts
                FROM read_parquet({flist}, union_by_name=true)
                WHERE CAST(asset_id AS VARCHAR) IN {alist} AND best_ask IS NOT NULL
            """).fetchdf()
        except Exception as ex:
            print(f"  skip {res_hour}: {str(ex)[:50]}", flush=True); continue
        for m in ms:
            mkt = df[df.aid.isin([m["up_token"], m["down_token"]])]
            if len(mkt) == 0:
                continue
            # anchor on the market's OWN last trade (= end of trading ~ game end),
            # not the batch UMA closedTime which lags by hours.
            last_ts = mkt.ts.max()
            lo = last_ts - window_min * 60
            win = mkt[(mkt.ts >= lo) & (mkt.ts <= last_ts)]
            got = False
            for tok in (m["up_token"], m["down_token"]):
                sub = win[win.aid == tok]
                if len(sub) < 2:
                    continue
                # favorite decided by best_bid (no look-ahead per row)
                for _, row in sub.iterrows():
                    bb, ba = row.best_bid, row.best_ask
                    if bb is None or ba is None or bb < 0.90 or ba >= 1.0:
                        continue
                    won = tok == m["winner_token"]
                    for lohi in BANDS:
                        if lohi[0] <= ba < lohi[1]:
                            s = band_stats[lohi]
                            s[0] += 1; s[1] += int(won)
                            s[2] += (1.0 - ba) if won else (-ba)
                            got = True
                            break
            swept_markets += int(got)
        print(f"  {res_hour}: {len(ms)} done", flush=True)

    print(f"\n===== [{label}] ENDGAME ASK-SWEEP by ASK BAND (markets w/ obs={swept_markets}) =====")
    print(f"  NOTE: one market emits many ask observations; treat n as obs not trades.")
    print(f"  {'ask band':<16}{'obs':>7}{'win%':>7}{'EV/sweep':>10}{'$/100':>8}")
    for lohi in BANDS:
        n, w, ev = band_stats[lohi]
        if not n:
            continue
        print(f"  [{lohi[0]:.3f},{lohi[1]:.3f}){n:>7}{100*w/n:>6.0f}%"
              f"{ev/n:>+10.4f}{100*ev/n:>+8.2f}")


if __name__ == "__main__":
    main()
