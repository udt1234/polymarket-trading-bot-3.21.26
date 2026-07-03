# Shadow Foretest — 2-day Elon calibrated pace edge

Forward (out-of-sample) test of the one edge that survived backtesting: on **2-day**
Elon tweet-count markets, at **~50% of the window**, the calibrated pace model called
the winning bracket **77% vs the market's 55%** (backtest, n=22). This harness checks
whether that holds live. No capital, no orders — it only logs and scores.

Harness: `scripts/recorder/shadow_foretest.py`

## How it works
- **Model dispersion** is learned from realized 2-day projection errors (historical
  auctions, X-API counts). At the halfway mark: `proj = count_so_far / 0.5`, predictive
  final `= proj * {historical ratios}`, bracket prob = share of samples landing in it.
- **Prices** are pulled LIVE from the Polymarket CLOB order book at snapshot time
  (per-bracket YES best bid/ask -> mid). Bracket->YES-token map comes from the
  recorder parquet (token IDs are stable). Falls back to the recorder slice if CLOB
  is unreachable.
- **Count** comes from the X-API (locked rule). Default reads the local parquet (stale
  past its last pull); `--pull` does a small cost-guarded live fetch (~$0.005/tweet).
- Each snapshot logs model vs market argmax + disagreement bets to `shadow_log.parquet`.
  `--score` joins logged snapshots to resolved winners and prints the running tally.

## Run it live (the two refresh steps + snapshot)
```
# 1) refresh recorder prices off Railway (free; needs the recorder URL + token)
python scripts/recorder/pull_and_merge.py --url https://<recorder>.up.railway.app --token <RECORDER_TOKEN>

# 2) see which 2-day markets are live and their elapsed %
python scripts/recorder/shadow_foretest.py --list

# 3) snapshot a market that is ~50% elapsed, WITH live count (small X-API spend ~$1)
python scripts/recorder/shadow_foretest.py --snapshot <slug> --pull

# 4) after the market resolves, score it (re-run any time; accumulates)
python scripts/recorder/shadow_foretest.py --score
```

## Hands-free (already scheduled)
Windows Task `ElonShadowForetest` runs `scripts/recorder/run_shadow_auto.bat` every 12h
(8am/8pm), calling `--auto`: it snapshots any live 2-day market at 40-70% elapsed that
isn't already logged in the last 18h. Output appended to `auto_run.log`. Count = your
IFTTT sheet (free), prices = live CLOB (free) — no paid X-API, no Railway token needed.
Only runs while the PC is on; move the .bat to the cloud recorder for 24/7.
NOTE: `--auto` only sees markets already in the local recorder parquet; pull the recorder
(or add Gamma discovery) so brand-new markets get their YES-token map.

## Promotion gate (before risking any capital)
Hold the snapshot for ~15-20 fresh 2-day markets. Only promote to micro-size live
trading if the live **model argmax-picks-winner rate stays clearly above the market's**
(target ~70%+ vs ~55%), maker-fills only. If it collapses to parity, the backtest edge
was small-sample noise — stop.
