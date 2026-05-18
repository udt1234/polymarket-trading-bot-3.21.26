import logging
import uuid
import asyncio
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from api.services.risk_manager import Signal
from api.dependencies import get_supabase
from api.services.position_manager import open_position

log = logging.getLogger(__name__)

# Polymarket CLOB tick size is 0.001 ($0.001 = 0.1¢). Lottery-ticket entries
# at 0.3¢/0.5¢ need to pass this floor. Was 0.01 (1¢) which silently
# rejected every spike_trading tier 2 signal.
MIN_PRICE_FLOOR = 0.001


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

        # Tick-size validation: live Polymarket CLOB rejects limit orders that
        # aren't multiples of the market's min_tick_size (0.01 on standard
        # markets, 0.001 on neg_risk). Without this check, paper mode can
        # 'fill' against legacy resting orders at sub-tick prices that live
        # would never accept — masking a major paper-vs-live divergence.
        fill_price, max_depth, min_tick, min_order = self._check_liquidity_with_constraints(signal)
        if min_tick and signal.market_price > 0:
            ratio = signal.market_price / min_tick
            if abs(ratio - round(ratio)) > 0.001:
                log.info(
                    f"PAPER REJECT {signal.bracket}: price {signal.market_price:.4f} "
                    f"is not a multiple of min_tick_size {min_tick} (live CLOB would reject)"
                )
                self._log_rejection(signal, "below_min_tick_size")
                return {"status": "rejected", "reason": "below_min_tick_size", "min_tick": min_tick}
        if fill_price is None:
            # Limit didn't cross — order rests on the book unfilled. This is
            # the CORRECT outcome for our spike strategy: we WANT the limit
            # to wait. We log as 'unfilled' (not rejected) so the engine
            # doesn't treat it as a failure.
            log.info(f"PAPER UNFILLED {signal.bracket} {signal.side} @ {signal.market_price:.4f}: book hasn't crossed limit")
            return {"status": "unfilled", "reason": "limit_not_crossed", "price": signal.market_price}

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
            # Emitters that compute size explicitly stash it in
            # metadata.tier_shares. Trust that over the legacy
            # balance*kelly_pct formula (which assumes self.balance is the
            # real bankroll — not true for the new notional-based ladders).
            md = signal.metadata or {}
            explicit_size = md.get("tier_shares")
            if explicit_size is not None:
                try:
                    raw_size = float(explicit_size)
                except (TypeError, ValueError):
                    raw_size = self.balance * signal.kelly_pct
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

        # min_order_size enforcement (Polymarket CLOB rejects sub-min orders).
        if min_order and size < min_order:
            if existing:
                from api.services.position_manager import release_position_after_failed_exit
                release_position_after_failed_exit(existing["id"])
            log.info(
                f"PAPER REJECT {signal.bracket}: size {size:.4f} < min_order_size {min_order} (live CLOB would reject)"
            )
            self._log_rejection(signal, "below_min_order_size")
            return {"status": "rejected", "reason": "below_min_order_size", "min_order": min_order}

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
            open_position(signal.module_id, signal.market_id, signal.bracket, signal.side, size, fill_price, token_id=signal.token_id)

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
        except Exception as e:
            # Was a silent pass — masked schema/serialization failures that
            # caused the dashboard's stale-data check to fire even though the
            # engine was running fine. Log the failure so the next break is
            # visible in Railway logs.
            log.warning(f"signals insert failed (PaperExecutor) module={signal.module_id} bracket={signal.bracket}: {e}")

        fill_note = f" (partial: {size:.2f}/{raw_size:.2f})" if partial else ""
        log.info(f"PAPER {signal.side} {signal.bracket} size={size:.2f} @ {fill_price:.4f}{fill_note}")
        return order

    def _check_liquidity(self, signal: Signal) -> tuple:
        """Backwards-compatible 2-tuple wrapper around the constraint-aware helper."""
        fill_price, depth, _, _ = self._check_liquidity_with_constraints(signal)
        return (fill_price, depth)

    def _check_liquidity_with_constraints(self, signal: Signal) -> tuple:
        """For limit orders: only fill if the book is already crossing our limit.

        BUY: fills at best_ask only if best_ask <= signal.market_price.
             Otherwise no fill — the limit waits on the book.
        SELL: fills at best_bid only if best_bid >= signal.market_price.

        Returns (fill_price | None, depth, min_tick_size, min_order_size).
        None price = no fill (limit sits unfilled, the realistic paper outcome).
        Tick + order constraints come from Polymarket Gamma; the executor uses
        them to mirror live CLOB rejection rules in paper mode.
        """
        try:
            from api.modules.shared.polymarket import fetch_order_books_for_brackets
            books = _run_async(fetch_order_books_for_brackets(signal.market_id, [signal.bracket]))
            book = books.get(signal.bracket)
            if not book:
                return (signal.market_price, 0, None, None)

            min_tick = book.get("min_tick_size")
            min_order = book.get("min_order_size")

            if signal.side == "BUY":
                best_ask = book.get("best_ask")
                depth = book.get("ask_depth_5", 0)
                if best_ask is None or best_ask <= 0 or best_ask >= 1:
                    return (signal.market_price, depth, min_tick, min_order)
                # Limit only fills if book ask is at or below our limit
                if best_ask > signal.market_price:
                    return (None, depth, min_tick, min_order)
                return (best_ask, depth, min_tick, min_order)
            else:
                best_bid = book.get("best_bid")
                depth = book.get("bid_depth_5", 0)
                if best_bid is None or best_bid <= 0 or best_bid >= 1:
                    return (signal.market_price, depth, min_tick, min_order)
                if best_bid < signal.market_price:
                    return (None, depth, min_tick, min_order)
                return (best_bid, depth, min_tick, min_order)
        except Exception as e:
            log.warning(f"Liquidity check failed for {signal.bracket}, using signal price: {e}")
            return (signal.market_price, 0, None, None)

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

            # py_clob_client requires the typed ApiCreds dataclass, not a
            # plain dict. ClobClient.__init__ accepts the dict without error,
            # but the first order call fails with:
            #   AttributeError: 'dict' object has no attribute 'api_key'
            # at py_clob_client/client.py:631 (post_order -> order_to_json).
            # Confirmed against the installed SDK 2026-05-17.
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds
            self._client = ClobClient(
                host="https://clob.polymarket.com",
                key=private_key,
                chain_id=137,
                creds=ApiCreds(
                    api_key=api_key,
                    api_secret=secret,
                    api_passphrase=passphrase,
                ),
            )
        return self._client

    def execute(self, signal: Signal) -> dict:
        # Global PAPER_MODE and ENV guards were removed 2026-05-12 — per-module
        # status (handled by Engine._executor_for_signal) is now authoritative.
        # Real safety net is the credentials check in _get_client(): a missing
        # API key / secret / passphrase / private_key raises ValueError, so a
        # misconfigured environment cannot accidentally place orders.
        if signal.market_price <= 0 or signal.market_price >= 1:
            raise ValueError(f"Invalid price: {signal.market_price}")
        # CLOB requires the ERC-1155 token ID, NOT the human bracket label.
        # If the emitter forgot to populate this, abort BEFORE creating an
        # orders row so we don't poison the audit trail with a doomed order.
        if not signal.token_id:
            raise ValueError(
                f"LiveExecutor refusing: signal has no token_id "
                f"(module={signal.module_id} bracket={signal.bracket}). "
                f"Module emitter must populate Signal.token_id from market['token1']."
            )

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
            # Emitters that compute size explicitly (e.g. spike_trading's
            # notional-based ladder) can stash it in metadata.tier_shares
            # to bypass the legacy `1000 * kelly_pct` formula. The legacy
            # formula assumes a $1000 bankroll and breaks on neg_risk
            # markets (min_tick=0.001) where kelly_pct = notional/bankroll
            # produces tiny share counts. Trust the emitter when it
            # specifies size explicitly.
            md = signal.metadata or {}
            explicit_size = md.get("tier_shares")
            if explicit_size is not None:
                try:
                    size = float(explicit_size)
                except (TypeError, ValueError):
                    size = 1000.0 * signal.kelly_pct
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
            from py_clob_client.clob_types import OrderArgs
            side = BUY if signal.side == "BUY" else SELL

            # py_clob_client requires the typed OrderArgs dataclass, not a
            # dict. Passing a dict raises:
            #   AttributeError: 'dict' object has no attribute 'token_id'
            # at py_clob_client/client.py line 503. Confirmed against the
            # installed SDK 2026-05-16.
            order = client.create_and_post_order(OrderArgs(
                token_id=signal.token_id,
                price=signal.market_price,
                size=size,
                side=side,
            ))

            # CLOB order ID is the field py-clob-client returns as "orderID"
            # (or "id" depending on SDK version). Save it so the TTL sweep
            # can call client.cancel(orderID) later.
            clob_order_id = None
            try:
                if isinstance(order, dict):
                    clob_order_id = order.get("orderID") or order.get("id") or order.get("orderId")
            except Exception:
                pass

            sb.table("orders").update({
                "status": "filled",
                "filled_at": datetime.now(timezone.utc).isoformat(),
                "metadata": {"profile": profile_name, "clob_order_id": clob_order_id} if clob_order_id else {"profile": profile_name},
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
                open_position(signal.module_id, signal.market_id, signal.bracket, signal.side, size, signal.market_price, token_id=signal.token_id)

            log.info(f"LIVE [{profile_name}] {signal.side} {signal.bracket} size={size:.2f} @ {signal.market_price:.4f}")
            return {
                "id": order_id,
                "status": "filled",
                "profile": profile_name,
                "size": size,
                "price": signal.market_price,
                "executor": "live",
                "clob_response": str(order),
            }

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

    def cancel_clob_order(self, clob_order_id: str) -> bool:
        """Cancel a resting GTC order at the Polymarket CLOB by its order ID.
        Used by the TTL sweep so past-TTL limits don't silently fill.
        Returns True on success, False on failure (best-effort — no raise).
        """
        if not clob_order_id:
            return False
        try:
            client = self._get_client()
            # py-clob-client exposes .cancel(order_id) (returns bool or dict).
            res = client.cancel(order_id=clob_order_id)
            log.info(f"CLOB cancel {clob_order_id}: {res}")
            return True
        except Exception as e:
            log.warning(f"CLOB cancel failed for {clob_order_id}: {e}")
            return False


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
