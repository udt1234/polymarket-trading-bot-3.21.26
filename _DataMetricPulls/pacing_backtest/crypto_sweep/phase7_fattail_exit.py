"""Fat-tail investigation: which games collapsed, what the price path looked like,
and how much a STOP-LOSS (selling out as the favorite fades) would have saved.

The +EV backtests HELD TO RESOLUTION (buy the decided favorite's cheap shares,
collect $1 or $0). The losses come from the ~1-3% of "decided" favorites that
COLLAPSE (a comeback). Sir's question: if the other team starts scoring, the
price drops gradually inning by inning - why hold to $0 instead of selling out?

This finds each collapse game (a token that was a decided favorite, bid>=0.95,
but LOST), reconstructs the favorite's best_bid path, our cheap entries, and
compares HOLD-TO-RESOLUTION vs a STOP-LOSS that sells (taker at the bid) the
first time the bid falls below S. Shows collapse SHAPE (gradual => sellable).

Run: python -u phase7_fattail_exit.py <series_id> <label> <n_dates>
"""
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import duckdb
import httpx
import numpy as np

GAMMA = "https://gamma-api.polymarket.com"
PMXT = "https://r2v2.pmxt.dev/polymarket_orderbook_{hour}.parquet"
FEE_RATE = 0.05
STOPS = [0.90, 0.85, 0.80]
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})$")


def fee(p, s):
    return FEE_RATE * p * (1 - p) * s


def discover(series_id):
    out = []
    for off in (0, 100, 200, 300):
        r = httpx.get(f"{GAMMA}/events", params={
            "series_id": str(series_id), "limit": 100, "offset": off,
            "closed": "true", "order": "endDate", "ascending": "false"}, timeout=40)
        evs = r.json() if r.status_code == 200 else []
        for e in evs:
            mday = DATE_RE.search(e.get("slug") or "")
            for mk in (e.get("markets") or []):
                try:
                    toks = json.loads(mk.get("clobTokenIds") or "[]")
                    prices = json.loads(mk.get("outcomePrices") or "[]")
                except (TypeError, ValueError):
                    continue
                if len(toks) != 2 or prices[0] not in ("0", "1") or prices[0] == prices[1]:
                    continue
                ct = mk.get("closedTime") or mk.get("umaEndDate")
                try:
                    res = datetime.fromisoformat(ct.replace(" ", "T").replace("Z", "+00:00"))
                except (TypeError, ValueError, AttributeError):
                    continue
                if res.tzinfo is None:
                    res = res.replace(tzinfo=timezone.utc)
                if not (datetime(2026, 4, 14, tzinfo=timezone.utc) < res < datetime.now(timezone.utc)):
                    continue
                out.append({"slug": e.get("slug"), "date": mday.group(1) if mday else None,
                            "res": res, "up": toks[0], "down": toks[1],
                            "winner": toks[0] if prices[0] == "1" else toks[1]})
        if len(evs) < 100:
            break
    return out


