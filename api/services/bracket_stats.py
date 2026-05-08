"""Per-bracket signal/trade/win statistics for the Bracket Analysis card (v2).

Spec: _ImportantConfigFiles/WHALE_BRACKET_CARDS_SPEC.md

v2 (2026-05-08): primary data source is auction_archive (one row per
resolved auction with bracket_outcomes) instead of positions. This unlocks
the "all-time win%" column with thousands of historical auctions. Bot-only
metrics (signals_count, trades_count, ev_per_trade, last_5_results) still
come from signals/positions/trades.

Pure-function module-id-driven analytics. No side effects, no per-module
branching.
"""
from __future__ import annotations
from collections import defaultdict
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


def _ev_per_trade(trades_count: int, realized_pnl_total: float) -> float:
    if not trades_count:
        return 0.0
    return round(realized_pnl_total / trades_count, 2)


def _resolve_module_meta(module_id: str) -> tuple[str | None, float | None]:
    """Return (handle, window_days) for a module. Used to scope auction_archive
    rows to the right handle + window."""
    try:
        from api.services.engine import engine
    except Exception:
        engine = None
    sb = get_supabase()
    row = sb.table("modules").select("id,name,strategy").eq("id", module_id).single().execute().data or {}
    if not row or engine is None:
        return None, None
    # Ensure registry has discovered modules. Idempotent.
    try:
        if not engine.registry.all_modules():
            engine.registry.discover()
    except Exception:
        pass
    module = engine.registry.for_db_row(row)
    if module is None:
        return None, None
    try:
        handle = module.get_handle()
    except Exception:
        handle = None
    try:
        window_days = module.get_auction_window_days()
    except Exception:
        window_days = None
    return handle, window_days


def _archive_rows_for_module(module_id: str, window: str) -> list[dict]:
    """Pull auction_archive rows for the module's handle + window-days.

    Falls back to all rows for the handle if window_days isn't declared.
    """
    handle, win_days = _resolve_module_meta(module_id)
    sb = get_supabase()
    if not handle:
        return []
    q = sb.table("auction_archive").select(
        "id,auction_slug,window_days,end_date,winning_bracket,"
        "bracket_outcomes,bracket_end_prices,bot_traded,bot_brackets,"
        "bot_pnl,bot_signals_count,bot_won_brackets"
    ).eq("handle", handle)
    # Tolerance: ±0.5 day on the window match. Spike (2-day) only sees 2-day
    # auctions; Trump (7-day) only sees 7-day. Modules that don't declare a
    # window get all rows.
    if win_days is not None:
        q = q.gte("window_days", float(win_days) - 0.5).lte(
            "window_days", float(win_days) + 0.5
        )
    res = q.order("end_date", desc=True).limit(2000).execute()
    rows = res.data or []

    n_window = _window_size(window)
    if n_window is not None and len(rows) > n_window:
        rows = rows[:n_window]
    return rows


