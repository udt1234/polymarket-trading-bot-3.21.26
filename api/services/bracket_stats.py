"""Per-bracket signal/trade/win statistics for the Bracket Analysis card.

Spec: _ImportantConfigFiles/WHALE_BRACKET_CARDS_SPEC.md

Pure-function module-id-driven analytics. No side effects, no per-module
branching. The `mode` filter (spike_only vs all_signals) reads
signals.signal_type which is populated by the 013_signal_type migration.
If signal_type is missing on a row (e.g. migration not yet run), we treat
it as 'baseline'.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
from typing import Literal

from api.dependencies import get_supabase

WindowLabel = Literal["last_5", "last_10", "all_time"]
Mode = Literal["spike_only", "all_signals"]


def _window_size(window: str) -> int | None:
    if window == "last_5":
        return 5
    if window == "last_10":
        return 10
    return None


def _bracket_won(positions: list[dict]) -> bool:
    """A bracket 'won' for an auction iff at least one closed position with
    realized_pnl > 0 exists. Open positions don't count toward win rate yet."""
    return any(
        (p.get("status") != "open") and ((p.get("realized_pnl") or 0) > 0)
        for p in positions
    )


def _ev_per_trade(trades: list[dict], realized_pnl_total: float) -> float:
    """Expected value per trade. Uses realized P&L for closed positions and
    average fill cost as the denominator. Returns 0 if no trades."""
    if not trades:
        return 0.0
    return round(realized_pnl_total / len(trades), 2)


def _last_5_results(positions: list[dict]) -> str:
    """Compress recent closed-position outcomes to a 'WLWLW' string. W = pnl>0,
    L = pnl<=0. Open positions skipped. Most recent first up to 5 chars."""
    closed = [p for p in positions if p.get("status") != "open"]
    closed.sort(key=lambda p: p.get("closed_at") or p.get("opened_at") or "", reverse=True)
    out = []
    for p in closed[:5]:
        pnl = p.get("realized_pnl") or 0
        out.append("W" if pnl > 0 else "L")
    return "".join(out)


