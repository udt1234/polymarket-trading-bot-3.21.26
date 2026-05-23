import logging
from datetime import datetime, timezone
from api.dependencies import get_supabase

log = logging.getLogger(__name__)


def open_position(module_id: str, market_id: str, bracket: str, side: str, size: float, price: float, token_id: str | None = None, metadata: dict | None = None):
    """Insert or merge into an open BUY position. `token_id` is the
    ERC-1155 CLOB token ID needed for the SELL leg — store it on first
    insert so exit_manager can resubmit a sell without re-fetching Gamma.
    """
    sb = get_supabase()
    existing = (
        sb.table("positions")
        .select("*")
        .eq("module_id", module_id)
        .eq("market_id", market_id)
        .eq("bracket", bracket)
        .eq("status", "open")
        .execute()
    )

    if existing.data:
        pos = existing.data[0]
        old_size = float(pos["size"] or 0)
        old_avg = float(pos["avg_price"] or 0)
        new_size = old_size + size
        new_avg = ((old_avg * old_size) + (price * size)) / new_size if new_size != 0 else 0
        upd = {"size": new_size, "avg_price": new_avg}
        # Backfill token_id on existing positions written before this column was set.
        if token_id and not pos.get("token_id"):
            upd["token_id"] = token_id
        sb.table("positions").update(upd).eq("id", pos["id"]).execute()
    else:
        row = {
            "module_id": module_id,
            "market_id": market_id,
            "bracket": bracket,
            "side": side,
            "size": size,
            "avg_price": price,
            "status": "open",
        }
        if token_id:
            row["token_id"] = token_id
        sb.table("positions").insert(row).execute()
    if side == "BUY" and _is_spike_signal(metadata):
        _sync_spike_position_after_buy(sb, module_id, market_id, bracket, size, price)


def find_open_position(module_id: str, market_id: str, bracket: str) -> dict | None:
    """Look up the single open BUY position matching this module/market/bracket.
    Returns None if none found. Used by exit paths to discover what to close.
    Bot is BUY-side-only today; if SELL-entry is ever added, this needs updating.
    """
    sb = get_supabase()
    res = (
        sb.table("positions")
        .select("*")
        .eq("module_id", module_id)
        .eq("market_id", market_id)
        .eq("bracket", bracket)
        .eq("side", "BUY")
        .eq("status", "open")
        .limit(1)
        .execute()
    )
    return (res.data or [None])[0]


def claim_position_for_exit(position_id: str) -> bool:
    """Atomically transition a position from 'open' -> 'closing' to claim it.

    Two concurrent exit cycles racing on the same position: only one will see
    rowcount > 0. The loser aborts before placing an order. Required because
    Supabase doesn't expose row locking — this is the cheapest safe alternative.
    """
    sb = get_supabase()
    res = (
        sb.table("positions")
        .update({"status": "closing"})
        .eq("id", position_id)
        .eq("status", "open")
        .execute()
    )
    return bool(res.data)


def release_position_after_failed_exit(position_id: str):
    """Roll a 'closing' position back to 'open' if the order didn't fill,
    so the next exit cycle can retry."""
    sb = get_supabase()
    sb.table("positions").update({"status": "open"}).eq("id", position_id).eq("status", "closing").execute()


def partial_close_position(position_id: str, sold_size: float, exit_price: float):
    """Reduce position size by `sold_size`. Used when a SELL fill was capped
    by depth and the remaining inventory should stay open. Realized PnL on
    the sold portion is recorded; the residual stays at the original avg_price."""
    sb = get_supabase()
    pos = sb.table("positions").select("*").eq("id", position_id).single().execute()
    if not pos.data:
        return None
    p = pos.data
    remaining = max((p.get("size") or 0) - sold_size, 0)
    realized = (exit_price - (p.get("avg_price") or 0)) * sold_size
    if p.get("side") == "SELL":
        realized = -realized
    sb.table("positions").update({
        "status": "open",
        "size": remaining,
        "realized_pnl": (p.get("realized_pnl") or 0) + realized,
    }).eq("id", position_id).execute()
    _sync_spike_position_after_sell(sb, p, sold_size, exit_price, remaining)
    return realized


