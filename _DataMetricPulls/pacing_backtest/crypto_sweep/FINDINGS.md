# Crypto hourly Up/Down "last-seconds sweep" — backtest findings (2026-07-08)

Backtest-first evaluation of Sir's idea: in the final seconds of BTC/ETH/SOL/XRP
hourly Up-or-Down markets, buy the near-certain winner (>97%) to scalp 0.97→1.00.
Data: Gamma (400 resolved hourly markets, Jul 4-8) + pmxt tick L2 (96 markets, 24h).

## Verdict: do NOT build it live. Edge is thin, rare, fragile, adversely selected.

### Phase 1 — is the late favorite mispriced? (1-min bars, n=400)
- TAKER (lift the favorite at market price, ≥0.97): +$0.37/$100 at T-60s, **-$0.17/$100 at T-180s**. Efficient / dead. Confirms the KOL negative result + our efficient-market thesis.
- The favorite that dips to ≤0.98 in the FINAL MINUTE still won 100% (noise), but that same dip 3 min out LOSES (real flips). The edge, if any, lives only in the final ~60s. Sir's "last 3 seconds" instinct was directionally right.

### Phase 2 — real maker-fill sim on tick L2 (n=96, 24h, GENEROUS fills)
- **70% of markets have ZERO favorite-trades in the final 30s** — most of the time there is simply no seller to fill against near the close. Flow late = buying the winner UP to 0.999, not dumping it.
- Fill rate (rest a post-only bid, generous = any print ≤ bid):
  - bid 0.97: 1.1% (10s) / 5.7% (30s) / 10.6% (60s)
  - bid 0.99: 6.7% / 13.6% / 17.6%
- Win rate on fills: 100% in this window — BUT on 1-15 fills/cell, in-sample, one 4-day stretch. Not trustworthy as a win rate.
- EV/fill: +0.01 (bid 0.99) to +0.03 (bid 0.97). Expected profit ≈ **$0.20-0.32 per market at $100/bid**, generously.

### Why it fails the bar
1. **Rare fills:** you need a panic seller dumping a near-certain winner; that almost never happens (70% no late trades). Generous fills ignore queue position; real fills are LOWER — we sit behind co-located bots at 0.99 in the FIFO queue.
2. **Fat-tail ruin:** one late flip (a 0.97 fill that loses) = -0.97, erasing ~32 wins. The "100% win" is small-n; the strategy is one adverse fill from negative.
3. **Adverse selection by construction:** the rare seller dumping to you in the final seconds sometimes knows the candle is turning. This is the #1 maker risk our whole design warns about.
4. **Build cost vs payout:** needs a new crypto ingestion stack (spot feed + resolution clock) for ~cents/market with fat-tail downside.

### Reframe (what to do instead)
- Bank the one robust finding: final-60s dips on the near-certain winner are almost always noise that recovers.
- Higher-EV redirect: the PARKED cross-market reconstruction idea — player-prop / thin markets showed reversion +0.22 to +0.28 vs the ~0.01-0.03 here (≈10x the edge). That is where to point the effort.

## Update 2026-07-09 — corrected to TAKER ask-sweep + broadened to other markets

Sir clarified: (1) last 3 SECONDS not minutes; (2) the sweeper mechanic is TAKER
(lift cheap asks below fair), not maker; (3) find OTHER daily markets (sports,
weather, etc.). Redone at tick level across market types (`phase3_ask_sweep.py`,
`phase4_endgame_sweep.py`, `phase4b_sports_endgame.py`).

**The unifying wall (why the mechanical 3-second sweep fails):**
- **Crypto hourly + daily (hard clock):** in the final 1-3s the favorite's
  best_ask sits at **1.000 for ~100% of markets** — there is NOTHING below par to
  lift. The cheap asks that exist at 5s+ are gone by 3s (faster bots). Dead.
