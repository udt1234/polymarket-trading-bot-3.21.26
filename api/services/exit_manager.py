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


def _resolve_thresholds(module_id: str, cfg_cache: dict) -> tuple[float, float]:
    """Return (stop_loss_pct, take_profit_pct) for a module, falling back to safe defaults.

    stop_loss_pct: cut loss when price drops by this fraction below avg_price (e.g. 0.30 = -30%).
    take_profit_pct: take profit when price rises by this fraction above avg_price (e.g. 0.50 = +50%).
    Setting either to 0 disables that exit type.
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
    sl = float(sl_raw) if sl_raw is not None else _DEFAULT_STOP_LOSS
    tp = float(tp_raw) if tp_raw is not None else _DEFAULT_TAKE_PROFIT
    cfg_cache[module_id] = (sl, tp)
    return sl, tp


def check_exits(positions: list[dict]) -> list[ExitSignal]:
    exits = []
    now = datetime.now(timezone.utc)
    cfg_cache: dict = {}

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

        stop_loss_pct, take_profit_pct = _resolve_thresholds(module_id, cfg_cache)

        # Take profit
        if take_profit_pct > 0 and current_price > avg_price * (1.0 + take_profit_pct):
            exits.append(ExitSignal(pid, f"take_profit: price up {take_profit_pct * 100:.0f}%+", "high"))
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
