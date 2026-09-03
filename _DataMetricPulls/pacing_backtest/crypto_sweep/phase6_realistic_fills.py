"""MLB sweep - REALISTIC backtest: real executed trades + real sizes + real fees.

Answers "backtest against real fills and trades" + "model the fees". Instead of
assuming we can lift whatever ask shows, we use the ACTUAL trades that printed
(pmxt last_trade_price events) on a DECIDED favorite (best_bid >= 0.95, no
look-ahead) at cheap prices - i.e. real sweeps that really happened, with real
sizes. We "become" the taker buyer of those cheap fills and hold to resolution:

  cost   = price * size
  fee    = 0.05 * price * (1 - price) * size     (Polymarket sports taker fee,
           makers free; verified vs docs: 100sh @0.50 = $1.25)
  payout = size * 1.0 if the favorite won else 0
  pnl    = payout - cost - fee

Reports net ROI by ask-price band + a per-game view. This bounds the REAL
addressable edge (we would compete for these fills, so this is an upper bound on
capturable volume, but priced with real fees + real trade sizes).

Run: python -u phase6_realistic_fills.py <series_id> <label> <n_dates> [max_price]
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
FEE_RATE = 0.05                       # sports taker coefficient
BANDS = [(0.95, 0.97), (0.97, 0.98), (0.98, 0.99), (0.99, 0.995), (0.995, 1.0)]
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})$")


def fee(price: float, size: float) -> float:
    return FEE_RATE * price * (1.0 - price) * size


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
    series_id, label, n_dates = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])
    max_price = float(sys.argv[4]) if len(sys.argv) > 4 else 0.98
    con = duckdb.connect(); con.execute("INSTALL httpfs; LOAD httpfs;")
    games = discover(series_id)
    by_date = defaultdict(list)
    for g in games:
        if g["date"]:
            by_date[g["date"]].append(g)
    dates = sorted(by_date, reverse=True)[1:1 + n_dates]

    band = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0])  # [n_fills, shares, cost, fee, payout]
    per_game = defaultdict(lambda: [0.0, 0.0, 0.0])       # slug -> [cost, fee, payout]
    maker = [[0, 0.0, 0.0, 0.0, 0.0]]                     # taker-SELL fills, maker fee=0
    for d in dates:
        ms = by_date[d]
        cts = [g["res"] for g in ms]
        lo_h = (min(cts) - timedelta(hours=8)).replace(minute=0, second=0, microsecond=0)
        hi_h = max(cts).replace(minute=0, second=0, microsecond=0)
        nh = int((hi_h - lo_h).total_seconds() // 3600) + 1
        files = [PMXT.format(hour=(lo_h + timedelta(hours=i)).strftime("%Y-%m-%dT%H")) for i in range(nh)]
        fl = "[" + ",".join("'" + f + "'" for f in files) + "]"
        toks = [t for g in ms for t in (g["up"], g["down"])]
        tl = "(" + ",".join("'" + t + "'" for t in toks) + ")"
        try:
            df = con.execute(f"""
                SELECT CAST(asset_id AS VARCHAR) aid, event_type, price, size, side,
                       best_bid AS bb, epoch(timestamp) AS ts
                FROM read_parquet({fl}, union_by_name=true)
                WHERE CAST(asset_id AS VARCHAR) IN {tl}
            """).fetchdf()
        except Exception as ex:
            print(f"  {d}: pull failed {str(ex)[:50]}", flush=True); continue
        used = 0
        for g in ms:
            mkt = df[df.aid.isin([g["up"], g["down"]])].sort_values("ts")
            # forward-fill best_bid per token so each trade knows the decided state
            trades = mkt[(mkt.event_type == "last_trade_price") & (mkt.price <= max_price)
                         & (mkt.price >= 0.95) & (mkt.size > 0)].copy()
            if len(trades) == 0:
                continue
            # decided favorite: the token's own best_bid at/just-before the trade >= 0.95
            books = mkt[mkt.bb.notna()][["aid", "ts", "bb"]]
            trades["bb_at"] = np.nan
            for tok in (g["up"], g["down"]):
                tb = books[books.aid == tok]
                tt = trades[trades.aid == tok]
                if len(tb) == 0 or len(tt) == 0:
                    continue
                idx = np.searchsorted(tb.ts.values, tt.ts.values, side="right") - 1
                vals = np.where(idx >= 0, tb.bb.values[np.clip(idx, 0, len(tb) - 1)], np.nan)
                trades.loc[tt.index, "bb_at"] = vals
            sweeps = trades[trades.bb_at >= 0.95]
            if len(sweeps) == 0:
                continue
            used += 1
            for _, t in sweeps.iterrows():
                won = t.aid == g["winner"]
                c = t.price * t.size; f = fee(t.price, t.size); pay = t.size if won else 0.0
                for lo, hi in BANDS:
                    if lo <= t.price < hi:
                        s = band[(lo, hi)]
                        s[0] += 1; s[1] += t.size; s[2] += c; s[3] += f; s[4] += pay
                        break
                pg = per_game[g["slug"]]
                pg[0] += c; pg[1] += f; pg[2] += pay
                # MAKER version (Sir's Q): only trades where the taker SOLD into a
                # bid are capturable by our resting post-only bid; maker pays $0 fee.
                if str(t.side).upper() == "SELL":
                    m = maker[0]; m[0] += 1; m[1] += t.size; m[2] += c; m[4] += pay
        print(f"  {d}: {used}/{len(ms)} games had real cheap sweeps", flush=True)

    print(f"\n===== [{label}] REALISTIC SWEEP (real trades + sizes + sports fee) dates={dates} =====")
    print(f"  buy fills where a real trade printed <= {max_price} on a decided favorite (bid>=0.95)")
    print(f"  {'band':<15}{'fills':>7}{'shares':>10}{'invested$':>11}{'fees$':>8}{'net P&L$':>10}{'ROI%':>7}")
    tot = [0, 0.0, 0.0, 0.0, 0.0]
    for lo, hi in BANDS:
        n, sh, c, f, pay = band[(lo, hi)]
        if not n:
            continue
        pnl = pay - c - f
        roi = 100 * pnl / c if c else 0
        print(f"  [{lo:.3f},{hi:.3f}){n:>7}{sh:>10.0f}{c:>11.0f}{f:>8.1f}{pnl:>+10.1f}{roi:>+7.2f}")
        for i, v in enumerate((n, sh, c, f, pay)):
            tot[i] += v
    if tot[2]:
        pnl = tot[4] - tot[2] - tot[3]
        print(f"  {'TOTAL':<15}{tot[0]:>7}{tot[1]:>10.0f}{tot[2]:>11.0f}{tot[3]:>8.1f}"
              f"{pnl:>+10.1f}{100*pnl/tot[2]:>+7.2f}")
    # MAKER vs TAKER comparison (Sir's question)
    mn, msh, mc, _, mpay = maker[0]
    if tot[2]:
        tk_pnl = tot[4] - tot[2] - tot[3]
        print(f"\n  TAKER (lift cheap asks, pay fee): fills={tot[0]} invested=${tot[2]:.0f} "
              f"fees=${tot[3]:.1f} net=${tk_pnl:+.0f} ROI={100*tk_pnl/tot[2]:+.2f}%")
    if mc:
        mk_pnl = mpay - mc  # maker fee = 0
        print(f"  MAKER (rest bid, seller crosses in, $0 fee): fills={mn} invested=${mc:.0f} "
              f"fees=$0 net=${mk_pnl:+.0f} ROI={100*mk_pnl/mc:+.2f}%  "
              f"[capturable volume = {100*mc/tot[2]:.0f}% of taker's]")

    # per-game independence check
    pg_pnls = [(pay - c - f) for c, f, pay in per_game.values()]
    if pg_pnls:
        wins = sum(1 for p in pg_pnls if p > 0)
        print(f"\n  PER-GAME: games={len(pg_pnls)} profitable={wins} ({100*wins/len(pg_pnls):.0f}%) "
              f"avg net P&L/game=${np.mean(pg_pnls):+.2f} median=${np.median(pg_pnls):+.2f} "
              f"worst=${min(pg_pnls):+.2f}")


if __name__ == "__main__":
    main()