- **Weather NYC (hard noon clock, n=70):** 67% of markets DO have a sub-par ask
  late, but they are **adversely selected** — cheap because the outcome is
  genuinely uncertain. Sweeping all sub-par asks: 96% win but **-$2.79/$100** (the
  deep-discount tail loses). A near-certain outcome does not trade at a discount;
  a discounted ask is discounted for a reason.

**Sports (the real candidate, MLB, high volume $0.5-2.7M/game):**
- Sports resolve on a fuzzy game-clock via BATCH UMA oracle, NOT a hard 3-second
  bell — so the "3-second sweep" mechanic does not apply; the play is "buy the
  decided winner during garbage time" over MINUTES (which actually SUITS us: no
  microsecond race).
- Direct tick probe of one blowout (col-lad): the winner had **16,439
  observations with cheap asks 0.91-0.99** while its bid was ≥0.90 (decided). This
  is genuinely DIFFERENT from weather — the game is truly decided, so those cheap
  asks are real retail cash-out, NOT adversely selected. Structural precondition
  for a +EV sweep EXISTS.
- NOT proven: a clean cross-game banded-EV number. The newest games' batch
  closedTime lags actual game-end by hours, so automated pmxt file-windowing
  misses them. Needs either forward-recording sports (like the Elon recorder) or a
  game-end timestamp source, then a clean backtest.

**Verdict:** the mechanical last-3-seconds sweep is DEAD on hard-clock markets
(crypto par-asks; weather adverse selection). The only place the sweeper edge
plausibly lives is SPORTS blowout garbage-time (decided game + real cheap retail
liquidity), a slower minutes-long play that fits us but is high-volume/contested
and not yet EV-proven. Recommended next step: forward-record sports order books
for ~2 weeks, then run the banded backtest on clean data (backtest-first).

Scripts: `phase1_efficiency.py`, `phase2_maker_fills.py`, `phase3_ask_sweep.py`,
`phase4_endgame_sweep.py`, `phase4b_sports_endgame.py` (durable, re-runnable).

## Update 2026-07-10 — MLB garbage-time sweep CONFIRMED +EV (real trades + fees)

`phase5_mlb_slate.py` (multi-day), `phase6_realistic_fills.py` (real executed
trades + real sizes + real fee + maker/taker split).

**Fee (verified vs Polymarket docs):** sports taker fee = `shares * 0.05 * p * (1-p)`,
takers only, makers $0. Tiny at the extremes we trade (~$0.05-0.19 per 100 shares).

**Realistic backtest (buy REAL cheap trades on decided favorites, bid>=0.95):**
- 2 dates: +2.35% ROI net of fees ($11,246 vol, fees only 0.16%), 28/29 games
  profitable, but one collapse game = -$36.55 (the fat tail is real).
- 1 date (07-08): TAKER +3.05% ($6,023 vol), 15/15 games profitable.
- Band pattern holds: deep discount (0.95-0.98) is where the edge lives; buying
  the 0.99 "sure thing" is break-even/negative (fat-tail collapses).

**EV = win_rate - price.** Decided MLB favorite truly wins ~98%; buy at 0.96 =>
+2%, buy at 0.99 => -1%. That is the whole edge.

**MAKER vs TAKER (Sir's question):** rest a post-only bid vs lift the ask.
- MAKER (seller crosses into our bid, $0 fee): +3.49% ROI, but only ~24% of the
  volume (only taker-SELL flow is maker-capturable; 76% of cheap fills were
  takers lifting asks, which a resting bid can't catch).
- TAKER (lift cheap asks, pay tiny fee): +3.05% ROI, full volume.
- Both +EV. Maker fits our maker-only design + is fee-free but captures ~4x less.

**Fat tail:** a "decided" favorite (bid 0.95) still collapses ~3% of games; one
loss ~-0.96 erases ~30-50 small wins. Size for it; prefer deeper "decided"
threshold (bid>=0.97) to cut collapses.

**Logger LIVE:** `infra/mlb-recorder/` deployed on Railway EU
(polybot-mlb-recorder, volume /data) capturing tonight's slate tick L2
(~6k events/30s) to our own parquet - forward clean data for OOS confirmation.
