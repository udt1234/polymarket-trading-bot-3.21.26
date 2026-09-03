"""Phase 8 - MLB garbage-time sweep, HONEST per-GAME re-validation on LOCAL data.

Re-scores the phase6 "buy the cheap sweep on a decided favorite and hold to
resolution" idea, but with the accounting fixed so a single lucky/large fill
cannot flatter the headline:

  * PER-GAME UNIT   - each game contributes exactly ONE observation:
                      pnl_game = sum over its qualifying sweep fills of (payout - cost - fee).
                      Games with zero qualifying fills are dropped (stated as n_games vs total).
  * TAKER FEE       - 0.05 * p * (1-p) * size applied to EVERY fill (phase5's fee=0 was a bug).
  * ANTI-LOOK-AHEAD - the "decided favorite" test uses the token's OWN best_bid at/just-before
                      the trade (searchsorted side='right' - 1, require a real prior book).
                      The Gamma winner is used ONLY to score payout, never to pick the favorite,
                      qualify a trade, or set the price cap.
  * BOOTSTRAP CI    - 10,000 resamples of the per-game pnl array; prints 5th/50th/95th pct of the
                      bootstrap MEAN.

LOCAL DATA: reads a one-time bounded pmxt cache at _DataMetricPulls/pmxt_mlb_cache/
(polymarket_orderbook_{hour}.parquet, RAW-derived phase6 columns, filtered to the MLB
slate tokens). If a needed hour is missing it is pulled ONCE from the remote pmxt archive
and written to the cache; every later run reads local only (no network).

Run: python -u phase8_local_pergame.py [n_dates=20] [max_price=0.98] [series_id=3]
"""
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import httpx
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot")
CACHE = ROOT / "_DataMetricPulls" / "pmxt_mlb_cache"
CACHE.mkdir(parents=True, exist_ok=True)

GAMMA = "https://gamma-api.polymarket.com"
PMXT = "https://r2v2.pmxt.dev/polymarket_orderbook_{hour}.parquet"
FEE_RATE = 0.05                        # Polymarket sports TAKER coefficient (makers $0)
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})$")
CACHE_COLS = "aid, event_type, price, size, side, bb, ts"


def fee(price: float, size: float) -> float:
    return FEE_RATE * price * (1.0 - price) * size


def discover(series_id: int) -> list[dict]:
    """Gamma /events -> resolved 0/1 binary MLB moneylines with an official winner."""
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


