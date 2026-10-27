# Module Architecture

The bot is a **modular trading system** where each module trades a different market (Trump posts, Elon tweets, etc.). The hard rule: editing one module must never break another.

## Directory Layout

```
api/modules/
├── base.py                  # BaseModule abstract class — ALL modules inherit
├── shared/                  # Cross-module reusable code
│   ├── pacing.py            # Pacing math (regular, bayesian, dow-hourly)
│   ├── signals.py           # Kelly sizing, ranking, contrarian
│   ├── regime.py            # Regime detection (HIGH/SURGE/NORMAL/QUIET/LOW)
│   ├── hawkes.py            # Burst-pattern projection
│   ├── projection.py        # Ensemble weights + EV
│   ├── enhanced_pacing.py   # Recency-weighted, acceleration, dow-deviation
│   ├── news_classifier.py   # Claude-based news regime override
│   ├── news.py              # Google News RSS fetch (any handle)
│   ├── price_timing.py      # Should-defer-signal logic
│   └── polymarket.py        # (Phase B) xTracker/Gamma/CLOB client
├── truth_social/            # Trump module (ensemble)
│   ├── module.py            # TruthSocialModule(BaseModule)
│   ├── module_config.py
│   ├── parquet_history.py   # Trump's price history archive
│   ├── schedule.py          # Presidential schedule (Trump-specific)
│   ├── trends.py            # Google Trends for Trump
│   ├── historical_winners.py
│   ├── truthsocial_direct.py
│   ├── truthsocial_via_cnn.py
│   └── __init__.py
├── elon_tweets/             # Elon module (ensemble)
│   ├── module.py            # ElonTweetsModule(BaseModule)
│   ├── lunarcrush.py        # Sentiment integration
│   ├── module_config.py
│   └── __init__.py
├── spike_trading/           # Lottery-ticket ladder (Elon 2-day primary)
│   ├── module.py            # SpikeTradingModule(BaseModule)
│   ├── data.py
│   ├── decision.py          # adaptive_buy_price, slow_bleed_sell_price
│   ├── module_config.py
│   ├── strategies/          # Pluggable strategy plugins
│   │   ├── cheap_lottery_pacing.py
│   │   ├── mid_range_spike.py
│   │   └── big_hold_monthly.py
│   └── __init__.py
└── copy_trading/            # Mirrors whale trades from a target wallet
    ├── module.py
    ├── data.py
    ├── module_config.py
    └── __init__.py
```

Note: `data.py` is OPTIONAL per module — Trump and Elon inline their data
fetchers into `module.py` because most of the work routes through
`shared/polymarket.py`. Required only when the module has handle/source-
specific fetchers (spike_trading uses it for the series-API path).

## The Rules

### 1. NO cross-module imports
**Never** write `from api.modules.truth_social.X import Y` inside `elon_tweets/`, or vice versa. If two modules need the same function, it goes in `shared/`.

### 2. Shared code lives in `shared/`
Pure math (no I/O), generic data clients (Polymarket APIs), and any utility used by 2+ modules. Adding a new shared file? Put it under `api/modules/shared/`, never under a specific module.

### 3. The engine talks to modules through `BaseModule`
The engine and routers must NOT branch on module name. Bad:

```python
# DON'T DO THIS
if "trump" in name or "truth" in name:
    handle = "realDonaldTrump"
elif "elon" in name:
    handle = "elonmusk"
```

Good:
```python
handle = module.get_handle()
```

If you need new info from a module, add a method to `BaseModule` (and implement it in every module) — never hardcode in the engine.

### 4. Module config is per-module-id
Each module has its own row in the Supabase `modules` table. Settings, toggles, and overrides live there. Never share a config row between modules.

### 5. Module health is per-module
`/api/engine/health?module_id=X` returns health scoped to that module. The dashboard banner on a module page MUST pass its `module_id`. Global states (engine stopped, circuit breaker, stale data) still apply to all, but recent errors are filtered.

### 6. Adding a new module
Use `@module-scaffolder`. It enforces the structure. If you go manual, the new folder MUST contain: `__init__.py`, `module.py`, `module_config.py`. `data.py` is OPTIONAL — add it when your module has handle/source-specific fetchers; if you only consume `shared/polymarket.py`, inline whatever lives in `data.py` into `module.py`. Register the module by inheriting `BaseModule` — the registry auto-discovers it via `pkgutil`.

### 7. Refactoring rule
- Touching `shared/` → re-run tests for ALL modules
- Touching one module's files → should NOT require edits to another module's files
- If a single change requires editing 2+ modules' files, the abstraction is wrong — push it into `shared/`

## Phase Plan (Module Separation Roadmap)

- **Phase A** ✅ DONE — Pure-math files in `shared/`
- **Phase B** ✅ DONE — Polymarket data client (xTracker/Gamma/CLOB) in `shared/polymarket.py`
- **Phase C** ✅ DONE — `BaseModule` API methods (`get_handle`, `get_platform`, `get_display_keywords`, `get_config`, `supports_direct_post_count`, `count_posts_in_window`); engine + routers use `registry.for_db_row()` instead of name-string branches.

