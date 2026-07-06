# Polymarket Elon Tweet Bot: Full Build Specification

**Version 1.0, compiled 2026-07-03. Maker-only, limit-only.**

This is the single, self-contained build spec. A developer can build the whole system from this file. It assumes NO prior knowledge of this project or of Polymarket.

## How a new session should use this file
1. Read this file top to bottom first.
2. Then read `_ImportantConfigFiles/NEW_BOT_PLAYBOOK.md` (fuller narrative + all prior-session findings) and `_ImportantConfigFiles/HANDOFF.md` (current state).
3. Auto-loaded memory (`~/.claude/projects/.../memory/`) holds the hard rules: `new_bot_master_build_2026_07_01.md`, `new_bot_maker_only.md`, `lesson_clob_v2_execution_specs.md`, `lesson_maker_not_taker.md`, `lesson_presign_hotpath.md`.
4. Companion Google Docs (same content): Full Spec `1TG4tdWR07Ob-vm4MD9dJpomoFwoIR8e5CUka3OvkLfM`, plain-English `1yEkXd7xQe3-frnntb_Oh4617kQ5lb_0JRmY41wB9oKo`.
5. Credentials live only in `~/.credentials/shared.env` (never commit). Start build at PART J Step 1.

---

# PART A: Background (no prior knowledge needed)

## A1. What we are building
An automated trading bot for Polymarket (a prediction market). It trades markets that ask "how many times will Elon Musk post on X during a fixed time window?" The bot places patient limit orders that rest on the order book, earns a small fee for providing them, and reacts within one second whenever Elon posts (a new tweet changes which answer is likely). It never chases the market price; it always sets its own. Runs 24/7 on a cloud server, stores state in a database, and auto-stops if it starts losing money.

## A2. What Polymarket is
A prediction market where shares in an outcome pay exactly 1.00 pUSD if it happens and 0.00 if not. A share's price (0 to 1) is the market's probability estimate. Trading is a CLOB (Central Limit Order Book): bids, asks, matched by the exchange.

## A3. What a tweet-count market is
For a fixed window (e.g. a 2-day window, noon ET to noon ET), Polymarket lists brackets: "less than 40", "40 to 49", "50 to 59", up to a high open-ended bracket. Each bracket is its own market with YES and NO sides. Exactly one wins (the one containing the final count). At the close, Polymarket counts tweets via xtracker + the UMA on-chain oracle; the winning bracket's YES shares become 1.00, the rest 0.00.

## A4. How the bot makes money (and the honest reality)
Our research (77 dev sessions) found the market forecasts the final count very well; you cannot reliably out-predict it. So the bot does NOT try to be smarter than the crowd. It makes money via: (1) maker rebates (the exchange pays makers who provide resting liquidity, and charges makers nothing); (2) buying slightly below fair value on dips and holding to resolution; (3) being first to re-price the instant a tweet lands. Break-even rule: on a share priced p, you only profit if your win rate exceeds p. A high win rate is not an edge by itself.

## A5. Glossary
- **CLOB**: Central Limit Order Book (the matching system).
- **Maker**: posts a resting limit order that waits. Zero exchange fee, can earn a rebate. OUR BOT IS ALWAYS A MAKER.
- **Taker**: takes an existing order immediately (crosses the spread). Pays a fee. OUR BOT IS NEVER A TAKER.
- **Limit order**: an order with a set price; a buy fills at your price or better, never worse. We only ever use limit orders.
- **Post-only**: a flag that rejects an order if it would immediately trade, guaranteeing maker status.
- **GTC / GTD**: Good-Till-Cancelled / Good-Till-Date. Post-only works with both.
- **Bracket**: one answer range (e.g. "50 to 59"); each is a separate market.
- **Condition ID / Token ID**: the on-chain id of one market / of one side (YES or NO) used when placing orders.
- **pUSD**: Polymarket USD, the Polygon ERC-20 collateral, backed 1:1 by USDC.
- **EIP-712**: the Ethereum standard for signing structured data; every order is signed this way.
- **Gamma / data-api / xTracker**: Polymarket's public data services (discovery, per-wallet trades, tweet-count tracker).
- **Fair value**: our model's estimate of a bracket's true win probability.
- **Edge**: fair value minus market price.
- **Kelly sizing**: how much to bet given edge and price.
- **Adverse selection**: getting filled exactly when you are wrong, because the counterparty knows something you do not yet.

---

# PART B: Architecture

## B1. Core design principles (non-negotiable)
- **Maker-only**: every order is a post-only limit order. Never takes.
- **Decoupled**: independent processes, each its own failure domain. One crashing/hanging must never block or crash another. They communicate only through the shared database.
- **Modules are sealed**: each strategy is a self-contained package with NO imports from any other strategy. Shared math lives in `shared/`.
- **Fail-closed**: every safety check blocks trading if data is missing or an error occurs.
- **Never trust a submission as a fill**: an order POST is an acknowledgement, not a fill. Open/close a position only after an on-chain confirmed fill.
- **Dual live guard**: real-money trading requires TWO independent switches on (see G3). One DB flag is never enough.

