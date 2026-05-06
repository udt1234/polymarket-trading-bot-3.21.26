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

    def supports_direct_post_count(self) -> bool:
        """True if this module can count posts directly (bypassing xTracker)."""
        return False

    async def count_posts_in_window(self, window_start, window_end) -> dict:
        """Direct post-count implementation. Only required when
        supports_direct_post_count() returns True."""
        raise NotImplementedError(f"{self.name} does not support direct post counting")
