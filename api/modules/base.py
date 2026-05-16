from abc import ABC, abstractmethod
from api.services.risk_manager import Signal


class BaseModule(ABC):
    """All trading modules inherit from this. Methods marked abstract MUST be
    implemented; concrete defaults can be overridden when needed.

    The engine and routers should NEVER branch on module name. If they need
    info about a module, add a method here.
    """

    # Canonical module name. Must match the directory name under api/modules/.
    name: str = "base"
    enabled: bool = True

    # Whether this module gates entry decisions on the detected regime
    # (TRANSITION / SURGE / etc). Ensemble pacing modules (truth_social,
    # elon_tweets) do — they skip entries during TRANSITION. Spike Trading
    # does NOT — its lottery-ticket ladder runs regardless of regime, so
    # the dashboard should not show "Watching — regime in transition" for
    # it. Used by the modules-list endpoint + dashboard timeline.
    gates_by_regime: bool = True

    @abstractmethod
    def evaluate(self) -> list[Signal]:
        """Run the module's strategy and return trade signals."""
        ...

    @abstractmethod
    def get_status(self) -> dict:
        """Return current module state for the dashboard."""
        ...

    def get_handle(self) -> str:
        """The social handle this module tracks (e.g. 'realDonaldTrump')."""
        raise NotImplementedError(f"{self.name} must implement get_handle()")

    def get_platform(self) -> str:
        """The xTracker platform identifier ('truthsocial', 'x', etc.)."""
        raise NotImplementedError(f"{self.name} must implement get_platform()")

    def get_display_keywords(self) -> list[str]:
        """Keywords matched against module display names in Supabase.
        Used by the registry to map DB rows to module instances. Lowercase."""
        return [self.name]

    def get_config(self, module_id: str) -> dict:
        """Load the per-module-id config dict from Supabase. Override to
        wire up the module's own module_config.get_module_config()."""
        return {}

    def save_config(self, module_id: str, config: dict) -> None:
        """Persist a partial config update for this module. Override to wire
        up the module's own module_config.save_module_config()."""
        raise NotImplementedError(f"{self.name} must implement save_config()")

    def get_auction_title_filter(self) -> str:
        """Substring used to filter xTracker auction titles for this module's
        market type. Default returns empty string = no filter."""
        return ""

    def get_auction_window_days(self) -> float | None:
        """If set, only auctions whose tracking window matches this length
        (within ±0.15d) are considered this module's. None = no length filter
        (default — accepts any window size). Spike Trading uses 2.0 to filter
        Elon's many concurrent series (1d/2d/7d/monthly) down to just 2-day."""
        return None

    def get_config_schema(self) -> list[dict]:
        """Return a list of field descriptors describing this module's config.

        Powers the dynamic config form on the dashboard. Each item:
          {
            "key": str,                    # cfg dict key
            "label": str,                  # display label
            "type": "number"|"boolean"|"string"|"select"|"number_list_2",
            "section": "general"|"buy"|"sell"|"risk"|"advanced",  # optional, default "general"
            "help": str,                   # tooltip
            "min"/"max"/"step": float,     # number constraints
            "options": list[str|number],   # for type=select
            "length": int,                 # for number_list_2 (rows × 2)
            "labels": list[str],           # column labels for number_list_2
          }
        Default returns [] which means "no editable schema" (read-only fallback)."""
        return []

    def supports_direct_post_count(self) -> bool:
        """True if this module can count posts directly (bypassing xTracker)."""
        return False

    async def count_posts_in_window(self, window_start, window_end) -> dict:
        """Direct post-count implementation. Only required when
        supports_direct_post_count() returns True."""
        raise NotImplementedError(f"{self.name} does not support direct post counting")

    # --- Bracket Analysis card support (spec: WHALE_BRACKET_CARDS_SPEC.md) ---

    def get_brackets(self) -> list[str]:
        """Bracket labels this module trades, in display order.

        Used by the Bracket Analysis card to render rows even when no
        signals exist yet. Override per-module. Default empty list -> the
        card derives brackets from observed signal data instead."""
        return []

    # Bracket-card config defaults. Per-module overrides go in the
    # module's module_config.DEFAULT_CONFIG; these are the fallbacks the
    # endpoint applies when a module hasn't customised them.
    BRACKET_CARD_DEFAULTS: dict = {
        "bracket_card_window": "last_10",   # last_5 | last_10 | all_time
        "bracket_card_mode": "all_signals", # all_signals | spike_only
        "bracket_card_reserve_pct": 25,     # 0-100, integer percent
    }

    def get_bracket_card_config(self, module_id: str) -> dict:
        """Resolved bracket-card config (own config overrides class defaults)."""
        cfg = {}
        try:
            cfg = self.get_config(module_id) or {}
        except Exception:
            pass
        out = dict(self.BRACKET_CARD_DEFAULTS)
        for k in out:
            if k in cfg and cfg[k] is not None:
                out[k] = cfg[k]
        return out

    def get_auction_slug_patterns(self) -> list[str]:
        """Substrings used by the dashboard to filter wallet-history auctions
        to those that belong to this module. Returned as lowercase keywords.

        Default: derive from get_handle() (lowercased). Override per-module
        when a single handle isn't enough — e.g. Trump module returns both
        `truth-social` and `trump` so we capture market slugs from either era.
        """
        try:
            h = (self.get_handle() or "").lower()
        except (NotImplementedError, Exception):
            return []
        return [h] if h else []

    def supports_post_count_divergence(self) -> bool:
        """True if the dashboard should render the 'xTracker vs Direct'
        post-count divergence card for this module. Defaults False;
        override on modules that have a direct post-count source separate
        from xTracker (currently: truth_social via TruthSocial Direct)."""
        return False

    def get_buy_order_ttl_hours(self) -> float:
        """How long a resting BUY limit order stays live before the engine
        cancels it. Default 5min (5/60h ≈ 0.083h) — most ensembles fill near
        top-of-book quickly. Override on modules with deep-ladder strategies
        (spike: 24h) so the engine doesn't yank limits that need patience."""
        return 5.0 / 60.0

    def get_strategy_metadata(self) -> list[dict]:
        """Strategy plugin info surfaced to the dashboard for module-config
        editors that have multiple strategy choices. Default []. Override
        only when the module has selectable strategy plugins (spike_trading)."""
        return []

    def archive_resolved_auction(self, module_id: str, auction_slug: str) -> dict | None:
        """Hook for modules to supply a custom auction_archive row.

        Default behavior: return None — the auction_archiver service falls
        back to the generic Gamma-event row builder. Override only if the
        module wants to add custom metrics (regime, pace_zscore, etc.) to
        the row's `metrics` JSONB.

        Should return a dict matching the auction_archive schema, OR a
        partial dict (auction_archiver merges it with the generic builder).
        Return None to use the generic builder unchanged."""
        return None

    # --- Whale Watching card support (spec: WHALE_BRACKET_CARDS_SPEC.md Phase 2) ---

    def get_market_universe(self, window_days: float | None = None) -> list[str]:
        """Auction slugs this module's whales should be measured against.

        Used by the /whales endpoint to look up which whale_snapshots rows
        belong to this module. Default implementation returns auction_slugs
        from auction_archive matching this module's handle + window_days.
        Override to customize."""
        try:
            from api.dependencies import get_supabase
            sb = get_supabase()
            handle = self.get_handle()
        except NotImplementedError:
            return []
        except Exception:
            return []
        if not handle:
            return []
        win = window_days if window_days is not None else self.get_auction_window_days()
        q = sb.table("auction_archive").select("auction_slug").eq("handle", handle)
        if win is not None:
            q = q.gte("window_days", float(win) - 0.5).lte(
                "window_days", float(win) + 0.5
            )
        try:
            res = q.order("end_date", desc=True).limit(50).execute()
        except Exception:
            return []
        return [r["auction_slug"] for r in (res.data or []) if r.get("auction_slug")]
