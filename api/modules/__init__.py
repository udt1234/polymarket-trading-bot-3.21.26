import importlib
import pkgutil
import logging
from api.modules.base import BaseModule

log = logging.getLogger(__name__)

_registry: dict[str, BaseModule] = {}


class ModuleRegistry:
    def discover(self):
        import api.modules as pkg
        for importer, name, ispkg in pkgutil.iter_modules(pkg.__path__):
            if not ispkg or name == "base":
                continue
            try:
                mod = importlib.import_module(f"api.modules.{name}")
                if hasattr(mod, "Module"):
                    instance = mod.Module()
                    _registry[instance.name] = instance
                    log.info(f"Discovered module: {instance.name}")
            except Exception as e:
                log.error(f"Failed to load module {name}: {e}")

    def active_modules(self) -> list[BaseModule]:
        return [m for m in _registry.values() if m.enabled]

    def get(self, name: str) -> BaseModule | None:
        return _registry.get(name)

    def all_modules(self) -> list[BaseModule]:
        return list(_registry.values())

    def for_db_row(self, module_row: dict) -> BaseModule | None:
        """Map a Supabase modules table row to its BaseModule instance.

        Resolution priority:
        1. strategy field matches a registered module name (e.g. 'spike_rider')
        2. Display name contains a module's get_display_keywords()
        Returns None when no module matches — caller should skip the row.
        """
        if not module_row:
            return None
        strategy = (module_row.get("strategy") or "").lower().strip()
        if strategy and strategy in _registry:
            return _registry[strategy]
        display = (module_row.get("name") or "").lower()
        for mod in _registry.values():
            for kw in mod.get_display_keywords():
                if kw and kw in display:
                    return mod
        return None
