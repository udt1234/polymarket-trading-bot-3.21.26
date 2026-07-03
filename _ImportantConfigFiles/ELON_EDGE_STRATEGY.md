# Elon Tweet-Market Bot: Strategy + Build Spec (2026-07-02)

Self-contained writeup for building the Elon tweet-count bot. Distilled from the 2026-07-02
session. Companion sheet tabs (in `1AV_vIsxLIzTivNE_EshZbh-y7QKxLa7MIy1hNJMbAf8`): **Elon Pacing**
(the pace/fair value), **Elon Edge Layer** (the buy/hold/lean signals), **Strategy Walkthrough**,
**Pacing Models (Plain English)**.

## 0) THE HEADLINE (read this first)
- **The Elon tweet market is EFFICIENT on every axis we tested.** We CANNOT out-forecast it,
  out-race it, or arb it. The edge is NOT a better pace number.
- **So the edge MOVED**: from "predict the count better" (dead) to **structure**: hold a basket
  bought at dips, lean on early disagreements, harvest maker rebates, and point the engine at
  DUMBER markets. Same pace, new edge.

## 1) WHAT WE TESTED AND KILLED (all on real L2, honest, walk-forward)
| Edge idea | Result | Verdict |
|---|---|---|
| Complete-set ARB (best-ASK sum) | median set costs $1.03-1.04; 0.85% of min < $0.99 | DEAD |
| SPEED (front-run the tweet) | market reprices in ~300ms, 61% of move in 1s, trade in 0.3s | CAN'T WIN |
| OVERREACTION / FADE (1-min) | ~51% revert (efficient) | NO EDGE |
| PACE RECONSTRUCTION (fade the market's own overshoot) | causal revert-corr +0.037 (a leaky centered-window version faked 89% - caught it) | NO EDGE |
| EARLY-BURST regime modifier on Kalman | over-projects, MAE 46.6 vs plain Kalman 35.0 | HURTS |
| **KALMAN vs MARKET divergence** | **Kalman closer to actual 58% when they disagree; Kalman-fav beats market-fav EARLY (20% vs 16%)** | **SMALL EDGE (early only)** |

Backtests (all in `_DataMetricPulls/pacing_backtest/`, obey `BACKTEST_RULES.md`):
`l2_edge_backtest.py` (arb+fade), `l2_speed_backtest.py` (speed), `pace_reconstruction.py`
(reverse-pace), `regime_test.py`, `divergence_test.py`, `layered_pacing_test.py` (model compare).

## 2) THE TWO FAIR-VALUE TOOLS (the brain)
- **Kalman pacing (ours):** projects final count from the live count + walk-forward priors.
  Best model = **Kalman + Particle-Filter ensemble (Ens_KPF)**, best-calibrated (Brier ~0.37).
  Grounded in the ACTUAL tweet count. `layered_pacing_test.py`.
- **Reverse-pace (the market's):** invert the live bracket prices into the market's implied final
  count. Formula recovered for Elon: `implied ~= 0.38*count + 0.46*naive_pace + 25`, R^2=0.75
  (Elon-specific; the METHOD transfers, each market recovers its own formula). `pace_reconstruction.py`.
- On Elon the two ~= each other ~= the true fair value. Use both: agreement = confidence;
  disagreement early = the lean signal.

## 3) THE STRATEGY (what the bot actually does)
The bot is a **patient holder + dip-buyer + rebate-harvester**, NOT a fast predictor.
1. **S2 Basket-Hold (core):** pick the 2-3 brackets around the consensus fair value (the HOLD
   band). Accumulate each ONLY when its live price is BELOW its fair value (a dip), via limit
   orders. Hold to resolution. Profit = $1 - (band cost); +EV only if you buy the band below its
   fair sum. NOT a guaranteed win unless you own the full set < $1 (rare).
2. **Early-disagreement lean (the edge):** in the first day (>24h left), when the price disagrees
   with Kalman, tilt toward Kalman's bracket (right ~58% of those; edge fades mid/late as the
   market takes over, so shrink size as the clock runs down).
3. **Maker LP rebates (structural income):** rest limit orders near mid to earn the maker rebate
   + LP reward. The #1 risk is ADVERSE SELECTION (resting quotes get picked off within ~300ms of
   a tweet). Guard: cancel/re-quote the instant a tweet moves Kalman's fair value past your quote.