## B2. Tech stack
- Backend: Python 3.12+, FastAPI, APScheduler, py_clob_client, httpx, websockets, pandas + pyarrow + duckdb, pydantic-settings.
- Database: Supabase (hosted PostgreSQL), micro tier.
- Dashboard (separate project): Next.js, read-only.
- Hosting: Railway for always-on services; optional Dublin VPS (AWS eu-west-1) for latency-critical work only.
- Blockchain: Polygon (Chain ID 137). Orders matched off-chain, settled on-chain.

## B3. Repository layout
- `api/main.py`: FastAPI entry; installs the Polymarket proxy before any SDK import; starts the engine.
- `api/services/engine.py`: the main loop (cycles, calls modules, routes signals through risk to the executor).
- `api/services/`: risk_manager.py, executor.py (LiveExecutor + PaperExecutor), exit_manager.py, position_manager.py, wallet.py, retention.py, notifications.py.
- `api/modules/<name>/`: one folder per strategy. Files: module.py (BaseModule subclass), data.py, decision.py, module_config.py, __init__.py.
- `api/modules/shared/`: pure I/O-free math + the Polymarket client: polymarket.py, pacing.py, projection.py, signals.py, regime.py, canonical_data.py, l2_history.py, parquet_archive.py. Dependencies flow modules -> shared, never reverse.
- `scripts/`, `_DataMetricPulls/` (parquet data), `infra/` (Cloudflare Worker proxy).

## B4. Process topology
- **Bot API service** (Railway or Dublin VPS): FastAPI + engine loop + in-process schedulers. The brain + order manager.
- **L2 recorder** (Railway worker): subscribes to the CLOB WebSocket, records the order book to parquet 24/7. Already live since 2026-06-23.
- **Telegram/Slack alerter** (Railway worker): read-only notifications, never trades.
- **Dashboard** (Railway, root = web/): Next.js, read-only.
- Every process stores state in Supabase, never local files (wiped on redeploy).

## B5. The message bus
Supabase is the shared notebook. Every process reads/writes rows there; no process calls another directly. EXCEPTION: the database is kept OFF the sub-second hot path (B6). The hot path works from in-memory state a background loop keeps fresh, because a DB round-trip is too slow when reacting to a tweet.

## B6. Two speed lanes plus background prep
- **HOT PATH** (target: well under 1s): triggered by a streamed tweet. Does exactly two things: (1) batch-cancel our now-stale resting orders in the affected market, (2) submit a pre-built, pre-signed set of new orders. It does NOT compute fair value and does NOT sign on this path.
- **BACKGROUND PREP** (continuous, between tweets, in the API process, off the hot path): for the current live auctions, repeatedly (every few seconds) compute what our orders SHOULD be if the count ticks up by one or two, pre-build and PRE-SIGN them, hold in memory ready to fire. This is what makes the hot path instant.
- **SLOW PATH** (every 5 min, scheduled): discover new auctions, recalibrate pacing, run exits, poll the copy-trade whale, full risk re-sync. Also: resolution checks every 30 min, full new-auction scan every 1 hr, walk-forward model recalibration every 6 hr.

## B7. End-to-end data flow
1. Tweet stream (TwitterAPI.io) pushes a new Elon post in under 0.5s.
2. Hot path checks the pre-signed set for the new count, cancels stale orders, submits the ready orders through the warm connection.
3. Execution records each order as "submitted" and waits for a fill confirmation (never assumes a fill).
4. A fill poller confirms fills on-chain and writes positions to the DB.
5. In parallel, background prep recomputes fair value and refreshes the pre-signed set for the next possible tweet.
6. Every 5 min the slow path reconciles positions, runs exits, re-syncs risk, polls the whale.
7. Observability watches all of it, alerts, can auto-stop.

---

# PART C: External integrations (Polymarket)

## C1. The six surfaces
- **CLOB trading**: clob.polymarket.com via py_clob_client (signed orders).
- **CLOB WebSocket**: wss://ws-subscriptions-clob.polymarket.com/ws/market. Full book snapshots, top-of-book changes, trades. At most 150 token IDs per connection; use multiple connections. (5 WS connections per IP max.)
- **Gamma**: gamma-api.polymarket.com (public). Discovery + live bid/ask/spread.
- **data-api**: data-api.polymarket.com (public). /positions, /value, /trades, /activity. Copy-trading + real wallet positions.
- **xTracker**: xtracker.polymarket.com (public). Fallback count source + auction discovery.
- **On-chain (Polygon)**: settlement confirmations + redeeming winnings, via a Polygon RPC.

