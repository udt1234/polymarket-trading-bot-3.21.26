import asyncio
import logging
from abc import ABC

log = logging.getLogger(__name__)


class BaseModule(ABC):
    """All trading modules inherit from this (BUILD_SPEC F1).

    Modules are sealed: no imports from any other strategy module; shared
    math lives in api/modules/shared/. The engine and routers must NEVER
    branch on a module name - if they need info about a module, add a
    method here.
    """

    # Canonical module name. Must match the directory name under api/modules/.
    name: str = "base"
    enabled: bool = True

    def evaluate(self, module_id: str) -> list:
        """Sync entry point used by the engine cycle. module_id is ALWAYS
        threaded down from the engine's Supabase modules row - modules must
        never resolve their own row by display name. Wraps the async impl
        for use from synchronous scheduler callbacks."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(
                        lambda: asyncio.run(self._evaluate_async(module_id))
                    ).result(timeout=120)
            return loop.run_until_complete(self._evaluate_async(module_id))
        except RuntimeError:
            return asyncio.run(self._evaluate_async(module_id))

    async def _evaluate_async(self, module_id: str) -> list:
        """Async strategy implementation. Returns a list of
        risk_manager.Signal. Override per module."""
        return []

    def get_status(self) -> dict:
        """Current module state for the dashboard."""
        return {"name": self.name, "enabled": self.enabled}

    def get_handle(self) -> str:
        """The social handle this module tracks (e.g. 'elonmusk').
        Return '' for handle-less modules."""
        raise NotImplementedError(f"{self.name} must implement get_handle()")

    def get_platform(self) -> str:
        """Platform identifier ('x', 'truthsocial', ...)."""
        raise NotImplementedError(f"{self.name} must implement get_platform()")

    def get_display_keywords(self) -> list[str]:
        """Lowercase keywords matched against module display names in
        Supabase. Used by the registry to map DB rows to instances."""
        return [self.name]

    def get_config(self, module_id: str) -> dict:
        """Load the per-module-id config dict from Supabase. Override to
        wire up the module's own module_config.get_module_config()."""
        return {}

    def save_config(self, module_id: str, config: dict) -> None:
        """Persist a partial config update (MERGE, never overwrite)."""
        raise NotImplementedError(f"{self.name} must implement save_config()")

    def get_auction_window_days(self) -> float | None:
        """If set, only auctions whose window matches this length (±0.15d)
        belong to this module. None = accepts any window size."""
        return None

    def get_config_schema(self) -> list[dict]:
        """Field descriptors driving the auto-generated settings form.
        Each item: {key, label, type, section, help, min, max, step,
        options, length, labels}. Default [] = no editable schema."""
        return []
