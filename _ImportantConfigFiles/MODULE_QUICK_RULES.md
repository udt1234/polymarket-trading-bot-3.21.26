# Module Quick Rules

Moved from CLAUDE.md on 2026-10-27. Full layout, BaseModule API and config editor detail: `MODULE_ARCHITECTURE.md`.

**Goal: editing one module never breaks another. New modules drop in cleanly.**

1. **Modules MUST live in `api/modules/<module_name>/`** with these files:
   - `module.py` (BaseModule subclass, the entry point)
   - `data.py` (ONLY module-specific data fetchers)
   - `module_config.py` (config loader/saver)
   - `__init__.py` (exports the Module class)

2. **NO cross-module imports.** Never `from api.modules.truth_social.X import Y` inside `elon_tweets/` or any other module. If two modules need the same code, it lives in `api/modules/shared/`.

3. **Shared code goes in `api/modules/shared/`**: pure-function math (pacing, signals, regime, hawkes, projection, news), the Polymarket data client (xTracker/Gamma/CLOB), and any other multi-module utility.

4. **Engine/router code MUST NOT hardcode module names.** No `if "trump" in name elif "elon" in name` branches. Use the module API:
   - `module.get_handle()`: returns the social handle
   - `module.get_config()`: returns the per-module config dict
   - `module.get_search_term()`: for news/trends queries
   Add new methods to `BaseModule` when needed; never special-case in the engine.

5. **Each module owns its own settings.** Module config is per-module-id in Supabase. Never share config rows between modules.

6. **Each module surfaces its own health.** `BotHealthBanner` accepts a `moduleId` and reads `/api/engine/health?module_id=X`. One module's failure must not paint another's page red.

7. **When adding a new module:** use `@module-scaffolder` agent. It enforces the structure above.

8. **When refactoring:** if you touch shared code, run the test suite for ALL modules. If you touch one module's code, you should NOT need to touch any other module's files: if you do, the abstraction is wrong.