## BaseModule API (what every module must provide)

```python
class MyModule(BaseModule):
    name = "my_module"               # MUST match the directory name

    # REQUIRED
    def evaluate(self) -> list[Signal]: ...
    def get_status(self) -> dict: ...

    # REQUIRED if your module trades a Polymarket auction tied to a handle
    def get_handle(self) -> str: ...                  # "realDonaldTrump", "elonmusk"
    def get_platform(self) -> str: ...                # "truthsocial", "x"
    def get_display_keywords(self) -> list[str]: ...  # ["elon"] or ["truth", "trump"]
    def get_config(self, module_id: str) -> dict: ... # delegates to module_config.get_module_config
    def save_config(self, module_id: str, config: dict): ... # delegates to module_config.save_module_config
    def get_auction_title_filter(self) -> str: ...    # "tweets", "truth social"

    # OPTIONAL — override only if your module has a direct post counter
    def supports_direct_post_count(self) -> bool: return True
    async def count_posts_in_window(self, start, end) -> dict: ...

    # OPTIONAL — return a list of field descriptors so the dashboard can
    # render an editable config form for this module (no React work needed).
    # Empty list = read-only fallback. Trump/Elon use the legacy hardcoded
    # ensemble UI instead.
    def get_config_schema(self) -> list[dict]: ...

    # OPTIONAL — restrict dashboard auction lists to a single window length.
    # e.g. Spike Trading returns 2.0 to filter out 7-day / monthly Elon
    # auctions. Default None = accept all window sizes.
    def get_auction_window_days(self) -> float | None: ...

    # OPTIONAL — buy-order TTL for the engine's order-cancel sweep. Default
    # 5min. Override on deep-ladder strategies (spike: 24h) so the engine
    # doesn't yank limits that need patience. Added 2026-05-16.
    def get_buy_order_ttl_hours(self) -> float: ...

    # OPTIONAL — UI hints exposed via /api/modules/{id} so the dashboard
    # renders module-id-driven (no name-string branching in JSX). Added
    # 2026-05-16 to remove `name.includes("trump"|"elon")` in page.tsx.
    def get_auction_slug_patterns(self) -> list[str]: ...    # ["truth-social","trump"]
    def supports_post_count_divergence(self) -> bool: ...    # True iff direct+xTracker

    # OPTIONAL — strategy plugin metadata for modules with selectable
    # strategies (spike_trading). Default [].
    def get_strategy_metadata(self) -> list[dict]: ...

    # OPTIONAL — whale watching support (spec WHALE_BRACKET_CARDS_SPEC.md).
    def get_market_universe(self, window_days: float | None = None) -> list[str]: ...
    def get_brackets(self) -> list[str]: ...
    def archive_resolved_auction(self, module_id: str, auction_slug: str) -> dict | None: ...
```

The engine resolves modules from Supabase rows via `engine.registry.for_db_row(row)` — never by inspecting `row["name"]` for substrings.

## Schema-Driven Config Editor (added 2026-05-05)

Any module can declare an editable-config schema. The dashboard auto-generates a form: typed inputs, sectioned layout, dirty-tracking, save/reset, server-side bounds validation. **No frontend code per module.**

Field descriptor shape:
```python
{
  "key": "buy_tier_1_price",         # cfg dict key
  "label": "Tier 1 Buy Price",       # display
  "type": "number",                  # number | boolean | string | select | number_list_2
  "section": "buy",                  # general | buy | sell | risk | advanced
  "min": 0.001, "max": 0.99, "step": 0.001,  # number bounds
  "options": ["x", "truthsocial"],   # for type=select
  "length": 4, "cols": 1,            # for number_list_2 (rows × cols)
  "labels": ["T1", "T2", "T3", "T4"],
  "help": "Aggressive primary entry",
}
```

Server-side: `module.save_config()` should bounds-clamp against the same schema (defense-in-depth — the dashboard clamps too but a buggy/malicious client could still POST out-of-range). Reference: `api/modules/spike_trading/module_config.py:_validate_against_schema`.

Endpoints:
- `GET  /api/modules/:id/config-schema`   — schema array
- `PUT  /api/modules/:id/config-dynamic`  — partial update (any keys)
- `PUT  /api/modules/:id/config`          — legacy ensemble Pydantic path (Trump/Elon)

Frontend branches: if `cfg.enabled_models` is an array → ensemble UI; else → `<DynamicConfigForm>`.

## Tests

Module-specific tests live in `tests/test_<module>.py`. Shared-code tests live in `tests/test_<shared_file>.py` (e.g. `test_pacing.py`, `test_signals.py`). When you move code to `shared/`, move the tests with it conceptually — the test names follow the file, not the module.