## C2. Market discovery (Gamma is primary)
- Discover ALL live tweet markets in one call: `GET gamma-api.polymarket.com/events?tag_id=972&closed=false` (tag 972 = Tweet Markets; tag 282 = Elon). Returns brackets with inline YES/NO token IDs.
- Discover recurring auctions early: `GET gamma-api.polymarket.com/series?slug=elon-tweets-48h` returns past/current/future auctions ~2 days before xTracker activates. Series slugs: elon-tweets-48h (2-day), elon-tweets (7-day, ~26 brackets), elon-tweet-daily (monthly).
- Always FILTER OUT resolved/closed brackets (`closed=true OR acceptingOrders=false`) before modeling.
- Read live prices from Gamma `bestBid`/`bestAsk`/`spread`, NOT the raw CLOB /book (returns fake near-empty on-chain books).

## C3. Auction windows (get exactly right)
- Windows run noon ET to noon ET, exclusive at 12:00:00 PM ET. 2-day = 48h, 7-day = 168h (handle DST: 167 or 169h; add days IN Eastern Time, not 168 UTC hours).
- PARSE the window from the market slug (e.g. `elon-musk-of-tweets-may-23-may-25` = May 23 noon ET to May 25 noon ET). Do NOT use Gamma startDate (listing date, often 2 days early) or trade-derived timestamps (~2x too wide).
- Convert tweet timestamps to ET via zoneinfo (America/New_York) before deciding if a tweet is in-window.

## C4. Tweet ingestion + counting rule
- Source: TwitterAPI.io filtered stream (paid, sub-500ms, persistent WebSocket). The hot-path trigger.
- Elon counting rule (LOCKED, validated to within 2-3 tweets vs xTracker): count originals + quotes + reposts + main-feed self-replies (`in_reply_to_user_id == 44196397`). EXCLUDE pure replies to others + community reposts.
- Count in the ET window only. Persist every count observation to `post_count_snapshots` every cycle.
- xTracker = fallback/cross-check. UMA on-chain oracle = the true resolver. If they disagree near close, prefer the direct X count and flag it.

## C5. Order book + our fills (WebSocket)
- Subscribe to the CLOB WS for the YES+NO token IDs of every bracket we quote (<=150 tokens/connection).
- Subscribe to the authenticated user channel to stream our own order/fill updates (do not poll if a stream exists).
- Add a per-connection stall watchdog (a half-open socket looks alive but captures nothing).

