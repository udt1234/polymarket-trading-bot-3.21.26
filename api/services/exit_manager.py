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


def check_exits(positions: list[dict]) -> list[ExitSignal]:
    exits = []
    now = datetime.now(timezone.utc)

    for pos in positions:
        pid = pos["id"]
        avg_price = pos.get("avg_price", 0)
        current_price = pos.get("current_price", avg_price)
        created_at = pos.get("created_at", "")
        side = pos.get("side", "BUY")
        size = pos.get("size", 0)

        if avg_price <= 0:
            continue

        # Take profit
        if current_price > avg_price * 1.5:
            exits.append(ExitSignal(pid, "take_profit: price up 50%+", "high"))
            continue

        # Cut loss
        if current_price < avg_price * 0.3:
            exits.append(ExitSignal(pid, "cut_loss: price down 70%+", "high"))
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