def compute_bracket_stats(
    module_id: str,
    window: WindowLabel = "last_10",
    mode: Mode = "all_signals",
) -> dict:
    """Return per-bracket stats for the Bracket Analysis card.

    Shape matches the spec's API response (rows + comparison + n_auctions).
    Allocation is computed by the caller via allocate().
    """
    sb = get_supabase()

    # 1. Pull ALL signals for this module (we'll bucket by tracking later via
    #    market_id since market_id corresponds 1:1 with an auction).
    # signal_type may not exist yet (migration runs separately) — try with it,
    # fall back to deriving from metadata if the column is missing.
    try:
        sig_q = sb.table("signals").select(
            "id,bracket,market_id,signal_type,metadata,created_at"
        ).eq("module_id", module_id).limit(5000)
        sig_rows = (sig_q.execute().data or [])
    except Exception:
        sig_q = sb.table("signals").select(
            "id,bracket,market_id,metadata,created_at"
        ).eq("module_id", module_id).limit(5000)
        sig_rows = (sig_q.execute().data or [])

    # Backfill signal_type in-memory if column not yet populated, so the card
    # works correctly even before the migration runs.
    for s in sig_rows:
        if not s.get("signal_type"):
            md = s.get("metadata") or {}
            s["signal_type"] = (
                md.get("signal_type")
                or ("spike" if md.get("strategy") == "spike_trading" else "baseline")
            )

    # 2. Pull positions + trades for the same window
    pos_rows = (sb.table("positions").select(
        "id,bracket,market_id,size,avg_price,exit_price,realized_pnl,unrealized_pnl,status,opened_at,closed_at"
    ).eq("module_id", module_id).limit(5000).execute().data or [])

    trade_rows = (sb.table("trades").select(
        "id,bracket,market_id,size,price,side,executed_at"
    ).eq("module_id", module_id).limit(5000).execute().data or [])

    # 3. Window filter: by distinct market_id (each market_id = one auction).
    distinct_markets = sorted({p.get("market_id") for p in pos_rows if p.get("market_id")})
    n_window = _window_size(window)
    if n_window is not None:
        # Sort markets by most-recent position close/open for that market
        latest_per_market = {}
        for p in pos_rows:
            mid = p.get("market_id")
            if not mid:
                continue
            ts = p.get("closed_at") or p.get("opened_at") or ""
            if ts > latest_per_market.get(mid, ""):
                latest_per_market[mid] = ts
        ordered = sorted(distinct_markets, key=lambda m: latest_per_market.get(m, ""), reverse=True)
        in_window = set(ordered[:n_window])
    else:
        in_window = set(distinct_markets)

    # 4. Apply window + mode filters
    def _sig_passes(s):
        if s.get("market_id") not in in_window and in_window:
            return False
        if mode == "spike_only":
            return s.get("signal_type") == "spike"
        return True

    sig_w = [s for s in sig_rows if _sig_passes(s)]
    pos_w = [p for p in pos_rows if (p.get("market_id") in in_window) or not in_window]
    trade_w = [t for t in trade_rows if (t.get("market_id") in in_window) or not in_window]

    # 5. Bucket by bracket
    sigs_by_b = defaultdict(list)
    pos_by_b = defaultdict(list)
    trades_by_b = defaultdict(list)
    for s in sig_w:
        if s.get("bracket"):
            sigs_by_b[s["bracket"]].append(s)
    for p in pos_w:
        if p.get("bracket"):
            pos_by_b[p["bracket"]].append(p)
    for t in trade_w:
        if t.get("bracket"):
            trades_by_b[t["bracket"]].append(t)

    # 6. Build rows. One row per bracket that has any signal/position/trade.
    all_brackets = sorted(set(sigs_by_b) | set(pos_by_b) | set(trades_by_b))
    total_trades = sum(len(trades_by_b[b]) for b in all_brackets)
    rows = []
    for b in all_brackets:
        sigs = sigs_by_b[b]
        positions = pos_by_b[b]
        trades = trades_by_b[b]

        # Aggregate per-market: each market_id-bracket is one "event".
        per_market_pos = defaultdict(list)
        for p in positions:
            per_market_pos[p["market_id"]].append(p)
        events = list(per_market_pos.values())

        won = sum(1 for ev in events if _bracket_won(ev))
        # Trades count = actual fills count (multiple trades per position OK).
        trades_count = len(trades)
        signals_count = len(sigs)

        # Avg entry price: weighted by trade size, BUYs only.
        buy_trades = [t for t in trades if t.get("side") == "BUY"]
        if buy_trades:
            tot_cost = sum((t.get("price") or 0) * (t.get("size") or 0) for t in buy_trades)
            tot_size = sum((t.get("size") or 0) for t in buy_trades)
            avg_entry = round(tot_cost / tot_size, 4) if tot_size > 0 else 0.0
        else:
            avg_entry = 0.0

        # Realized + unrealized P&L summed per bracket.
        realized = sum(p.get("realized_pnl") or 0 for p in positions if p.get("status") != "open")
        unrealized = sum(p.get("unrealized_pnl") or 0 for p in positions if p.get("status") == "open")
        total_pnl = realized + unrealized
        cost_basis = sum((p.get("avg_price") or 0) * (p.get("size") or 0) for p in positions)
        avg_roi_pct = round((total_pnl / cost_basis) * 100, 1) if cost_basis > 0 else 0.0
        ev_per_trade = _ev_per_trade(trades, realized)

        win_rate = round((won / len(events)) * 100, 1) if events else 0.0

        annotation = None
        trade_share_pct = round((trades_count / total_trades) * 100, 1) if total_trades > 0 else 0.0
        if win_rate >= 65 and trade_share_pct < 20 and signals_count >= 10:
            annotation = "winner"
        elif ev_per_trade < 0 and trades_count >= 5:
            annotation = "stop"

        rows.append({
            "bracket": b,
            "signals_count": signals_count,
            "trades_count": trades_count,
            "won_count": won,
            "events_count": len(events),
            "win_rate_pct": win_rate,
            "avg_entry_price": avg_entry,
            "avg_roi_pct": avg_roi_pct,
            "ev_per_trade_usd": ev_per_trade,
            "last_5_results": _last_5_results(positions),
            "annotation": annotation,
            "trade_share_pct": trade_share_pct,
        })

    # 7. All-time comparison (no window filter, mode still applies)
    all_time = compute_comparison_baseline(module_id, mode)
    comparison = []
    for r in rows:
        b = r["bracket"]
        baseline = all_time.get(b, {"win_rate_pct": 0.0})
        delta = round(r["win_rate_pct"] - baseline["win_rate_pct"], 1)
        if delta <= -15:
            trend = "regime_shift"
        elif delta >= 15:
            trend = "improving"
        else:
            trend = "stable"
        comparison.append({
            "bracket": b,
            "last_window_win_pct": r["win_rate_pct"],
            "all_time_win_pct": baseline["win_rate_pct"],
            "delta_pt": delta,
            "trend": trend,
        })

    return {
        "rows": rows,
        "comparison": comparison,
        "n_auctions": len(in_window),
        "data_quality": "ok" if len(in_window) >= 5 else "insufficient",
    }