def compute_bracket_stats(
    module_id: str,
    window: WindowLabel = "last_10",
    mode: Mode = "all_signals",
) -> dict:
    """Return per-bracket stats for the Bracket Analysis card.

    Truth source: auction_archive (one row per resolved auction). Bot-only
    fields (signals/trades/ev) layer in from signals + positions + trades.
    """
    sb = get_supabase()
    handle, _ = _resolve_module_meta(module_id)

    # 1. Window-scoped archive rows = recent ground truth
    window_rows = _archive_rows_for_module(module_id, window)
    n_auctions = len(window_rows)

    # 2. All-time archive rows for the comparison column
    all_time_rows = _archive_rows_for_module(module_id, "all_time")

    # 3. Bot signals + trades + positions (per-module — auction-archive doesn't
    #    expand to per-fill granularity).
    try:
        sig_rows = sb.table("signals").select(
            "id,bracket,market_id,signal_type,metadata,created_at"
        ).eq("module_id", module_id).limit(5000).execute().data or []
    except Exception:
        sig_rows = sb.table("signals").select(
            "id,bracket,market_id,metadata,created_at"
        ).eq("module_id", module_id).limit(5000).execute().data or []
    for s in sig_rows:
        if not s.get("signal_type"):
            md = s.get("metadata") or {}
            s["signal_type"] = (
                md.get("signal_type")
                or ("spike" if md.get("strategy") == "spike_trading" else "baseline")
            )

    pos_rows = sb.table("positions").select(
        "id,bracket,market_id,size,avg_price,exit_price,realized_pnl,unrealized_pnl,status,opened_at,closed_at"
    ).eq("module_id", module_id).limit(5000).execute().data or []

    trade_rows = sb.table("trades").select(
        "id,bracket,market_id,size,price,side,executed_at"
    ).eq("module_id", module_id).limit(5000).execute().data or []

    # 4. Apply mode filter to bot signals (spike_only or all_signals)
    if mode == "spike_only":
        sig_rows = [s for s in sig_rows if s.get("signal_type") == "spike"]

    # 5. Build per-bracket aggregates
    archive_brackets: set[str] = set()
    for r in window_rows:
        outcomes = r.get("bracket_outcomes") or {}
        archive_brackets.update(outcomes.keys())

    # Win events from archive (primary source of win rate)
    events_count: dict[str, int] = defaultdict(int)
    won_count: dict[str, int] = defaultdict(int)
    for r in window_rows:
        outcomes = r.get("bracket_outcomes") or {}
        for b, won in outcomes.items():
            events_count[b] += 1
            if won:
                won_count[b] += 1

    # Bot-side counts
    sigs_by_b: dict[str, list] = defaultdict(list)
    pos_by_b: dict[str, list] = defaultdict(list)
    trades_by_b: dict[str, list] = defaultdict(list)
    for s in sig_rows:
        if s.get("bracket"):
            sigs_by_b[s["bracket"]].append(s)
    for p in pos_rows:
        if p.get("bracket"):
            pos_by_b[p["bracket"]].append(p)
    for t in trade_rows:
        if t.get("bracket"):
            trades_by_b[t["bracket"]].append(t)

    # 6. Build rows. Union of archive-observed brackets + bot-touched brackets.
    all_brackets = sorted(archive_brackets | set(sigs_by_b) | set(pos_by_b) | set(trades_by_b))
    total_trades = sum(len(trades_by_b[b]) for b in all_brackets)

    rows = []
    for b in all_brackets:
        sigs = sigs_by_b[b]
        positions = pos_by_b[b]
        trades = trades_by_b[b]

        n_events = events_count.get(b, 0)
        n_won = won_count.get(b, 0)
        win_rate = round((n_won / n_events) * 100, 1) if n_events > 0 else 0.0

        # Avg entry price: weighted by trade size, BUYs only
        buy_trades = [t for t in trades if t.get("side") == "BUY"]
        if buy_trades:
            tot_cost = sum((t.get("price") or 0) * (t.get("size") or 0) for t in buy_trades)
            tot_size = sum((t.get("size") or 0) for t in buy_trades)
            avg_entry = round(tot_cost / tot_size, 4) if tot_size > 0 else 0.0
        else:
            avg_entry = 0.0

        realized = sum(p.get("realized_pnl") or 0 for p in positions if p.get("status") != "open")
        unrealized = sum(p.get("unrealized_pnl") or 0 for p in positions if p.get("status") == "open")
        total_pnl = realized + unrealized
        cost_basis = sum((p.get("avg_price") or 0) * (p.get("size") or 0) for p in positions)
        avg_roi = round((total_pnl / cost_basis) * 100, 1) if cost_basis > 0 else 0.0
        ev = _ev_per_trade(len(trades), realized)

        # Last-5 W/L: derived from archive (most recent auctions where this bracket appeared).
        l5 = []
        for r in window_rows[:5]:
            outcomes = r.get("bracket_outcomes") or {}
            if b in outcomes:
                l5.append("W" if outcomes[b] else "L")
        last_5 = "".join(l5)

        annotation = None
        share = round((len(trades) / total_trades) * 100, 1) if total_trades > 0 else 0.0
        if win_rate >= 65 and share < 20 and n_events >= 10:
            annotation = "winner"
        elif ev < 0 and len(trades) >= 5:
            annotation = "stop"

        rows.append({
            "bracket": b,
            "signals_count": len(sigs),
            "trades_count": len(trades),
            "won_count": n_won,
            "events_count": n_events,
            "win_rate_pct": win_rate,
            "avg_entry_price": avg_entry,
            "avg_roi_pct": avg_roi,
            "ev_per_trade_usd": ev,
            "last_5_results": last_5,
            "annotation": annotation,
            "trade_share_pct": share,
        })

    # 7. All-time comparison
    at_events: dict[str, int] = defaultdict(int)
    at_won: dict[str, int] = defaultdict(int)
    for r in all_time_rows:
        outcomes = r.get("bracket_outcomes") or {}
        for bk, won in outcomes.items():
            at_events[bk] += 1
            if won:
                at_won[bk] += 1

    comparison = []
    for r in rows:
        b = r["bracket"]
        at_n = at_events.get(b, 0)
        at_w = at_won.get(b, 0)
        at_pct = round((at_w / at_n) * 100, 1) if at_n else 0.0
        delta = round(r["win_rate_pct"] - at_pct, 1)
        if delta <= -15:
            trend = "regime_shift"
        elif delta >= 15:
            trend = "improving"
        else:
            trend = "stable"
        comparison.append({
            "bracket": b,
            "last_window_win_pct": r["win_rate_pct"],
            "all_time_win_pct": at_pct,
            "all_time_n": at_n,
            "delta_pt": delta,
            "trend": trend,
        })

    return {
        "rows": rows,
        "comparison": comparison,
        "n_auctions": n_auctions,
        "data_quality": "ok" if n_auctions >= 5 else "insufficient",
    }


def allocate(rows: list[dict], reserve_pct: float = 25) -> dict:
    """Allocation algorithm from the spec."""
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
    spent = sum(out.values())
    out["reserve"] = max(0, 100 - spent)
    return out
