"""Empty demo module proving the registry auto-discovery contract
(BUILD_SPEC J1 Step 1). Emits no signals. Delete once S2 lands."""
from api.modules.base import BaseModule
from api.modules.demo.module_config import DEFAULT_CONFIG


class DemoModule(BaseModule):
    name = "demo"

    def get_handle(self) -> str:
        return ""

    def get_platform(self) -> str:
        return "x"

    def get_config(self, module_id: str) -> dict:
        return dict(DEFAULT_CONFIG)

    def save_config(self, module_id: str, config: dict) -> None:
        pass

    async def _evaluate_async(self) -> list:
        return []
