from pathlib import Path
from pydantic_settings import BaseSettings

_env_file = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    # Wallet / CLOB auth (BUILD_SPEC I3)
    polymarket_api_key: str = ""
    polymarket_secret: str = ""
    polymarket_passphrase: str = ""
    polymarket_private_key: str = ""
    polymarket_wallet_address: str = ""
    polymarket_signer_address: str = ""

    # Database
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""

    # Live-money guards (BUILD_SPEC G3): real trading requires BOTH a module
    # status flip in Supabase AND this env backstop. A single DB row flip
    # must never route real money.
    environment: str = "development"
    paper_mode: bool = True
    allow_live_trading: bool = False

    # Feeds / proxy
    twitterapi_io_key: str = ""
    enable_tweet_collector: bool = True   # listen-only tweet-latency diagnostic
    polymarket_proxy_url: str = ""
    polymarket_proxy_key: str = ""
    polygon_rpc_url: str = ""

    # Alerts
    slack_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Engine cadence (seconds) - slow path (BUILD_SPEC B6)
    default_interval: int = 300

    # Risk defaults (BUILD_SPEC G1/D4)
    bankroll: float = 1000.0
    gas_reserve_pol: float = 5.0
    max_portfolio_exposure: float = 0.5
    max_single_market_exposure: float = 0.15
    max_correlated_exposure: float = 0.30
    daily_loss_limit: float = 0.05
    weekly_loss_limit: float = 0.10
    max_drawdown: float = 0.15
    min_edge_threshold: float = 0.02
    slippage_tolerance: float = 0.05
    kelly_fraction: float = 0.25
    max_book_depth_fraction: float = 0.30
    # Per-auction aggregate price ceiling floor: modules may go stricter,
    # never looser (BUILD_SPEC D4).
    auction_aggregate_price_ceiling_floor: float = 0.65

    # Circuit breaker (BUILD_SPEC G2)
    circuit_breaker_enabled: bool = True
    circuit_breaker_max_consecutive_losses: int = 5
    circuit_breaker_cooldown_minutes: int = 60

    # CORS (dashboard)
    cors_origins: str = "http://localhost:3010"

    model_config = {"env_file": str(_env_file), "env_file_encoding": "utf-8", "extra": "ignore"}


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
