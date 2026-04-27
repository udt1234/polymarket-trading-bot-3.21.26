import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from api.dependencies import get_supabase
from api.services.position_manager import close_position

log = logging.getLogger(__name__)


@dataclass
class ExitSignal:
    position_id: str
    reason: str
    urgency: str  # "high", "medium", "low"


_DEFAULT_STOP_LOSS = 0.30
_DEFAULT_TAKE_PROFIT = 0.0
_DEFAULT_TRAILING_STOP = 0.30


def _resolve_thresholds(module_id: str, cfg_cache: dict) -> tuple[float, float, float]:
    """Return (stop_loss_pct, take_profit_pct, trailing_stop_pct) for a module.

    stop_loss_pct: cut loss when price drops by this fraction below avg_price (0.30 = -30%).
    take_profit_pct: take profit when price rises by this fraction above avg_price (0.50 = +50%).
    trailing_stop_pct: cut loss when price drops by this fraction off the peak observed
                      since position open (0.30 = -30% from peak, only after a runup).
    Setting any to 0 disables that exit type.
    """
    if module_id in cfg_cache:
        return cfg_cache[module_id]
    cfg = {}
    if module_id:
        try:
            from api.modules.truth_social.module_config import get_module_config
            cfg = get_module_config(module_id)
        except Exception as e:
            log.warning(f"exit_manager: module config load failed for {module_id} ({e}); using defaults")

    sl_raw = cfg.get("stop_loss_pct", _DEFAULT_STOP_LOSS)
    tp_raw = cfg.get("take_profit_pct", _DEFAULT_TAKE_PROFIT)
    ts_raw = cfg.get("trailing_stop_pct", _DEFAULT_TRAILING_STOP)
    sl = float(sl_raw) if sl_raw is not None else _DEFAULT_STOP_LOSS
    tp = float(tp_raw) if tp_raw is not None else _DEFAULT_TAKE_PROFIT
    ts = float(ts_raw) if ts_raw is not None else _DEFAULT_TRAILING_STOP
    cfg_cache[module_id] = (sl, tp, ts)
    return sl, tp, ts