4. **Sizing:** fractional Kelly (0.25x) off the consensus edge, capped 10%/bracket. Trust the
   signals most early; the market wins late.

Do NOT build for tweets: the speed stack (Dublin VPS, streaming tweets, warm pool). It cannot
beat 300ms. Speed only pays for the deterministic crypto post-resolution sweeper (S5), separate.

## 4) THE EDGE SIGNALS (sheet: "Elon Edge Layer" tab, live off Elon Pacing rows 29-38)
- **Model-implied final** vs **Market-implied final** -> **Divergence** -> **SIGNAL** (LEAN
  UP/DOWN/ALIGNED).
- Per bracket: **Live Price** vs **Fair (our model)** -> **DIP BUY** flag (price > 2c below fair)
  and **HOLD band** flag (model prob >= 5%).
- The bot reads the same logic: fair value = anchor, buy dips in the band, lean early on divergence.

## 5) BOT ARCHITECTURE NOTES (reuse the module pattern in MODULE_ARCHITECTURE.md)
- Module `api/modules/elon_tweets/`: `module.py` (BaseModule), `data.py`, `decision.py`,
  `module_config.py`. Shared math in `api/modules/shared/` (pacing, reverse-pace, sizing).
- Decision loop per cycle: compute Kalman/Ens_KPF projection + reverse-pace implied -> band +
  divergence -> for each band bracket, if live price < fair - margin AND sized-Kelly > floor,
  emit a LIMIT BUY at/below best; hold to resolution (no active sell unless a full-set arb prints).
- Maker guard: on each new tweet, recompute fair value; if a resting order is now on the wrong
  side of fair, CANCEL it (adverse-selection defense).
- Constraints (LOCKED): LIMIT orders only, never market. Maker-only / post-only preferred. Live
  trade requires PAPER_MODE=false + ENV=production + env backstop. All 15 risk checks fail-closed.

## 6) THE DATA (L2 repository - the asset that makes all this testable)
- `_DataMetricPulls/l2_history/` = durable full-depth L2 store. TWO sources, one schema:
  **pmxt** (free archive.pmxt.dev, COMPLETE tick L2 every market, Apr 13 2026+) + **our recorder**
  (Railway `tweet-recorder`, Jun 23+). 100% cross-checked. Read via
  `api.modules.shared.l2_history.read_l2()`. Kept current by daily tasks `PolymarketPmxtForward`
  + `PolymarketRecorderPull`. See memory `l2_history_repository`.
- Counts: X-API backfill `_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet`
  (counts_main_feed = the locked count rule: originals+quotes+reposts+self-replies).

## 7) CROSS-MARKET FUTURE (parked, do after Elon ships - the real upside)
- The reconstruction engine is market-agnostic. Elon is efficient; DUMBER markets are where it
  pays. Build a **weekly SCANNER** (reversion-corr across every bracketed Polymarket market ->
  ranked watchlist of inefficient crowds). Prototype: `scratchpad/reconstruct_other_markets.py`.
- Lead found: soccer PLAYER-PROP markets show mean-reversion (+0.22 to +0.28 vs efficient Elon
  +0.037). VALIDATE on real L2 depth before trusting (may be thin-book bounce). Baseball/weather
  aren't listed as brackets now (seasonal); the scanner catches them when live. See HANDOFF.md.

## 8) OPEN VALIDATION (small samples ~35 auctions / ~9 days L2)
- Re-run divergence + all L2 backtests once the pmxt backfill (Apr 13 -> Jun 22) completes (~8x data).
- Confirm the early-lean 58% holds; test the maker-rebate net (rebates minus adverse selection).
- Then: paper-trade S2 + early-lean on the live Elon module before any real money.
