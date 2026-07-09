"""Sports endgame sweep, per-game + vectorized (the decisive EV test).

For each resolved 2-outcome game: pull ~10h of pmxt around closedTime, anchor on
the market's own LAST trade (= end of trading ~ game end, robust to batch UMA
resolution lag), take the final WINDOW minutes, and for BOTH tokens record every
best_ask observation while that token was the FAVORITE (best_bid >= 0.90, decided
by bid only - NO look-ahead). Score with the true winner. Report taker EV by
ask-price band: is lifting the near-certain winner's cheap asks +EV?

Run: python -u phase4b_sports_endgame.py <series_id> <label> <window_min> <n_games>
"""
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import duckdb
import httpx
import pandas as pd

GAMMA = "https://gamma-api.polymarket.com"
PMXT = "https://r2v2.pmxt.dev/polymarket_orderbook_{hour}.parquet"
BANDS = [(0.995, 1.0), (0.99, 0.995), (0.98, 0.99), (0.97, 0.98), (0.95, 0.97), (0.90, 0.95)]


def discover(series_id: int) -> list[dict]:
    out = []
    for off in (0, 100, 200):
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
                ct = mk.get("closedTime") or mk.get("umaEndDate")
                try:
                    res = datetime.fromisoformat(ct.replace(" ", "T").replace("Z", "+00:00"))
                except (TypeError, ValueError, AttributeError):
                    continue
                if res.tzinfo is None:
                    res = res.replace(tzinfo=timezone.utc)
                if not (datetime(2026, 4, 14, tzinfo=timezone.utc) < res < datetime.now(timezone.utc)):
                    continue
                out.append({"slug": e.get("slug"), "res": res,
                            "up": toks[0], "down": toks[1],
                            "winner": toks[0] if prices[0] == "1" else toks[1]})
        if len(evs) < 100:
            break
    return out


def main() -> None:
    series_id, label, window_min, n_games = int(sys.argv[1]), sys.argv[2], float(sys.argv[3]), int(sys.argv[4])
    con = duckdb.connect(); con.execute("INSTALL httpfs; LOAD httpfs;")
    games = sorted(discover(series_id), key=lambda m: m["res"], reverse=True)[:n_games]
    print(f"[{label}] games={len(games)} window={window_min}m", flush=True)

    band = defaultdict(lambda: [0, 0, 0.0])   # band -> [obs, wins, ev_sum]
    per_game = []                              # (slug, best cheap ask captured EV)
    used = 0
    for g in games:
        files = [PMXT.format(hour=(g["res"] - timedelta(hours=h)).strftime("%Y-%m-%dT%H"))
                 for h in range(6)]
        fl = "[" + ",".join("'" + f + "'" for f in files) + "]"
        try:
            df = con.execute(f"""
                SELECT CAST(asset_id AS VARCHAR) aid, best_bid AS bb, best_ask AS ba,
                       epoch(timestamp) AS ts
                FROM read_parquet({fl}, union_by_name=true)
                WHERE CAST(asset_id AS VARCHAR) IN ('{g['up']}','{g['down']}')
                  AND best_ask IS NOT NULL AND best_bid IS NOT NULL
            """).fetchdf()
        except Exception as ex:
            print(f"  skip {g['slug']}: {str(ex)[:45]}", flush=True); continue
        if len(df) == 0:
            continue
        last_ts = df.ts.max()
        w = df[(df.ts >= last_ts - window_min * 60) & (df.ts <= last_ts)
               & (df.bb >= 0.90) & (df.ba < 1.0)].copy()
        if len(w) == 0:
            continue
        used += 1
        w["won"] = (w.aid == g["winner"])
        import numpy as np; w["ev"] = np.where(w.won, 1.0 - w.ba, -w.ba)
        for lo, hi in BANDS:
            b = w[(w.ba >= lo) & (w.ba < hi)]
            if len(b):
                s = band[(lo, hi)]
                s[0] += len(b); s[1] += int(b.won.sum()); s[2] += float(b.ev.sum())
        # per-game: if you swept the single cheapest ask on the eventual favorite
        fav_last_bid = w.sort_values("ts").groupby("aid").bb.last()
        fav = fav_last_bid.idxmax()
        fb = w[w.aid == fav]
        if len(fb):
            cheapest = fb.loc[fb.ba.idxmin()]
            per_game.append((g["slug"], float(cheapest.ba), bool(cheapest.aid == g["winner"])))
        print(f"  {g['slug'][:34]:<34} obs={len(w)} last={int(last_ts)}", flush=True)

    print(f"\n===== [{label}] SPORTS ENDGAME by ASK BAND (games used={used}) =====")
    print(f"  {'ask band':<16}{'obs':>8}{'win%':>7}{'EV/sweep':>10}{'$/100':>8}")
    for lo, hi in BANDS:
        n, wn, ev = band[(lo, hi)]
        if n:
            print(f"  [{lo:.3f},{hi:.3f}){n:>8}{100*wn/n:>6.0f}%{ev/n:>+10.4f}{100*ev/n:>+8.2f}")
    if per_game:
        wins = sum(1 for _, _, w in per_game if w)
        avg_ask = sum(a for _, a, _ in per_game) / len(per_game)
        ev = sum((1 - a) if w else (-a) for _, a, w in per_game) / len(per_game)
        print(f"\n  PER-GAME (sweep the favorite's single cheapest ask): games={len(per_game)} "
              f"fav_won={wins}/{len(per_game)} avg_ask={avg_ask:.3f} EV/game={ev:+.4f} (${ev*100:+.2f}/$100)")


if __name__ == "__main__":
    main()
