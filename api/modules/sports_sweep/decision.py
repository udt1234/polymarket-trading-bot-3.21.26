"""Sports-sweep decision logic (pure given inputs).

Entry: on a DECIDED favorite (bid >= threshold), rest post-only BUY bids at a
deep-discount ladder (0.95-0.97) below fair - we fill when retail dumps the lost
side, for $0 maker fee. Edge = decided_winrate - price (buy below the ~98.5%
true win rate).

Exit: hold winners to resolution; but if the favorite FADES (a comeback), sell
out the first time its bid drops below stop_loss_bid. Baseball/basketball
comebacks are gradual, so the price steps down inning-by-inning and we can exit
well above $0 instead of eating the full -price loss.
"""
import logging

from api.services.clob import snap_price
from api.services.risk_manager import Signal

log = logging.getLogger(__name__)


def build_entry_bids(module_id: str, game: dict, fav: dict, cfg: dict,
                     resting_tokens: set[str], held_tokens: set[str],
                     fair_override: float | None = None) -> list[Signal]:
    """Rest a deep-discount post-only BUY ladder on the decided favorite,
    if we are not already quoting/holding it. When fair_override is given (the
    live game-state win probability), it replaces the flat decided_winrate as the
    fair value, so edge = p_true - price is priced off the actual game, not a
    constant. Missing/None override falls back to the config constant."""
    tok = fav["token"]
    if tok in resting_tokens or tok in held_tokens:
        return []
    tick = fav["tick"]
    levels = [p for p in cfg["bid_ladder"]
              if cfg["min_entry_price"] <= p <= cfg["max_entry_price"]
              and p < (fav["best_ask"] or 1.0)]  # stay a maker (below the ask)
    if not levels:
        return []
    per_level = cfg["per_game_max_usd"] / len(levels)
    win = fair_override if fair_override is not None else cfg["decided_winrate"]
    signals = []
    for price in levels:
        price = snap_price(price, tick)
        edge = win - price
        if edge < cfg["min_edge"]:
            continue
        size = int(per_level / price) if price > 0 else 0
        if size < 5 or size * price < 1.0:
            continue
        signals.append(Signal(
            module_id=module_id, market_id=game["condition_id"],
            bracket=fav["outcome"], side="BUY", price=price, size=size,
            token_id=tok, fair_value=win, edge=edge, auction_slug=game["slug"],
            spread=fav["spread"], best_bid=fav["best_bid"], best_ask=fav["best_ask"],
            metadata={"strategy": "sports_sweep", "decided_bid": fav["best_bid"]}))
    return signals


def build_gamestate_exits(module_id: str, positions: list[dict],
                          win_probs: dict[str, float],
                          game_by_token: dict[str, dict], cfg: dict) -> list[Signal]:
    """Sell a held favorite whose LIVE win probability has collapsed below
    exit_win_prob. Unlike the price stop-loss (which backfired on price noise),
    this fires on the actual game state (score/inning), so it cuts the real
    fat-tail collapse without selling winners on a dip that fizzles."""
    if not cfg.get("gamestate_exit_enabled", True):
        return []
    thr = cfg.get("exit_win_prob", 0.40)
    out = []
    for p in positions:
        tok = p.get("token_id")
        wp = win_probs.get(tok)
        if wp is None or wp >= thr:
            continue
        g = game_by_token.get(tok)
        if not g:
            continue
        side = next((s for s in g["sides"] if s["token"] == tok), None)
        if not side or side["best_bid"] is None:
            continue
        price = max(snap_price(side["best_bid"], side["tick"]), side["tick"])
        out.append(Signal(
            module_id=module_id, market_id=p["market_id"], bracket=p.get("bracket") or "",
            side="SELL", price=price, size=float(p["size"]), token_id=tok,
            is_exit=True, auction_slug=g["slug"], spread=side["spread"],
            best_bid=side["best_bid"], best_ask=side["best_ask"],
            metadata={"position_id": p["id"], "gamestate_exit": True,
                      "win_prob_at_exit": round(wp, 3)}))
    return out


def build_stop_exits(module_id: str, positions: list[dict],
                     game_by_token: dict[str, dict], cfg: dict) -> list[Signal]:
    """Sell out a held favorite whose current best_bid fell below the stop.

    MAKER-ONLY reality (risk-audit F4, 2026-07-22): a post-only SELL priced AT the
    bid would CROSS and be rejected by the exchange, so a "taker/marketable" stop is
    impossible on this bot. We rest the exit AT the current best_bid (a post-only
    SELL there does not cross - it joins the top of the ask queue one level above,
    at bid, which rests). It is NOT guaranteed to fill instantly; if the game keeps
    fading it re-quotes lower each cycle chasing the bid down. This is an honest
    maker stop, not a taker guarantee."""
    out = []
    if not cfg.get("stop_loss_enabled", False):
        return out  # HOLD to resolution - price stops bleed winners (backtest 2026-07-10)
    stop = cfg["stop_loss_bid"]
    for p in positions:
        tok = p.get("token_id")
        g = game_by_token.get(tok)
        if not g:
            continue
        side = next((s for s in g["sides"] if s["token"] == tok), None)
        if not side or side["best_bid"] is None:
            continue
        if side["best_bid"] < stop:
            # rest the exit at the current bid (post-only maker; will not cross)
            price = max(snap_price(side["best_bid"], side["tick"]), side["tick"])
            out.append(Signal(
                module_id=module_id, market_id=p["market_id"], bracket=p.get("bracket") or "",
                side="SELL", price=price, size=float(p["size"]), token_id=tok,
                is_exit=True, auction_slug=g["slug"], spread=side["spread"],
                best_bid=side["best_bid"], best_ask=side["best_ask"],
                metadata={"position_id": p["id"], "stop_loss": True,
                          "maker_rest_exit": True}))  # not a taker guarantee (F4)
    return out
