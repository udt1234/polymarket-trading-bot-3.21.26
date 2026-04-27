import logging
import uuid
import asyncio
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from api.services.risk_manager import Signal
from api.dependencies import get_supabase
from api.services.position_manager import open_position

log = logging.getLogger(__name__)

MIN_PRICE_FLOOR = 0.01


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result(timeout=15)
    return asyncio.run(coro)


class PaperExecutor:
    def __init__(self):
        self.balance = 1000.0

    def execute(self, signal: Signal) -> dict:
        if signal.market_price < MIN_PRICE_FLOOR:
            log.info(f"PAPER REJECT {signal.bracket}: price {signal.market_price:.4f} below floor {MIN_PRICE_FLOOR}")
            self._log_rejection(signal, "price_below_floor")
            return {"status": "rejected", "reason": "price_below_floor"}

        fill_price, max_depth = self._check_liquidity(signal)
        if fill_price is None:
            log.info(f"PAPER REJECT {signal.bracket}: no liquidity")
            self._log_rejection(signal, "no_liquidity")
            return {"status": "rejected", "reason": "no_liquidity"}

        order_id = str(uuid.uuid4())
        # On SELL, "size" comes from kelly_pct meaning "fraction of position to liquidate".
        # On BUY, "size" comes from kelly_pct meaning "fraction of bankroll to deploy".
        existing = None
        if signal.side == "SELL":
            from api.services.position_manager import find_open_position, claim_position_for_exit
            existing = find_open_position(signal.module_id, signal.market_id, signal.bracket)
            if not existing:
                self._log_rejection(signal, "no_position_to_sell")
                return {"status": "rejected", "reason": "no_position_to_sell"}
            # Atomically claim the position so a parallel cycle can't double-sell.
            if not claim_position_for_exit(existing["id"]):
                self._log_rejection(signal, "lost_race_to_concurrent_exit")
                return {"status": "rejected", "reason": "lost_race_to_concurrent_exit"}
            raw_size = float(existing.get("size") or 0)
            size = min(raw_size, max_depth) if max_depth > 0 else raw_size
        else:
            raw_size = self.balance * signal.kelly_pct
            size = min(raw_size, max_depth) if max_depth > 0 else raw_size

        if size <= 0:
            # If we claimed a position for exit but can't fill, release it so the
            # next cycle can retry.
            if existing:
                from api.services.position_manager import release_position_after_failed_exit
                release_position_after_failed_exit(existing["id"])
            self._log_rejection(signal, "zero_size")
            return {"status": "rejected", "reason": "zero_size"}

        cost = size * fill_price

        if signal.side == "BUY":
            self.balance -= cost
        else:
            self.balance += cost

        now = datetime.now(timezone.utc).isoformat()
        partial = size < raw_size
        order = {
            "id": order_id,
            "module_id": signal.module_id,
            "market_id": signal.market_id,
            "bracket": signal.bracket,
            "side": signal.side,
            "size": size,
            "price": fill_price,
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
            "price": fill_price,
            "executor": "paper",
            "executed_at": now,
        }).execute()

        if signal.side == "SELL":
            # Partial fill (depth-capped): only close the portion that filled and
            # leave the rest open for the next cycle. Full fill: close completely.
            if size < raw_size and raw_size > 0:
                from api.services.position_manager import partial_close_position
                partial_close_position(existing["id"], size, fill_price)
            else:
                from api.services.position_manager import close_position
                close_position(existing["id"], fill_price)
        else:
            open_position(signal.module_id, signal.market_id, signal.bracket, signal.side, size, fill_price)

        try:
            sb.table("signals").insert({
                "module_id": signal.module_id,
                "market_id": signal.market_id,
                "bracket": signal.bracket,
                "side": signal.side,
                "edge": signal.edge,
                "model_prob": signal.model_prob,
                "market_price": signal.market_price,
                "kelly_pct": signal.kelly_pct,
                "approved": True,
                "metadata": signal.metadata if signal.metadata else {},
                "post_detected_at": signal.post_detected_at or now,
            }).execute()
        except Exception:
            pass

        fill_note = f" (partial: {size:.2f}/{raw_size:.2f})" if partial else ""
        log.info(f"PAPER {signal.side} {signal.bracket} size={size:.2f} @ {fill_price:.4f}{fill_note}")
        return order

    def _check_liquidity(self, signal: Signal) -> tuple:
        try:
            from api.modules.truth_social.data import fetch_order_books_for_brackets
            books = _run_async(fetch_order_books_for_brackets(signal.market_id, [signal.bracket]))
            book = books.get(signal.bracket)
            if not book:
                return (signal.market_price, 0)

            if signal.side == "BUY":
                fill_price = book.get("best_ask", signal.market_price)
                depth = book.get("ask_depth_5", 0)
            else:
                fill_price = book.get("best_bid", signal.market_price)
                depth = book.get("bid_depth_5", 0)

            if fill_price <= 0 or fill_price >= 1:
                return (signal.market_price, depth)

            return (fill_price, depth)
        except Exception as e:
            log.warning(f"Liquidity check failed for {signal.bracket}, using signal price: {e}")
            return (signal.market_price, 0)

    def _log_rejection(self, signal: Signal, reason: str):
        try:
            sb = get_supabase()
            sb.table("signals").update({
                "approved": False,
                "rejection_reason": reason,
            }).eq("module_id", signal.module_id).eq("bracket", signal.bracket).eq("approved", False).execute()
        except Exception:
            pass


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
        # On SELL, kelly_pct means "fraction of the existing position to liquidate".
        # On BUY, kelly_pct means "fraction of bankroll to deploy".
        # KNOWN LIMITATION: this path marks orders 'filled' as soon as the CLOB
        # POST returns. GTC limit orders may rest unfilled. A reconciliation job
        # against actual on-chain fills is in the backlog. Until that lands,
        # treat live execution results as best-effort. See FEATURES.md backlog.
        existing_position = None
        if signal.side == "SELL":
            from api.services.position_manager import find_open_position, claim_position_for_exit
            existing_position = find_open_position(signal.module_id, signal.market_id, signal.bracket)
            if not existing_position:
                raise ValueError(f"No open BUY position to sell: {signal.bracket}")
            if not claim_position_for_exit(existing_position["id"]):
                raise ValueError(f"Lost race to concurrent exit on {signal.bracket}")
            size = float(existing_position.get("size") or 0)
        else:
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

            if signal.side == "SELL" and existing_position:
                from api.services.position_manager import close_position
                close_position(existing_position["id"], signal.market_price)
            else:
                open_position(signal.module_id, signal.market_id, signal.bracket, signal.side, size, signal.market_price)

            log.info(f"LIVE [{profile_name}] {signal.side} {signal.bracket} size={size:.2f} @ {signal.market_price:.4f}")
            return {"id": order_id, "status": "filled", "profile": profile_name, "clob_response": str(order)}

        except Exception as e:
            sb.table("orders").update({"status": "rejected"}).eq("id", order_id).execute()
            # If we claimed an open position to exit but the order failed,
            # release it back to 'open' so the next exit cycle retries.
            if signal.side == "SELL" and existing_position:
                try:
                    from api.services.position_manager import release_position_after_failed_exit
                    release_position_after_failed_exit(existing_position["id"])
                except Exception:
                    pass
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
