"""BUILD_SPEC PART J Step 6 acceptance test.

1. Forcing 5 paper losses trips the circuit breaker (and it blocks entries).
2. The daily heartbeat message actually delivers (Telegram/Slack).
3. Flipping ONLY the DB module flag to 'active' does NOT enable real money
   (LiveExecutor refuses without the env backstop).

Run: python -u scripts/step6_acceptance.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.services.polymarket_proxy import install_httpx_proxy_patch

install_httpx_proxy_patch()

from api.dependencies import get_supabase  # noqa: E402


def main() -> None:
    sb = get_supabase()
    ok = {}

    print("== 1. five consecutive losses trip the breaker ==")
    from api.services import breaker
    sb.table("settings").upsert({"key": breaker.KEY, "value": {
        "consecutive_losses": 0, "cooldown_until": "", "trips": 0}}).execute()
    for i in range(5):
        state = breaker.record_trade_result(-1.0)
    print(f"  state after 5 losses: {state}")
    ok["breaker_trips"] = bool(state.get("cooldown_until"))
    ok["breaker_blocks"] = breaker.is_tripped()
    print(f"  is_tripped(): {ok['breaker_blocks']}")
    from api.services.risk_manager import Signal, check
    sig = Signal(module_id=None, market_id="m", bracket="b", side="BUY",
                 price=0.10, size=100, token_id="t", edge=0.05, spread=0.01,
                 best_bid=0.09, best_ask=0.11)
    verdict = check(sig, breaker_tripped=True)
    ok["gate_rejects"] = (not verdict.approved) and verdict.reason == "circuit_breaker"
    print(f"  risk gate verdict under trip: {verdict}")
    sb.table("settings").upsert({"key": breaker.KEY, "value": {
        "consecutive_losses": 0, "cooldown_until": "", "trips": 0}}).execute()
    print("  breaker reset")

    print("== 2. heartbeat delivers ==")
    from api.modules import ModuleRegistry
    from api.services.engine import Engine
    from api.services.notifications import daily_heartbeat, notify
    reg = ModuleRegistry(); reg.discover()
    eng = Engine(reg)
    ok["heartbeat"] = notify("🫀 newbot Step 6 acceptance: heartbeat path test")
    print(f"  delivered: {ok['heartbeat']}")

    print("== 3. DB-only 'active' flip must NOT enable real money ==")
    from api.config import get_settings
    s = get_settings()
    print(f"  env: environment={s.environment} paper_mode={s.paper_mode} "
          f"allow_live_trading={s.allow_live_trading}")
    from api.services.executor import executor_for
    try:
        ex = executor_for("active")
        ok["dual_guard"] = False
        print(f"  UNSAFE: got {type(ex).__name__} without env backstop")
    except RuntimeError as e:
        ok["dual_guard"] = True
        print(f"  LiveExecutor correctly refused: {e}")

    print(f"\nresults: {ok}")
    print("\nACCEPT PASS" if all(ok.values()) else "\nACCEPT FAIL")


if __name__ == "__main__":
    main()