def compute_comparison_baseline(module_id: str, mode: Mode) -> dict[str, dict]:
    """Per-bracket all-time win rate, used for the recent-vs-all-time delta."""
    sb = get_supabase()
    pos_rows = (sb.table("positions").select(
        "bracket,market_id,realized_pnl,status"
    ).eq("module_id", module_id).limit(5000).execute().data or [])

    if mode == "spike_only":
        # Only count auctions where a spike-tagged signal fired in this bracket.
        try:
            sig_rows = (sb.table("signals").select(
                "bracket,market_id,signal_type,metadata"
            ).eq("module_id", module_id).limit(5000).execute().data or [])
        except Exception:
            sig_rows = (sb.table("signals").select(
                "bracket,market_id,metadata"
            ).eq("module_id", module_id).limit(5000).execute().data or [])
        spike_keys = set()
        for s in sig_rows:
            stype = s.get("signal_type")
            if not stype:
                md = s.get("metadata") or {}
                stype = "spike" if md.get("strategy") == "spike_trading" else "baseline"
            if stype == "spike" and s.get("market_id") and s.get("bracket"):
                spike_keys.add((s["bracket"], s["market_id"]))
        pos_rows = [
            p for p in pos_rows
            if (p.get("bracket"), p.get("market_id")) in spike_keys
        ]

    by_b_market = defaultdict(lambda: defaultdict(list))
    for p in pos_rows:
        b, m = p.get("bracket"), p.get("market_id")
        if b and m:
            by_b_market[b][m].append(p)

    out = {}
    for b, markets in by_b_market.items():
        events = list(markets.values())
        won = sum(1 for ev in events if _bracket_won(ev))
        out[b] = {
            "win_rate_pct": round((won / len(events)) * 100, 1) if events else 0.0,
            "events_count": len(events),
        }
    return out


def allocate(rows: list[dict], reserve_pct: float = 25) -> dict:
    """Allocation algorithm from the spec.

    Inputs: rows from compute_bracket_stats (must include ev_per_trade_usd
    and signals_count). Returns {bracket: pct} plus 'reserve'. Pct values
    are 0-100 integers that sum to 100.
    """
    reserve = max(0, min(100, reserve_pct)) / 100.0
    weights = {}
    for r in rows:
        ev = r.get("ev_per_trade_usd") or 0
        n = r.get("signals_count") or 0
        if ev <= 0:
            weights[r["bracket"]] = 0
            continue
        confidence = min(n / 10, 1.0)
        weights[r["bracket"]] = ev * confidence
    total = sum(weights.values())
    if total == 0:
        out = {b: 0 for b in weights}
        out["reserve"] = 100
        return out
    out = {b: round(w / total * (1 - reserve) * 100) for b, w in weights.items()}
    # Round error -> push remainder into reserve so total = 100.
    spent = sum(out.values())
    out["reserve"] = max(0, 100 - spent)
    return out