def hours_for_date(ms: list[dict]) -> list[str]:
    """phase6 window: min(res)-8h .. max(res), hour-floored, inclusive."""
    cts = [g["res"] for g in ms]
    lo_h = (min(cts) - timedelta(hours=8)).replace(minute=0, second=0, microsecond=0)
    hi_h = max(cts).replace(minute=0, second=0, microsecond=0)
    nh = int((hi_h - lo_h).total_seconds() // 3600) + 1
    return [(lo_h + timedelta(hours=i)).strftime("%Y-%m-%dT%H") for i in range(nh)]


def _valid(p: Path) -> bool:
    if not p.exists():
        return False
    try:
        duckdb.connect().execute(
            f"SELECT COUNT(*) FROM read_parquet('{str(p).replace(chr(92), '/')}')").fetchone()
        return True
    except Exception:
        p.unlink(missing_ok=True)   # truncated/corrupt -> drop so it re-pulls
        return False


def ensure_cache(con, needed: dict) -> None:
    """needed: hour_str -> set(tokens). Pull+write each missing/corrupt hour ONCE (filtered)."""
    todo = [h for h in sorted(needed) if not _valid(CACHE / f"polymarket_orderbook_{h}.parquet")]
    print(f"cache: {len(needed)} hours needed, {len(needed) - len(todo)} already local, "
          f"{len(todo)} to pull", flush=True)
    for i, h in enumerate(todo):
        toks = needed[h]
        tl = "(" + ",".join("'" + t + "'" for t in toks) + ")"
        url = PMXT.format(hour=h)
        outp = CACHE / f"polymarket_orderbook_{h}.parquet"
        try:
            con.execute(f"""
                COPY (
                    SELECT CAST(asset_id AS VARCHAR) aid, event_type, price, size, side,
                           best_bid AS bb, epoch(timestamp) AS ts
                    FROM read_parquet('{url}', union_by_name=true)
                    WHERE CAST(asset_id AS VARCHAR) IN {tl}
                ) TO '{str(outp).replace(chr(92), "/")}' (FORMAT parquet)
            """)
            n = con.execute(f"SELECT COUNT(*) FROM read_parquet('{str(outp).replace(chr(92), '/')}')").fetchone()[0]
            print(f"  [{i+1}/{len(todo)}] {h}: cached {n:,} rows", flush=True)
        except Exception as ex:
            # 404 / missing hour: write nothing, mark handled by leaving no file (skipped on read)
            print(f"  [{i+1}/{len(todo)}] {h}: pull failed ({str(ex)[:60]})", flush=True)


def read_local(con, hours: list[str], tokens: list[str]):
    """Read cached hours for a date's tokens; return sorted DataFrame (or None)."""
    files = [str(CACHE / f"polymarket_orderbook_{h}.parquet").replace(chr(92), "/")
             for h in hours if (CACHE / f"polymarket_orderbook_{h}.parquet").exists()]
    if not files:
        return None
    fl = "[" + ",".join("'" + f + "'" for f in files) + "]"
    tl = "(" + ",".join("'" + t + "'" for t in tokens) + ")"
    return con.execute(f"""
        SELECT aid, event_type, price, size, side, bb, ts
        FROM read_parquet({fl}, union_by_name=true)
        WHERE aid IN {tl}
    """).fetchdf()


def token_pnl(tok_df, is_winner: bool, max_price: float):
    """Per-token contribution to a game's pnl using phase6 anti-look-ahead logic.

    tok_df: rows for ONE token (aid), any order. Returns (cost, fee, pay, n_fills).
    """
    d = tok_df.sort_values("ts")
    ts = d["ts"].values
    price = d["price"].values
    size = d["size"].values
    bb = d["bb"].values
    et = d["event_type"].values
    is_trade = (et == "last_trade_price") & (price >= 0.95) & (price <= max_price) & (size > 0)
    has_book = ~np.isnan(bb)
    if not is_trade.any() or not has_book.any():
        return 0.0, 0.0, 0.0, 0
    book_ts = ts[has_book]
    book_bb = bb[has_book]
    tr_idx = np.nonzero(is_trade)[0]
    tr_ts = ts[tr_idx]
    # last book strictly at/before each trade ts (no look-ahead)
    j = np.searchsorted(book_ts, tr_ts, side="right") - 1
    bb_at = np.where(j >= 0, book_bb[np.clip(j, 0, len(book_bb) - 1)], np.nan)
    keep = bb_at >= 0.95
    if not keep.any():
        return 0.0, 0.0, 0.0, 0
    p = price[tr_idx][keep]
    s = size[tr_idx][keep]
    cost = float((p * s).sum())
    fee_sum = float((FEE_RATE * p * (1.0 - p) * s).sum())
    pay = float(s.sum()) if is_winner else 0.0
    return cost, fee_sum, pay, int(keep.sum())


def game_pnl(up_df, down_df, g: dict, max_price: float):
    """phase6 per-game accounting -> (pnl, invested, n_fills) or None if no qualifying sweep."""
    cost = fee_sum = pay = 0.0
    nf = 0
    for tok, tdf in ((g["up"], up_df), (g["down"], down_df)):
        if tdf is None or len(tdf) == 0:
            continue
        c, f, pa, n = token_pnl(tdf, tok == g["winner"], max_price)  # winner ONLY sets pay
        cost += c; fee_sum += f; pay += pa; nf += n
    if nf == 0:
        return None
    return (pay - cost - fee_sum, cost, nf)


def bootstrap_ci(pnls: np.ndarray, n_boot: int = 10000, seed: int = 42):
    rng = np.random.default_rng(seed)
    n = len(pnls)
    means = pnls[rng.integers(0, n, size=(n_boot, n))].mean(axis=1)
    return np.percentile(means, [5, 50, 95])


def main() -> None:
    n_dates = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    max_price = float(sys.argv[2]) if len(sys.argv) > 2 else 0.98
    series_id = int(sys.argv[3]) if len(sys.argv) > 3 else 3

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")

    games = discover(series_id)
    by_date = defaultdict(list)
    for g in games:
        if g["date"]:
            by_date[g["date"]].append(g)
    dates = sorted(by_date, reverse=True)[1:1 + n_dates]  # drop newest (maybe partial)
    total_games = sum(len(by_date[d]) for d in dates)
    print(f"discovered {len(games)} resolved MLB moneylines across {len(by_date)} dates; "
          f"backtesting {len(dates)} dates ({total_games} games): {dates[-1]}..{dates[0]}", flush=True)

    # one-time bounded cache: hour -> union of that hour's slate tokens
    needed = defaultdict(set)
    for d in dates:
        toks = [t for g in by_date[d] for t in (g["up"], g["down"])]
        for h in hours_for_date(by_date[d]):
            needed[h].update(toks)
    ensure_cache(con, needed)

    pg_pnls, pg_invested, pg_fills = [], [], []
    for d in dates:
        ms = by_date[d]
        tokens = [t for g in ms for t in (g["up"], g["down"])]
        df = read_local(con, hours_for_date(ms), tokens)
        if df is None or len(df) == 0:
            print(f"  {d}: no local rows (hours 404/uncached) - skipped", flush=True)
            continue
        groups = {aid: gdf for aid, gdf in df.groupby("aid", sort=False)}  # O(1) per-game lookup
        used = 0
        for g in ms:
            res = game_pnl(groups.get(g["up"]), groups.get(g["down"]), g, max_price)
            if res is None:
                continue
            pnl, inv, nf = res
            pg_pnls.append(pnl); pg_invested.append(inv); pg_fills.append(nf)
            used += 1
        print(f"  {d}: {used}/{len(ms)} games had a qualifying sweep", flush=True)

    n_games = len(pg_pnls)
    print("\n" + "=" * 72)
    print(f"[MLB SWEEP] per-GAME honest re-validation | dates={len(dates)} | max_price={max_price}")
    print("=" * 72)
    if n_games == 0:
        print("n_games = 0 - NO qualifying sweeps in the local sample. Nothing to score.")
        return

    pnls = np.array(pg_pnls, dtype=float)
    inv = np.array(pg_invested, dtype=float)
    prof = int((pnls > 0).sum())
    total_inv = inv.sum()
    total_pnl = pnls.sum()
    # per-$100 ROI per game (equal-weight across games), guarding zero-invested (can't happen: fills>0)
    roi_per_game = 100.0 * pnls / inv
    print(f"  n_games kept        : {n_games} of {total_games} discovered ({100*n_games/total_games:.0f}%)")
    print(f"  total sweep fills   : {sum(pg_fills)}")
    print(f"  profitable games    : {prof} ({100*prof/n_games:.1f}%)")
    print(f"  per-game pnl mean    : ${pnls.mean():+.4f}")
    print(f"  per-game pnl median  : ${np.median(pnls):+.4f}")
    print(f"  per-game pnl worst   : ${pnls.min():+.4f}")
    print(f"  per-game pnl best    : ${pnls.max():+.4f}")
    print(f"  per-game pnl stdev   : ${pnls.std(ddof=1):.4f}")
    print(f"  per-game ROI mean    : {roi_per_game.mean():+.2f}% per $100 (equal-weight games)")
    print(f"  per-game ROI median  : {np.median(roi_per_game):+.2f}% per $100")
    print(f"  dollar-weighted ROI  : {100*total_pnl/total_inv:+.2f}% (invested=${total_inv:.0f}, "
          f"net=${total_pnl:+.0f})  [secondary]")

    lo, mid, hi = bootstrap_ci(pnls)
    print(f"\n  BOOTSTRAP (10,000 resamples of per-game mean pnl):")
    print(f"    5th pct  = ${lo:+.4f}/game")
    print(f"    50th pct = ${mid:+.4f}/game")
    print(f"    95th pct = ${hi:+.4f}/game")
    verdict = "CI EXCLUDES 0 (profitable)" if lo > 0 else (
        "CI EXCLUDES 0 (losing)" if hi < 0 else "CI STRADDLES 0 (indistinguishable from break-even)")
    print(f"    verdict  = {verdict}")
    if n_games < 30:
        print(f"\n  ** THIN SAMPLE WARNING: n_games={n_games} (<30). CI is wide; treat as indicative only. **")


if __name__ == "__main__":
    main()
