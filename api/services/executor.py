import logging
import uuid
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from api.services.risk_manager import Signal
from api.dependencies import get_supabase
from api.services.position_manager import open_position

log = logging.getLogger(__name__)


class PaperExecutor:
    def __init__(self):
        self.balance = 1000.0

    def execute(self, signal: Signal) -> dict:
        order_id = str(uuid.uuid4())
        size = self.balance * signal.kelly_pct
        cost = size * signal.market_price

        if signal.side == "BUY":
            self.balance -= cost
        else:
            self.balance += cost

        now = datetime.now(timezone.utc).isoformat()
        order = {
            "id": order_id,
            "module_id": signal.module_id,
            "market_id": signal.market_id,
            "bracket": signal.bracket,
            "side": signal.side,
            "size": size,
            "price": signal.market_price,
            "status": "filled",
            "executor": "paper",
            "created_at": now,
            "filled_at": now,
        }

        sb = get_supabase()
        sb.table("orders").insert(order).execute()
        sb.table("trades").insert({
            "order_id": order_id,
            "module_id": signal.module_id,
            "market_id": signal.market_id,
            "bracket": signal.bracket,
            "side": signal.side,
            "size": size,
            "price": signal.market_price,
            "executor": "paper",
            "executed_at": now,
        }).execute()

        open_position(signal.module_id, signal.market_id, signal.bracket, signal.side, size, signal.market_price)

        sb.table("signals").update({"approved": True}).eq("module_id", signal.module_id).eq("bracket", signal.bracket).eq("approved", False).execute()

        log.info(f"PAPER {signal.side} {signal.bracket} size={size:.2f} @ {signal.market_price:.4f}")
        return order


class LiveExecutor:
    def __init__(self, profile: dict | None = None):
        self._client = None
        self._profile = profile

    def _get_client(self):
        if self._client is None:
            if self._profile:
                profile = self._profile
            else:
                from api.services.profiles import get_active_profile
                profile = get_active_profile()

            api_key = profile.get("polymarket_api_key", "")
            secret = profile.get("polymarket_secret", "")
            passphrase = profile.get("polymarket_passphrase", "")
            private_key = profile.get("polymarket_private_key", "")

            if not all([api_key, secret, passphrase, private_key]):
                raise ValueError("Missing Polymarket credentials in active profile")

            from py_clob_client.client import ClobClient
            self._client = ClobClient(
                host="https://clob.polymarket.com",
                key=private_key,
                chain_id=137,
                creds={
                    "apiKey": api_key,
                    "secret": secret,
                    "passphrase": passphrase,
                },
            )
        return self._client

    def execute(self, signal: Signal) -> dict:
        from api.config import get_settings
        settings = get_settings()
        if settings.paper_mode:
            raise RuntimeError("LiveExecutor called while PAPER_MODE is True")
        if getattr(settings, "environment", "development") != "production":
            raise RuntimeError("LiveExecutor called outside production environment")
        if signal.market_price <= 0 or signal.market_price >= 1:
            raise ValueError(f"Invalid price: {signal.market_price}")

        order_id = str(uuid.uuid4())
        size = 1000.0 * signal.kelly_pct
        if size <= 0:
            raise ValueError(f"Invalid order size: {size}")
        now = datetime.now(timezone.utc).isoformat()
        profile_name = self._profile["name"] if self._profile else "active"

        sb = get_supabase()
        sb.table("orders").insert({
            "id": order_id,
            "module_id": signal.module_id,
            "market_id": signal.market_id,
            "bracket": signal.bracket,
            "side": signal.side,
            "size": size,
            "price": signal.market_price,
            "status": "submitted",
            "executor": "live",
            "created_at": now,
            "metadata": {"profile": profile_name},
        }).execute()

        try:
            client = self._get_client()
            from py_clob_client.order_builder.constants import BUY, SELL
            side = BUY if signal.side == "BUY" else SELL

            order = client.create_and_post_order({
                "tokenID": signal.bracket,
                "price": signal.market_price,
                "size": size,
                "side": side,
                "type": "GTC",
            })

            sb.table("orders").update({
                "status": "filled",
                "filled_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", order_id).execute()

            sb.table("trades").insert({
                "order_id": order_id,
                "module_id": signal.module_id,
                "market_id": signal.market_id,
                "bracket": signal.bracket,
                "side": signal.side,
                "size": size,
                "price": signal.market_price,
                "executor": "live",
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "metadata": {"profile": profile_name},
            }).execute()

            open_position(signal.module_id, signal.market_id, signal.bracket, signal.side, size, signal.market_price)

            log.info(f"LIVE [{profile_name}] {signal.side} {signal.bracket} size={size:.2f} @ {signal.market_price:.4f}")
            return {"id": order_id, "status": "filled", "profile": profile_name, "clob_response": str(order)}

        except Exception as e:
            sb.table("orders").update({"status": "rejected"}).eq("id", order_id).execute()
            log.error(f"Live execution failed [{profile_name}]: {e}")
            raise

    def invalidate_client(self):
        self._client = None


class MultiExecutor:
    def __init__(self, profiles: list[dict]):
        self._executors = {p["name"]: LiveExecutor(profile=p) for p in profiles}

    @property
    def profile_names(self) -> list[str]:
        return list(self._executors.keys())

    def execute(self, signal: Signal) -> dict:
        results = {}
        with ThreadPoolExecutor(max_workers=len(self._executors)) as pool:
            futures = {
                pool.submit(self._execute_one, name, executor, signal): name
                for name, executor in self._executors.items()
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    results[name] = {"status": "ok", "result": future.result()}
                except Exception as e:
                    results[name] = {"status": "error", "error": str(e)}
                    log.error(f"MultiExec failed for profile '{name}': {e}")

        succeeded = sum(1 for r in results.values() if r["status"] == "ok")
        failed = len(results) - succeeded
        log.info(f"MultiExec complete: {succeeded} succeeded, {failed} failed across {len(results)} profiles")

        return {
            "multi": True,
            "total": len(results),
            "succeeded": succeeded,
            "failed": failed,
            "results": results,
        }

    def _execute_one(self, name: str, executor: LiveExecutor, signal: Signal) -> dict:
        return executor.execute(signal)

    def invalidate_clients(self):
        for executor in self._executors.values():
            executor.invalidate_client()
