"""MLB garbage-time sweep - multi-day, slate-batched (the non-fluke test).

Efficiency fix: pull each day's evening pmxt hours ONCE and process ALL that
day's games from the same dataframe (games share the files), instead of per-game
pulls that re-download. Robust anchor: within a game, look at every observation
where the outcome is DECIDED (best_bid >= 0.95) and there is something to lift
(best_ask < 1.0), in the final GARBAGE window before the last such moment. No
look-ahead: favorite = higher best_bid per row; score with the true winner.

Reports taker EV by ask band across many games + a realistic strategy rule
(lift the decided favorite's asks in [0.95, 0.995)). Taker fee assumed 0
(Polymarket standard on these markets; flag if that changes).

Run: python -u phase5_mlb_slate.py <series_id> <label> <window_min> <n_dates>
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
BANDS = [(0.995, 1.0), (0.99, 0.995), (0.98, 0.99), (0.97, 0.98), (0.95, 0.97)]
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})$")


def discover(series_id: int) -> list[dict]:
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


def main() -> None:
    series_id, label, window_min, n_dates = int(sys.argv[1]), sys.argv[2], float(sys.argv[3]), int(sys.argv[4])
    con = duckdb.connect(); con.execute("INSTALL httpfs; LOAD httpfs;")
    games = discover(series_id)
    by_date = defaultdict(list)
    for g in games:
        if g["date"]:
            by_date[g["date"]].append(g)
    dates = sorted(by_date, reverse=True)[1:1 + n_dates]  # skip today (maybe partial)

    band = defaultdict(lambda: [0, 0, 0.0])
    per_game = []
    for d in dates:
        ms = by_date[d]
        cts = [g["res"] for g in ms]
        lo_h = (min(cts) - timedelta(hours=8)).replace(minute=0, second=0, microsecond=0)
        hi_h = max(cts).replace(minute=0, second=0, microsecond=0)
        n = int((hi_h - lo_h).total_seconds() // 3600) + 1
        files = [PMXT.format(hour=(lo_h + timedelta(hours=i)).strftime("%Y-%m-%dT%H")) for i in range(n)]
        fl = "[" + ",".join("'" + f + "'" for f in files) + "]"
        toks = [t for g in ms for t in (g["up"], g["down"])]
        tl = "(" + ",".join("'" + t + "'" for t in toks) + ")"
        try:
            df = con.execute(f"""
                SELECT CAST(asset_id AS VARCHAR) aid, best_bid AS bb, best_ask AS ba,
                       epoch(timestamp) AS ts
                FROM read_parquet({fl}, union_by_name=true)
                WHERE CAST(asset_id AS VARCHAR) IN {tl}
                  AND best_ask IS NOT NULL AND best_bid IS NOT NULL
            """).fetchdf()
        except Exception as ex:
            print(f"  {d}: pull failed {str(ex)[:50]}", flush=True); continue
        used = 0
        for g in ms:
            mkt = df[df.aid.isin([g["up"], g["down"]])]
            cheap = mkt[(mkt.bb >= 0.95) & (mkt.ba < 1.0)]
            if len(cheap) == 0:
                continue
            anchor = cheap.ts.max()
            w = cheap[cheap.ts >= anchor - window_min * 60].copy()
            if len(w) == 0:
                continue
            used += 1
            w["won"] = w.aid == g["winner"]
            w["ev"] = np.where(w.won, 1.0 - w.ba, -w.ba)
            for lo, hi in BANDS:
                b = w[(w.ba >= lo) & (w.ba < hi)]
                if len(b):
                    s = band[(lo, hi)]
                    s[0] += len(b); s[1] += int(b.won.sum()); s[2] += float(b.ev.sum())
            # realistic per-game: sweep the decided favorite's cheapest ask in [0.95,0.995)
            fav = w.sort_values("ts").groupby("aid").bb.last().idxmax()
            fb = w[(w.aid == fav) & (w.ba >= 0.95) & (w.ba < 0.995)]
            if len(fb):
                ask = float(fb.ba.min())
                per_game.append((g["slug"], ask, bool(fav == g["winner"])))
        print(f"  {d}: {used}/{len(ms)} games with decided cheap-ask liquidity", flush=True)

    print(f"\n===== [{label}] MLB GARBAGE-TIME SWEEP (dates={dates}) =====")
    print(f"  {'ask band':<16}{'obs':>9}{'win%':>7}{'EV/sweep':>10}{'$/100':>8}")
    for lo, hi in BANDS:
        n, wn, ev = band[(lo, hi)]
        if n:
            print(f"  [{lo:.3f},{hi:.3f}){n:>9}{100*wn/n:>6.0f}%{ev/n:>+10.4f}{100*ev/n:>+8.2f}")
    if per_game:
        wins = sum(1 for _, _, w in per_game if w)
        avg = sum(a for _, a, _ in per_game) / len(per_game)
        ev = sum((1 - a) if w else (-a) for _, a, w in per_game) / len(per_game)
        print(f"\n  STRATEGY (per game, lift decided favorite's cheapest ask in [0.95,0.995)):")
        print(f"    games={len(per_game)} fav_won={wins} ({100*wins/len(per_game):.0f}%) "
              f"avg_entry={avg:.3f} EV/game={ev:+.4f} (${ev*100:+.2f} per $100)")


if __name__ == "__main__":
    main()