def main():
    series_id, label, n_dates = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])
    con = duckdb.connect(); con.execute("INSTALL httpfs; LOAD httpfs;")
    games = discover(series_id)
    by_date = defaultdict(list)
    for g in games:
        if g["date"]:
            by_date[g["date"]].append(g)
    dates = sorted(by_date, reverse=True)[1:1 + n_dates]

    collapses = []
    hold_tot = defaultdict(float)   # date -> hold pnl
    stop_tot = {s: defaultdict(float) for s in STOPS}
    for d in dates:
        ms = by_date[d]
        cts = [g["res"] for g in ms]
        lo_h = (min(cts) - timedelta(hours=8)).replace(minute=0, second=0, microsecond=0)
        nh = int((max(cts).replace(minute=0, second=0, microsecond=0) - lo_h).total_seconds() // 3600) + 1
        files = [PMXT.format(hour=(lo_h + timedelta(hours=i)).strftime("%Y-%m-%dT%H")) for i in range(nh)]
        fl = "[" + ",".join("'" + f + "'" for f in files) + "]"
        toks = [t for g in ms for t in (g["up"], g["down"])]
        tl = "(" + ",".join("'" + t + "'" for t in toks) + ")"
        try:
            df = con.execute(f"""
                SELECT CAST(asset_id AS VARCHAR) aid, event_type, price, size, best_bid AS bb,
                       epoch(timestamp) AS ts
                FROM read_parquet({fl}, union_by_name=true)
                WHERE CAST(asset_id AS VARCHAR) IN {tl}
            """).fetchdf()
        except Exception as ex:
            print(f"  {d}: pull failed {str(ex)[:50]}", flush=True); continue
        for g in ms:
            for tok in (g["up"], g["down"]):
                sub = df[df.aid == tok].sort_values("ts")
                bidrows = sub[sub.bb.notna()]
                if len(bidrows) == 0 or bidrows.bb.max() < 0.95:
                    continue  # never a decided favorite
                won = tok == g["winner"]
                # our entries: real cheap trades on this token while it was decided
                books = bidrows[["ts", "bb"]].values
                trades = sub[(sub.event_type == "last_trade_price") & (sub.price >= 0.95)
                             & (sub.price <= 0.98) & (sub.size > 0)]
                entries = []
                for _, t in trades.iterrows():
                    j = np.searchsorted(books[:, 0], t.ts, side="right") - 1
                    if j >= 0 and books[j, 1] >= 0.95:
                        entries.append((t.ts, float(t.price), float(t.size)))
                if not entries:
                    continue
                cost = sum(p * s for _, p, s in entries)
                fees_in = sum(fee(p, s) for _, p, s in entries)
                shares = sum(s for _, _, s in entries)
                # HOLD to resolution
                hold_pnl = (shares if won else 0.0) - cost - fees_in
                hold_tot[d] += hold_pnl
                # STOP-LOSS: sell all at the bid the first time bb < S (taker sell)
                for S in STOPS:
                    stop_hit = bidrows[(bidrows.ts > entries[0][0]) & (bidrows.bb < S)]
                    if len(stop_hit):
                        exitp = float(stop_hit.iloc[0].bb)
                        pnl = shares * exitp - cost - fees_in - fee(exitp, shares)
                    else:
                        pnl = (shares if won else 0.0) - cost - fees_in
                    stop_tot[S][d] += pnl
                if not won:  # a collapse
                    minbid_after = bidrows[bidrows.ts > entries[0][0]].bb.min() if len(bidrows[bidrows.ts > entries[0][0]]) else 1.0
                    collapses.append({"slug": g["slug"], "shares": shares, "cost": cost,
                                      "hold_pnl": hold_pnl, "min_bid_after": minbid_after,
                                      "peak_bid": float(bidrows.bb.max()),
                                      "entry0": entries[0][1]})
        print(f"  {d} done", flush=True)

    print(f"\n===== COLLAPSE GAMES (decided favorite that LOST), dates={dates} =====")
    collapses.sort(key=lambda x: x["hold_pnl"])
    for c in collapses[:12]:
        print(f"  {c['slug']:<32} bought~{c['shares']:.0f}sh cost=${c['cost']:.0f} "
              f"peak_bid={c['peak_bid']:.3f} -> min_bid_after={c['min_bid_after']:.3f} "
              f"HOLD P&L=${c['hold_pnl']:+.1f}")
    print(f"\n  total collapse games: {len(collapses)}")

    print(f"\n===== HOLD-TO-RESOLUTION vs STOP-LOSS (net P&L across all decided-fav sweeps) =====")
    h = sum(hold_tot.values())
    print(f"  HOLD to resolution:        ${h:+.1f}")
    for S in STOPS:
        st = sum(stop_tot[S].values())
        print(f"  STOP-LOSS at bid<{S:.2f}:      ${st:+.1f}  (delta ${st-h:+.1f})")


if __name__ == "__main__":
    main()