## C6. Copy-trade / whale feed
- Poll `GET data-api.polymarket.com/trades?user=0xWHALE` every ~2s (no stream for a third-party wallet). Each trade: proxyWallet, side, size, price, timestamp, condition id.
- Portfolio/perf via /positions?user=, /value?user=, /activity?user=.
- Ignore "magic" 0-cent, 100%-win wallets (Polymarket's own NegRisk infrastructure, PnL zero).

---

# PART D: The modeling brain (fair value)

## D1. Purpose
Estimate fair value: for each bracket, its probability of being the winner given the count so far and time left. Used to spot deals (edge) and size orders. We do NOT wait for the model to beat the market; the model is the ruler we measure deals against.

## D2. Projecting the final count (pacing model)
- Inputs: posts_so_far, elapsed_fraction (time elapsed / total, floored 0.001, capped 0.99), a prior mean/std from previous CLOSED auctions of the same handle+duration.
- Base projection (Bayesian Gamma-Poisson blend): `obs_projection = posts_so_far / elapsed_fraction`; `posterior_mean = (prior_precision*prior_mean + obs_precision*obs_projection) / (prior_precision + obs_precision)`. Beats naive linear (5 tweets in hour 1 must not predict 840/week).
- Best model = an ensemble averaging a Kalman filter and a Particle Filter probability vector (they err differently). Validated priors: Elon 7-day ~207 (std ~55); Elon monthly median ~923 (prefer median, Dec 2025 outlier 1654 skews mean).
- Regime persistence is the biggest signal: anchor early on a recent ~6-day baseline (corr to final ~+0.63).

## D3. Turning the projection into bracket probabilities
- Model the final count as normal around the projection with `sigma = sqrt(max(projection - posts_so_far, 1))`. This "remaining uncertainty" sigma is the single most important fix (the old sigma was ~10x too wide near close).
- Floor to 0 any bracket whose upper bound < posts_so_far (count only rises = impossible). Renormalize to sum 1.
- Shrink uncertainty as the window ends: multiply std by `sqrt(remaining_days / total_days)`. In the final part (remaining fraction < 0.30) use a pure normal (drop right-skew).
- Each bracket's fair value = the normal's probability mass inside that bracket's range.

## D4. Edge and Kelly sizing
- Edge per share = `fair_value - price`.
- Full Kelly for a 1-dollar binary: `f_star = (q - p) / (1 - p)`, q = fair_value, p = price.
- Fractional Kelly: `stake_fraction = 0.25 * f_star`. Caps: <=15% of bankroll in one market, <=50% total, never >30% of visible book depth.
- Shares = stake_dollars / price. Only bid if the sized stake is >= a small floor (~0.1% of bankroll).
- Aggregate price ceiling: the SUM of average prices across all brackets held in one auction must stay under 0.65 (exactly one bracket wins, so sum < 1.00 guarantees at least one wins; < 0.65 locks in edge).

---

# PART E: Execution (CLOB V2, the money path)

## E1. Wallet, collateral, approvals
- Trade from a dedicated BOT wallet. Collateral is pUSD; convert USDC.e via the Collateral Onramp.
- One-time on-chain: approve the V2 CTF Exchange + V2 Negative Risk Exchange for pUSD + ERC-1155 conditional tokens (addresses in the appendix).
- Optional sub-wallets (one per live strategy) for risk isolation. Do NOT build nonce-sequencing (V2 removed the nonce).

## E2. Signing orders (CLOB V2)
- CLOB V2 live 2026-04-28. EIP-712 typed data. EXCHANGE domain version = "2"; AUTH ClobAuthDomain stays "1" (crossing them = immediate auth failure).
- NO nonce field. Uniqueness = a millisecond timestamp in the signed struct. Signing V1 -> `order_version_mismatch` (hard reject).
- Use py_clob_client. Typed dataclasses: `OrderArgs(token_id, price, size, side)`, `ApiCreds(api_key, api_secret, api_passphrase)`. Dicts crash later with AttributeError.
- Struct asymmetry: nonce, feeRateBps, taker, expiration are REMOVED from the signed struct; taker + expiration must still be passed in the outer JSON body of POST /order.
- GTD expiration = `now + 60 + N` seconds (60s minimum safety threshold).

## E3. Post-only limit orders (our only order type)
- Set `post_only = true` on every order. Would-cross -> rejected `INVALID_POST_ONLY_ORDER` (never takes). With FOK/FAK -> `INVALID_POST_ONLY_ORDER_TYPE`. Works only with GTC/GTD.
- Validate all three CLOB minimums at build time: >=5 shares, >=$1 notional, price on the tick (1c standard; 0.001 neg-risk). `shares = round(notional / price)`. Snap price to tick.

## E4. Heartbeat (mandatory)
- Send a heartbeat every 2 to 3 seconds (field heartbeat_id, empty on first), in an isolated lightweight thread. No valid heartbeat within 10s (+5s buffer) -> ALL open orders cancelled (5s leaves only a one-miss buffer; 2-3s is safer).
- MATCHING-ENGINE RESTARTS (verified): during a restart the CLOB returns HTTP 425 (Too Early), then runs POST-ONLY for ~2 minutes (cancels accepted, non-post-only rejected with 503). Announced ~2 days ahead via Discord/Telegram; no fixed public schedule. Handle 425 with exponential-backoff retry and pause new entries. The 2-min post-only window FAVORS us (we are already post-only while takers are locked out).

## E5. Order lifecycle + state machine
- States: submitted -> open -> (partial) -> filled -> confirmed (on-chain). Also cancelled. NEVER mark filled on the POST ack.
- A fill poller (or the user WS channel) confirms fills; only then write a position row. Accumulate realized P&L on close (existing + new), never overwrite. Always set closed_at.
- Atomic claim to prevent double-sells: `UPDATE ... SET status='closing' WHERE id=? AND status='open'`. Sweep rows stuck in 'closing' > N min.

## E6. Ghost fills (settlement can revert)
- Matching is off-chain (ms); settlement is on-chain (Polygon) and can FAIL/revert (proxy traps, balance drains, allowance revocations, Gnosis Safe nonce bumps).
- Treat off-chain MATCHED as PROVISIONAL until on-chain confirms. Keep risk limits on unconfirmed exposure. Do not hedge/offset a MATCHED-but-unconfirmed fill.

## E7. Pre-signed ladder + hot path (speed)
- Background loop (off the hot path): compute the target bid ladder for the current count and the next 1-2 plausible counts, build + SIGN, hold in memory, refresh every few seconds. Caveat: the V2 ms timestamp is set at signing and the server rejects stale orders. Authenticated requests expire past ~30s clock drift, so treat ~30s (or tighter) as the max pre-sign horizon: sign just-in-time and refresh continuously. Keep the VPS clock UTC + NTP-synced. Benchmark the exact order-timestamp window before relying on it.
- Hot path (on a streamed tweet): look up the pre-signed set for the new count, batch-cancel now-stale orders (one cancel-all-in-market), submit the ready orders. No compute, no signing, no logging, no JSON building on this path. Clone the pre-built request and send. Set TCP_NODELAY on the socket.

## E8. Exits (the SELL path)
- Exits (stop-loss, trailing, take-profit) run unconditionally every cycle and BEFORE the circuit-breaker check.
- An exit places a real SELL via the executor and marks closed only after the SELL fills. Route SELLs to close_position / partial_close_position, never open_position. SELLs bypass entry gates (edge, EV, spread, liquidity) but respect the breaker + paper mode. A SELL sizes as "100% of THIS position", not "100% of bankroll".

---

# PART F: Strategies

## F1. The module contract (BaseModule)
- Override: get_handle ('elonmusk' or '' for handle-less modules), get_platform ('x'), get_config, save_config, get_display_keywords, get_auction_window_days, get_config_schema (drives an auto-generated settings form), and the evaluate method.
- Auto-register: a registry scans `api/modules/`. Adding a strategy is drop-in (create the folder, implement BaseModule). No engine/router edits; never hardcode a module name or handle in the engine.
- Config in the settings table keyed `module_config:{module_id}`. Missing row -> DEFAULT_CONFIG. PUT endpoints MERGE incoming fields into the stored config, never overwrite.

## F2. S2 Basket-Hold (BUILD FIRST)
Goal: rest patient maker bids on the few brackets around the projected count, buy on dips below fair value, hold to resolution.
- Each slow cycle and each hot-path tweet, for the current live Elon auction: (1) fetch live brackets from Gamma, drop resolved/closed; (2) get the current in-window count; (3) run the pacing model for projection + sigma; (4) build the bracket probability distribution (D3); (5) pick the top 2-3 brackets by probability around the projection.
- For each chosen bracket, set a target maker BID a small margin BELOW fair value (fill only on a dip, capture edge). Size via fractional Kelly (D4), capped, enforce the aggregate price ceiling (< 0.65).
- Place post-only GTC limit bids. Refresh/reprice on each tweet via the hot path. Hold to resolution.
- SALVAGE EXIT (recommended, capital efficiency): on the slow path, if a held bracket's fair value falls below ~0.03 (clearly dead), place a post-only SELL to recover remaining equity and recycle collateral into concurrent auctions.
- Config keys: kelly_fraction (0.25), max_bet_pct (0.15), aggregate_price_ceiling (0.65), num_brackets (3), bid_margin_below_fair, min_edge_threshold (0.02), slippage_tolerance, salvage_exit_threshold (0.03), take_profit_pct (off), stop_loss_pct (off).

## F3. Copytrader (BUILD FIRST) - OPTION B (maker-quoting)
DECIDED 2026-07-03: copytrader is a MAKER-QUOTING module, not a fill-mirror. It uses a proven market-maker whale (0xd218e474 ~+16% ROI, or 0x63d43bbb ~+10%) ONLY as a market/bracket SELECTOR + confidence signal (which markets/brackets a profitable MM is active in), then quotes its OWN two-sided post-only limits around fair value on those markets, capturing spread + maker rebate. It does NOT rest a passive bid at the whale's fill price (that is adversely selected: you fill only when the market moves against the whale = catch losers, miss winners). This keeps it maker-native and largely shares the market-making logic with S2; the whale just tells it where to point.
- Whale-performance gate: auto-bench a whale if its last 10 closed trades ROI < -30%. Ignore NegRisk 0-cent wallets. Do NOT copy the persistent sub-50-cent "signal-zone" wallets (they lose 46% to 100%).
- If any per-whale fill tracking is stored, dedupe with a UNIQUE index on (wallet_id, whale_trade_id); a skipped item must log a DISTINCT action (never 'mirrored') or the index gets poisoned.

## F4. Future strategies (framework only; do not implement yet)
- S4 Finish-Line Arb (gated on July 9 backtest): buy mispriced brackets in the final hours before close. Mostly maker (rest a bid below fair); only a true simultaneous complete-set arb would take. Guardrails: skip if a tweet landed in the last N seconds or the count sits on a bracket boundary; oracle-lag haircut; ghost-fill provisional.
- S5 Post-Resolution Sweeper (ON HOLD): rest a 0.99+ maker bid to sweep the near-certain winner right after the noon-ET close. Trigger = the tweet-count buffer: sweep only when (distance from count to nearest bracket boundary) > (plausible remaining tweets from Elon's burst rate) AND the window is within seconds of closing.
- S1 Pace-Scalp and S3 Anchor+Harvest: also gated on July 9. CUT and do not build: "Spike Lottery".

---

# PART G: Risk and safety

## G1. The risk gate (every order passes through)
- Position limits: <=15% of bankroll in one market, 50% total, 30% correlated. Loss limits: daily 5%, weekly 10%, drawdown 15% from peak. ALL checks FAIL CLOSED on any DB error / missing data.
- Real checks (no stubs): spread check (reject if spread > slippage_tolerance or no data), depth check (reject if order > 30% of book depth or no data). Read prices from Gamma bestBid/bestAsk.
- Risk state pre-warmed at engine BOOT before the first cycle. Empty daily P&L = "no constraint", never "block all". Hot path uses a fast cached version; recompute fully on the slow path.
- SELL orders bypass entry gates but respect breaker + paper mode; a SELL sizes as 100% of THIS position.

## G2. Circuit breaker
Trips after 5 consecutive losses, 60-min cooldown, auto-pause new entries, alert, auto-reset. Persist win/loss counters to the settings table and reload on boot.

## G3. Live-money guards
- Real trading requires BOTH: module status 'active' AND env backstop `ALLOW_LIVE_TRADING=true` with `ENVIRONMENT=production` and `PAPER_MODE=false`. LiveExecutor must raise if in paper/non-production and must refuse to run without valid Polymarket credentials.
- Module statuses: active, paper, inactive. A single DB flip to active must NOT enable real money; the env backstop is the second lock.

## G4. Kill switch + pause
- Pause: stop new entries, keep exits firing, do NOT liquidate. Kill (CLI only, protected): close all positions. WARNING: always read a handler body before calling anything named stop/cancel/kill/reset (an old /stop was a kill switch). Prefer a process-level restart over destructive endpoints.
- An external, process-level kill switch must exist. Auto-stop + auto-QA fires when P&L bleeds past a limit.

---

# PART H: Data and persistence

## H1. Supabase tables
- Per-module: positions, signals (JSONB metadata + explicit status generated/deferred/approved/rejected), trades, orders (metadata column), pending_signals.
- Observational/shared: price_snapshots (unique module_id+bracket+snapshot_hour), order_book_snapshots, post_count_snapshots, elon_tweets, daily_pnl, calibration_log.
- Control: modules (budget column + status), settings (JSONB config incl breaker counters + Slack kill switch), logs (metadata JSONB with tracebacks).
- Unique partial index on (module_id, market_id, bracket) WHERE state IN ('WAITING','MONITORING') to block dup/race inserts.

## H2. Migrations
Forward-only numbered SQL, applied to prod Supabase via the authenticated SQL editor BEFORE any code references the new table/column. A missing table + swallowed exception silently drops writes for days.

## H3. Retention + archive
Daily cleanup 03:30 UTC; weekly archive Sunday 03:00 UTC to `_DataMetricPulls/historical/supabase_archive/`. Live windows: price_snapshots 180d, post_count_snapshots 90d, order_book_snapshots 30d, logs 14-30d, pending_signals 7d. Archive before deleting anything live code reads.

## H4. Canonical data (backtests only)
All backtests read only from `_DataMetricPulls/canonical/` (posts, auctions, prices; partitioned handle+month). Every timestamp dual-stored (UTC + ET). Filter posts to counts_for_auction=true, auctions to confidence in (high, medium).

---

# PART I: Infrastructure and deployment

## I1. Network stack (Dublin, gated)
- Optional VPS in AWS eu-west-1 (Dublin), ~2ms from London (eu-west-2). Bypasses the geoblock (UK + US datacenter IPs blocked; Dublin allowed). Only needed for a microsecond FIFO race (crypto sweep).
- Warm keep-alive pooled HTTPS to the CLOB (cold ~85ms, warm ~23ms) with TCP_NODELAY. Local caching DNS resolver (dnsmasq/systemd-resolved) so lookups are <1ms.
- Cloudflare Worker proxy (boot-time httpx monkey-patch, env POLYMARKET_PROXY_URL + POLYMARKET_PROXY_KEY): READS ONLY as of 2026-07-06 - order POSTs through it get the region 403 (see PART M). Keep it for Gamma/xTracker/CLOB reads from geo-awkward hosts; do not rely on it for trading.

## I2. Railway services + deploy
- API + worker services each deploy from a GitHub repo. Deploy by git push to master (production, no preview env). Verify it landed via the Railway dashboard + Supabase log behavior, not just a merge.
- Healthcheck `GET /api/healthz` must stay UNAUTHENTICATED (auth makes Railway run stale code while "Online"). Returns {status: ok, running: true}.

## I3. Environment variables (names only, no secrets)
- Wallet: POLYMARKET_API_KEY, POLYMARKET_SECRET, POLYMARKET_PASSPHRASE, POLYMARKET_PRIVATE_KEY, POLYMARKET_WALLET_ADDRESS, POLYMARKET_SIGNER_ADDRESS.
- Database: SUPABASE_URL, SUPABASE_SERVICE_KEY, NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY.
- Live guards: ENVIRONMENT, PAPER_MODE, ALLOW_LIVE_TRADING.
- Feeds/proxy: TWITTERAPI_IO_KEY, POLYMARKET_PROXY_URL, POLYMARKET_PROXY_KEY, POLYGON_RPC_URL. Alerts: SLACK_WEBHOOK_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID. Real values only in ~/.credentials/shared.env + the Railway/VPS dashboards.

## I4. Observability + alerting
- Health states from real runtime: TRADING (a trade in 24h), CYCLING (cycles, no trades, no errors), STUCK (errors or 0 cycles). Expose `GET /api/engine/health?module_id=X` per module.
- Daily heartbeat to Telegram/Slack at 9 AM + 5 PM ET, every day regardless of health (a MISSING message means the bot is dead). Persist every generated signal with an explicit status; measure liveness by per-cycle decision-log rows, not the signals table.

## I5. API rate limits + the multi-wallet decision (verified 2026-07-03)
- Verified Polymarket limits: POST /order and DELETE /order allow ~3,500-5,000 requests per 10-second burst and tens of thousands per 10 minutes (~60-500/s); batch order endpoints ~1,000-2,000/10s. Over-limit = THROTTLED (queued), not rejected. WebSocket = 5 concurrent connections PER IP.
- DECISION: do NOT use multiple wallets to beat rate limits. Our maker bot uses well under 1% of a single wallet's limit, so limits never bind. Multiple wallets fragment capital (each needs pUSD + gas), split our FIFO queue position, and complicate P&L. Use sub-wallets ONLY for (a) per-strategy risk isolation (optional) and (b) the future crypto sweep (FIFO queue-position sharding). The only real per-IP ceiling is the 5-WebSocket limit; add IPs, not wallets. If real throughput is ever needed, upgrade the Builder Program tier (Verified/Partner).
- Wrap every external call (Gamma, data-api, CLOB) in retry with exponential backoff (0.5/1/2s) + a short cache.

---

# PART L: Live Dashboard (TradingView-style terminal)
Read-only web terminal to watch everything in real time. NEVER places orders. Next.js + TradingView's open-source lightweight-charts.
- Panels: (1) per-bracket price charts (line/candle) from price_snapshots + the live CLOB WS; (2) live order-book depth per bracket; (3) OUR resting orders overlaid on the book; (4) positions + unrealized/realized P&L; (5) live fills tape; (6) per-module cards with health (TRADING/CYCLING/STUCK) + start/stop toggles (active/paper/inactive) + model projection/fair value/edge per bracket; (7) engine cycle heartbeat + circuit-breaker state.
- Data path: reads Supabase + a lightweight WebSocket relay from the API service pushes live book/fill updates to the browser (real-time without hammering the DB).
- Access control: behind Supabase auth (a login), not public (it shows wallet P&L).

# PART M: Hosting decision (CORRECTED 2026-07-06 - verified by live test)
- **Railway CANNOT place orders from ANY of its regions.** Verified 2026-07-06 with a real signed post-only order: Railway europe-west4 (Amsterdam = Netherlands, a Polymarket-restricted country) returns the region 403. us-west/us-east are US (blocked); asia-southeast1 is Singapore (blocked). The old "Railway Amsterdam is good enough" line is FALSE for trading.
- **The Cloudflare Worker proxy no longer bypasses the ORDER geoblock** (verified 2026-07-06: signed order POST through the worker from a US client returns the region 403). It still works for reads (Gamma/xTracker/CLOB GETs). Treat the worker as a read proxy only.
- **Live trading therefore REQUIRES a host in an allowed country from day one: the Dublin VPS (AWS eu-west-1, Ireland) is no longer optional/gated - it is the execution host.** Railway remains fine for the recorder, alerter, dashboard, and any read-only worker.
- Everything up to Step 4 (paper) runs anywhere; Step 2's live rest/cancel acceptance and Steps 5+ live execution run on the Dublin box.

# PART N: Additional pre-build items (gaps closed 2026-07-03)
- Paper vs production isolation: run paper against a SEPARATE Supabase project (or schema), so paper never competes with the live engine for jobs/rows.
- Redemption/claim flow: winning shares must be redeemed on-chain to become spendable pUSD (costs Polygon gas). Build a redemption job + keep a gas (POL) reserve. Ignore 0-dollar losers (redeeming only burns gas).
- Capital/funding plan: set the starting bankroll in pUSD + a gas reserve; all risk caps compute off the bankroll setting. Fund the BOT wallet, wrap USDC.e -> pUSD.
- Concurrent auctions: handle multiple live Elon auctions at once (2-day/7-day/monthly); pick the right auction per strategy (freshest for entry); resolve per market_id.
- Key security on any VPS: secure the private key + pre-signed orders (restricted access, secrets manager, no plaintext in the repo).

# PART O: Future - crypto sweep + Rust hot path (deferred, gated)
- The 3-second sweep on crypto Up/Down (BTC/ETH) slots in as a new module easily, BUT needs (1) its own ingestion (Binance/Coinbase price feed + resolution clock) and (2) the microsecond speed stack.
- For that: port ONLY the hot-path execution worker to Rust (polymarket_client_sdk_v2 or polyfill-rs) on the Dublin VPS (a FIFO race is where Python's 15-40ms loses). The rest stays Python.
- Gated: build only after the July 9 L2 backtest proves the speed/overreaction edge survives realistic spread + fee fills.

---

# PART J: Build plan, testing, acceptance

## J1. Build sequence (each step has an acceptance test)
- **Step 1 - Skeleton**: repo layout, BaseModule, the auto-discovery registry, the Supabase schema (all migrations). ACCEPT: app boots, registry discovers an empty demo module, `GET /api/healthz` returns 200.
- **Step 2 - Execution core**: CLOB V2 signer (exchange domain 2, ms timestamp, pUSD), post-only placement, the heartbeat daemon, the fill poller + on-chain reconciliation. ACCEPT: on a test wallet, place a post-only limit far from the market, see it rest, cancel it, confirm via the user WS.
- **Step 3 - Data + brain**: Gamma discovery, slug window parsing, the tweet counter, the pacing model. ACCEPT: for a live auction, print the current count, projection, and a bracket probability distribution summing to 1 with impossible brackets at 0.
- **Step 4 - S2 + Copytrader in paper**: both modules + the risk gate, in paper. ACCEPT: both emit orders that pass the risk gate and fill in the paper executor, with positions + P&L written correctly.
- **Step 5 - Speed**: Dublin VPS (or Railway Amsterdam), TwitterAPI.io stream, warm pool, local DNS cache, the pre-signed ladder background loop + the hot path. ACCEPT: a tweet triggers a cancel-and-fire round trip in well under 1 second, measured.
- **Step 6 - Observability + safety**: health, alerts, circuit breaker, dual live guard, external kill switch. ACCEPT: forcing 5 paper losses trips the breaker; the daily heartbeat arrives; flipping only the DB flag does NOT enable real money.
- **Step 7 - Go live small**: pass the round-trip real-trade test, then run maker-only at micro size. ACCEPT: a real signal goes signal -> risk -> order -> fill -> position -> SELL -> realized P&L on the live instance.
- **Step 8 - After July 9**: add S4 + the speed strategies only if the L2 backtest proves the edge survives realistic fills. S5 stays on hold.

## J2. Testing rules
- "Working" = a completed round-trip real trade on the live instance, NOT a green code pipeline.
- Paper mode simulates fills at the limit price, never touches the CLOB; a paper BUY fills only when best_ask <= the limit.
- Before any live size, run a shadow foretest: log model vs market at the 50% window mark, score at resolution; promote only if the model holds up over 15-20 fresh markets.

## J3. Open questions to resolve during the build
- Pre-signed order staleness: confirm the exact V2 order-timestamp validity window (anchor ~30s auth clock-drift; benchmark it) - decides how far ahead we can pre-sign.
- Real maker fill-rate in thin tweet books; how many concurrent resting quotes the bankroll can fund (pUSD + gas); VPS key security; the ToS decision on the geoblock bypass.

## J4. Appendix: verified contract addresses + endpoints + constants
- **Verified contract addresses (PolygonScan + docs.polymarket.com, 2026-07-03; verify on PolygonScan before wiring - a widely-shared report had a WRONG CTF address 0x4D97Df0726...):**
  - V2 CTF Exchange: `0xE111180000d2663C0091e4f400237545B87B996B`
  - V2 Negative Risk Exchange: `0xe2222d279d744050d28e00520010520000310F59`
  - pUSD token: `0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB`
  - Conditional Tokens Framework (CTF): `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045`
- **Endpoints**: clob.polymarket.com; wss://ws-subscriptions-clob.polymarket.com/ws/market; gamma-api.polymarket.com (/events?tag_id=972, /series?slug=elon-tweets-48h); data-api.polymarket.com (/trades, /positions, /value, /activity); xtracker.polymarket.com.
- **Constants**: Elon user id 44196397; Gamma tag 972 (Tweet Markets), 282 (Elon); Supabase ref xdonwowgqvmtrduikaon; Polygon chain id 137. Wallets: BOT `0xD0f99f553bC376E8b86246295d679dC86334d400` (POLYMARKET_* env); MANUAL `0x2eEF3A...8eAca` (POLY_MANUAL_* env).

## K. External-AI QA outcomes (2026-07-03)
- ADOPTED: absolute cent-based copy-trade drift (2c not 10%); S2 salvage exit; matching-engine restart handling (HTTP 425 + 2-min post-only window); ~30s pre-sign horizon + UTC clock; TCP_NODELAY.
- FLAGGED then DECIDED: copytrader adverse selection -> Option B (maker-quoting, see F3).
- REJECTED (already decided): Rust hot-path rewrite for the maker bot (deferred to the crypto sweep only, Part O); UDS/SHM local IPC (hot path is one in-memory process; recorder writes parquet not Supabase; use the Supabase pooler for the slow path).
- N/A / already in spec: dynamic taker fee (maker-only = zero fee); struct asymmetry (already in E2).