def close_position(position_id: str, exit_price: float):
    sb = get_supabase()
    pos = sb.table("positions").select("*").eq("id", position_id).single().execute()
    if not pos.data:
        return

    p = pos.data
    pnl = (exit_price - p["avg_price"]) * p["size"]
    if p["side"] == "SELL":
        pnl = -pnl

    # Accumulate any previously-recorded realized P&L from earlier partial
    # closes on this position. Without this, a partial-fill sequence loses
    # the first tranche's P&L when the residual finally fully closes.
    total_realized = float(p.get("realized_pnl") or 0) + pnl

    sb.table("positions").update({
        "status": "closed",
        "exit_price": exit_price,
        "realized_pnl": total_realized,
        "closed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", position_id).execute()
    # QA fix #2 (2026-05-23): close the SINGLE matching spike row, not all
    # rows matching the composite key. Without a row-level id filter, a
    # historical re-entry's leftover row gets stamped LIQUIDATED too,
    # leaving the canonical positions row open and triggering bot re-entry.
    _close_spike_position_for(sb, p, exit_price, total_realized)

    return total_realized


def _is_spike_signal(metadata: dict | None) -> bool:
    md = metadata or {}
    return md.get("strategy") == "spike_trading" or md.get("signal_type") == "spike"


def _sync_spike_position_after_buy(sb, module_id: str, market_id: str, bracket: str, size: float, price: float):
    try:
        now = datetime.now(timezone.utc).isoformat()
        res = (
            sb.table("spike_positions")
            .select("*")
            .eq("module_id", module_id)
            .eq("market_id", market_id)
            .eq("bracket", bracket)
            .in_("state", ["WAITING", "MONITORING"])
            .order("last_decision_at", desc=True)
            .limit(1)
            .execute()
        )
        row = (res.data or [None])[0]
        if row:
            old_shares = float(row.get("entry_size_shares") or 0)
            old_cost = float(row.get("entry_size_usd") or 0)
            if old_cost <= 0 and old_shares > 0:
                old_cost = old_shares * float(row.get("entry_price") or 0)
            new_shares = old_shares + size
            new_cost = old_cost + (size * price)
            sb.table("spike_positions").update({
                "state": "MONITORING",
                "entry_price": new_cost / new_shares if new_shares > 0 else price,
                "entry_size_shares": new_shares,
                "entry_size_usd": new_cost,
                "last_decision": "TRACKED_BUY_FILL",
                "last_decision_at": now,
            }).eq("id", row["id"]).execute()
            return
        # QA fix #4 (2026-05-23): guard INSERT against migration 024 unique
        # index. Concurrent BUY fills could both reach here; the index
        # rejects the second, in which case we re-read and merge into the
        # row the racing cycle just inserted.
        try:
            sb.table("spike_positions").insert({
                "module_id": module_id,
                "market_id": market_id,
                "bracket": bracket,
                "state": "MONITORING",
                "entry_price": price,
                "entry_size_shares": size,
                "entry_size_usd": size * price,
                "current_tweets": 0,
                "hours_to_close": 0,
                "last_decision": "TRACKED_BUY_FILL",
                "last_decision_at": now,
            }).execute()
        except Exception as insert_err:
            err_msg = str(insert_err).lower()
            if "idx_spike_one_active_per_bracket" in err_msg or "duplicate" in err_msg or "unique" in err_msg:
                log.info(f"spike_positions: parallel BUY race for {bracket}, recursing to merge")
                _sync_spike_position_after_buy(sb, module_id, market_id, bracket, size, price)
                return
            raise
    except Exception as e:
        log.warning(f"spike position sync after buy failed: {e}")


def _sync_spike_position_after_sell(sb, position: dict, sold_size: float, exit_price: float, remaining: float):
    if position.get("side") != "BUY":
        return
    try:
        res = (
            sb.table("spike_positions")
            .select("*")
            .eq("module_id", position["module_id"])
            .eq("market_id", position["market_id"])
            .eq("bracket", position["bracket"])
            .in_("state", ["WAITING", "MONITORING"])
            .order("last_decision_at", desc=True)
            .limit(1)
            .execute()
        )
        row = (res.data or [None])[0]
        if not row:
            return
        avg = float(position.get("avg_price") or 0)
        realized = (exit_price - avg) * sold_size
        old_realized = float(row.get("realized_pnl") or 0)
        if remaining <= 0:
            # Close ONLY this specific row by id (QA fix #2).
            _close_spike_row_by_id(sb, row["id"], exit_price, old_realized + realized)
            return
        sb.table("spike_positions").update({
            "entry_size_shares": remaining,
            "entry_size_usd": remaining * avg,
            "realized_pnl": old_realized + realized,
            "last_decision": "PARTIAL_SELL_FILL",
            "last_decision_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", row["id"]).execute()
    except Exception as e:
        log.warning(f"spike position sync after sell failed: {e}")


def _close_spike_row_by_id(sb, row_id: str, exit_price: float, realized_pnl: float | None):
    """Close a SPECIFIC spike_positions row by primary key. Safe vs the
    multi-row footgun where (module_id, market_id, bracket) matches more
    than one row."""
    try:
        sb.table("spike_positions").update({
            "state": "LIQUIDATED",
            "end_price": exit_price,
            "realized_pnl": realized_pnl or 0,
            "closed_at": datetime.now(timezone.utc).isoformat(),
            "last_decision": "SELL_FILL_CLOSED",
            "last_decision_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", row_id).execute()
    except Exception as e:
        log.warning(f"spike position close-by-id failed: {e}")


def _close_spike_position_for(sb, position: dict, exit_price: float, realized_pnl: float | None):
    """Look up the most-recent active spike row for this position's
    (module/market/bracket) and close JUST that one. Safer than the
    composite-key UPDATE which would stamp all matching rows."""
    if position.get("side") != "BUY":
        return
    try:
        res = (
            sb.table("spike_positions")
            .select("id")
            .eq("module_id", position["module_id"])
            .eq("market_id", position["market_id"])
            .eq("bracket", position["bracket"])
            .in_("state", ["WAITING", "MONITORING"])
            .order("last_decision_at", desc=True)
            .limit(1)
            .execute()
        )
        row = (res.data or [None])[0]
        if row:
            _close_spike_row_by_id(sb, row["id"], exit_price, realized_pnl)
    except Exception as e:
        log.warning(f"spike position lookup-for-close failed: {e}")
