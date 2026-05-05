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
├── truth_social/            # Trump module
│   ├── module.py            # TruthSocialModule(BaseModule)
│   ├── data.py              # ONLY Trump-specific (truthsocial_direct, parquet)
│   ├── module_config.py
│   ├── parquet_history.py   # Trump's price history archive
│   ├── schedule.py          # Presidential schedule (Trump-specific)
│   ├── trends.py            # Google Trends for Trump
│   ├── historical_winners.py
│   ├── truthsocial_direct.py
│   ├── truthsocial_via_cnn.py
│   └── __init__.py
└── elon_tweets/             # Elon module
    ├── module.py            # ElonTweetsModule(BaseModule)
    ├── data.py              # ONLY Elon-specific
    ├── module_config.py
    └── __init__.py
```

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
Use `@module-scaffolder`. It enforces the structure. If you go manual, the new folder MUST contain: `__init__.py`, `module.py`, `data.py`, `module_config.py`. Register it by inheriting `BaseModule` — the registry auto-discovers it via `pkgutil`.

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
```

The engine resolves modules from Supabase rows via `engine.registry.for_db_row(row)` — never by inspecting `row["name"]` for substrings.

## Tests

Module-specific tests live in `tests/test_<module>.py`. Shared-code tests live in `tests/test_<shared_file>.py` (e.g. `test_pacing.py`, `test_signals.py`). When you move code to `shared/`, move the tests with it conceptually — the test names follow the file, not the module.
