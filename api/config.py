from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache

_env_file = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    polymarket_api_key: str = ""
    polymarket_secret: str = ""
    polymarket_passphrase: str = ""
    polymarket_private_key: str = ""

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""

    paper_mode: bool = True
    default_interval: int = 300

    # Risk defaults
    bankroll: float = 1000.0
    max_portfolio_exposure: float = 0.5
    max_single_market_exposure: float = 0.15
    max_correlated_exposure: float = 0.30
    daily_loss_limit: float = 0.05
    weekly_loss_limit: float = 0.10
    max_drawdown: float = 0.15
    min_edge_threshold: float = 0.02
    slippage_tolerance: float = 0.02
    kelly_fraction: float = 0.25

    # Circuit breaker
    circuit_breaker_enabled: bool = True
    circuit_breaker_max_consecutive_losses: int = 5
    circuit_breaker_cooldown_minutes: int = 30

    # CORS
    cors_origins: str = "http://localhost:3010"

    # Shadow mode
    shadow_mode: bool = False

    # LunarCrush
    lunarcrush_api_key: str = ""

    model_config = {"env_file": str(_env_file), "env_file_encoding": "utf-8", "extra": "ignore"}


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
