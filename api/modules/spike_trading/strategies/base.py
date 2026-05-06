"""Strategy base class. Each subclass is a pluggable trading algorithm
that the SpikeTradingModule dispatches to per (auction_type, profile).

Each strategy decides:
  - whether the bot can ENTER a position right now (timing gates)
  - what limit-buy ladder to place
  - how to classify an open position state -> SELL-NOW / HOLD / SELL
  - what sell prices/multipliers to target

The strategy is stateless. All state lives in:
  - the position row (spike_positions)
  - the profile params dict (passed in)
  - the auction's xTracker tweet count + Polymarket order book
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass
class AuctionState:
    """Snapshot of the current auction the strategy is being asked about.
    Strategies should not need anything beyond what's in here."""
    market_id: str
    bracket: str
    best_bid: float
    best_ask: float
    cum_tweets: int
    hours_to_close: float
    elapsed_hours: float
    total_hours: float
    bracket_max_count: int  # the numeric cap for this bracket (40 for '<40')


class Strategy:
    """Base class. Subclasses MUST set `name` and override the four methods."""
    name: str = ""

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        if cls.name:
            from . import REGISTRY
            REGISTRY[cls.name] = cls

    # ------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------

    def can_enter(self, state: AuctionState, params: dict) -> tuple[bool, str]:
        """Should the bot place new buy orders for this auction right now?
        Returns (can_enter, reason). reason is logged for the dashboard.
        """
        raise NotImplementedError

    def build_buy_ladder(self, state: AuctionState, params: dict) -> list[dict]:
        """Returns a list of tier dicts: [{price, pct, label}, ...]
        The module wraps these into Signal objects.
        """
        raise NotImplementedError

    def classify(self, state: AuctionState, position: dict, params: dict) -> tuple[str, dict]:
        """Returns (decision, context) where decision is one of:
          'SELL-NOW' | 'HOLD' | 'HOLD-LIGHT' | 'SELL'
        context is a dict surfaced in logs (pacing_score, trigger reason, etc.)
        """
        raise NotImplementedError

    def sell_targets(self, fill_price: float, params: dict) -> list[tuple[float, float]]:
        """Returns a list of (price, fraction_of_position) sell targets.
        Used after a buy fills to place the sell ladder.
        """
        raise NotImplementedError

    # ------------------------------------------------------------
    # Optional descriptive methods (for the dashboard)
    # ------------------------------------------------------------

    def display_label(self, params: dict) -> str:
        """Human-friendly label shown in the bidding strategy panel."""
        return self.name

    def describe(self, params: dict) -> list[str]:
        """Plain-English step-by-step lines for the bidding strategy panel.
        Each item is one bullet. Override to surface strategy-specific logic.
        """
        return [f"Strategy: {self.name}"]