def _is_late_in_auction(pos: dict, threshold: float = 0.10) -> bool:
    """True if less than `threshold` fraction of the auction window remains.

    Best-effort: reads the module's resolution_date and computes time_remaining /
    total_duration. If we can't resolve the auction window, returns False (i.e.
    trailing stop runs as normal — fail-open since the gate is just a safety
    nicety).
    """
    try:
        sb = get_supabase()
        module_id = pos.get("module_id")
        if not module_id:
            return False
        m = sb.table("modules").select("resolution_date,created_at").eq("id", module_id).single().execute()
        meta = m.data or {}
        res_str = meta.get("resolution_date")
        if not res_str:
            return False
        res = datetime.fromisoformat(res_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        # Use position created_at as a proxy auction start when no other anchor
        # is available. Underestimates total_duration but works for the gate.
        opened_str = pos.get("created_at")
        opened = (
            datetime.fromisoformat(opened_str.replace("Z", "+00:00"))
            if opened_str else now
        )
        total_seconds = (res - opened).total_seconds()
        remaining_seconds = (res - now).total_seconds()
        if total_seconds <= 0:
            return True  # past resolution — definitely late
        frac_remaining = remaining_seconds / total_seconds
        return frac_remaining < threshold
    except Exception:
        return False


def _fetch_peak_prices(positions: list[dict]) -> dict[str, float]:
    """Return {position_id: peak_price} from price_snapshots since each position opened.

    Single batched query per (module_id, bracket) combo to keep DB load minimal.
    Falls back to current_price if snapshots are missing.
    """
    if not positions:
        return {}
    sb = get_supabase()
    peaks: dict[str, float] = {}
    # Group by (module_id, bracket) to dedupe queries when multiple positions share them.
    # In practice each (module, bracket) usually has 1 open position.
    for pos in positions:
        pid = pos.get("id")
        module_id = pos.get("module_id")
        bracket = pos.get("bracket")
        created_at = pos.get("created_at")
        if not (pid and module_id and bracket and created_at):
            continue
        try:
            res = (
                sb.table("price_snapshots")
                .select("price")
                .eq("module_id", module_id)
                .eq("bracket", bracket)
                .gte("snapshot_at", created_at)
                .order("price", desc=True)
                .limit(1)
                .execute()
            )
            rows = res.data or []
            if rows and rows[0].get("price") is not None:
                peaks[pid] = float(rows[0]["price"])
        except Exception as e:
            log.warning(f"peak fetch failed for position {pid} ({module_id}/{bracket}): {e}")
    return peaks


def check_exits(positions: list[dict]) -> list[ExitSignal]:
    exits = []
    now = datetime.now(timezone.utc)
    cfg_cache: dict = {}

    # Pre-fetch peak prices for trailing-stop evaluation. One batched call instead
    # of querying inside the loop.
    peaks = _fetch_peak_prices(positions)

    for pos in positions:
        pid = pos["id"]
        avg_price = pos.get("avg_price", 0)
        current_price = pos.get("current_price", avg_price)
        created_at = pos.get("created_at", "")
        side = pos.get("side", "BUY")
        size = pos.get("size", 0)
        module_id = pos.get("module_id", "")

        if avg_price <= 0:
            continue

        stop_loss_pct, take_profit_pct, trailing_stop_pct = _resolve_thresholds(module_id, cfg_cache)

        # Take profit
        if take_profit_pct > 0 and current_price > avg_price * (1.0 + take_profit_pct):
            exits.append(ExitSignal(pid, f"take_profit: price up {take_profit_pct * 100:.0f}%+", "high"))
            continue

        # Trailing stop — only fires after the position has actually been in
        # *meaningful* profit (peak >= avg_price * 1.05) so a 0.5% wiggle doesn't
        # arm a 30% trailing exit. Runs BEFORE the fixed stop so we lock in
        # remaining profit before falling all the way to the cost-basis stop.
        # Skipped in the last 10% of the auction window since late-week prices
        # converge to 0/1 and mean-revert noisily — those should resolve naturally,
        # not via trailing exit.
        if trailing_stop_pct > 0 and side == "BUY":
            peak = peaks.get(pid, 0.0)
            armed = peak >= avg_price * 1.05
            late_in_auction = _is_late_in_auction(pos, threshold=0.10)
            if armed and not late_in_auction and current_price < peak * (1.0 - trailing_stop_pct):
                exits.append(ExitSignal(
                    pid,
                    f"trailing_stop: price ${current_price:.3f} is {trailing_stop_pct * 100:.0f}%+ off peak ${peak:.3f}",
                    "high",
                ))
                continue

        # Cut loss
        if stop_loss_pct > 0 and current_price < avg_price * (1.0 - stop_loss_pct):
            exits.append(ExitSignal(pid, f"cut_loss: price down {stop_loss_pct * 100:.0f}%+", "high"))
            continue

        # Time decay
        if created_at:
            try:
                opened = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                days_open = (now - opened).total_seconds() / 86400
                unrealized = (current_price - avg_price) * size
                if side == "SELL":
                    unrealized = -unrealized
                if days_open > 5 and unrealized < 0:
                    exits.append(ExitSignal(pid, f"time_decay: open {days_open:.1f}d with negative P&L", "medium"))
                    continue
            except (ValueError, TypeError):
                pass

        # Edge reversal
        model_prob = pos.get("model_prob")
        if model_prob is not None and side == "BUY":
            if current_price > model_prob:
                exits.append(ExitSignal(pid, "edge_reversal: market past model prob", "medium"))
                continue

    return exits


def execute_exits(exits: list[ExitSignal], positions_by_id: dict, executor) -> list[dict]:
    results = []
    sb = get_supabase()
    for ex in exits:
        pos = positions_by_id.get(ex.position_id)
        if not pos:
            continue
        current_price = pos.get("current_price", pos.get("avg_price", 0))
        try:
            pnl = close_position(ex.position_id, current_price)
            sb.table("logs").insert({
                "log_type": "exit",
                "severity": "info",
                "module_id": pos.get("module_id"),
                "message": f"Exit {pos.get('bracket')}: {ex.reason} (pnl={pnl:.4f})",
                "metadata": {"position_id": ex.position_id, "reason": ex.reason, "urgency": ex.urgency},
            }).execute()
            results.append({"position_id": ex.position_id, "reason": ex.reason, "pnl": pnl})
        except Exception as e:
            log.error(f"Exit failed for {ex.position_id}: {e}")
    return results
