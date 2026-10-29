# Pure-maker momentum scalp (spec) - run 2026-10-27T22:06:28.576448+00:00 git ac0b116
NEEDS @backtest-auditor REVIEW BEFORE ANY NUMBER IS TRUSTED.
**Control:** CONTROL PROFITABLE under spec fills -> FILL MODEL IS FANTASY; headline NOT VALID

Window: 2024-06-14T20:20:16+00:00 -> 2026-06-05T05:31:22+00:00
Universe: 297 admissible auctions; used 273; instruments 4392 (liq>50k ever: 643)

| metric | spec | hardened | control(spec) | control(hardened) |
|---|---|---|---|---|
| breakouts pre-liq/ctrl elig | 29351 | 29351 | 771577 | 771577 |
| breakouts post-filter | 13735 | 13735 | 771577 | 771577 |
| filled | 654 | 629 | 1799 | 1723 |
| fill rate % (of breakouts) | 4.762 | 4.58 | 0.2332 | 0.2233 |
| win rate % | 55.81 | 55.48 | 73.21 | 72.43 |
| adverse sel rate | 0.4419 | 0.4452 | 0.2679 | 0.2757 |
| spread pnl | 25.55 | 24.43 | 92.19 | 87.36 |
| rebate pnl | 10.19 | 0 | 31.16 | 0 |
| resolution pnl | -34.85 | -33.98 | -102.8 | -102 |
| TOTAL | 0.886 | -9.552 | 20.52 | -14.68 |
| total ex-rebate | -9.304 | -9.552 | -10.64 | -14.68 |
| max DD $ | 2.605 | 9.737 | 3.169 | 15.59 |
| max DD % peak capital | 249.3 | 991.5 | 87.18 | 448.6 |
| excluded_n | 0 | 0 | 0 | 0 |
| n auctions w/ trades | 152 | 151 | 165 | 164 |

Spec by-auction CI/jackknife: {"n_auctions": 152, "total": 0.8860000000000012, "boot_ci95_total": [-4.386024999999998, 6.439100000000001], "mean_per_trade": 0.0013547400611620803, "jackknife_drop_best_auction_total": -0.2699999999999989, "best_auction": "elon-musk-of-tweets-february-3-february-10", "best_auction_pnl": 1.1560000000000001, "ci_includes_zero": true}

Caveats: touch-fill/no-latency/no-queue under spec; hardened is strict-through + rebate 0 only (no queue haircut - UNVERIFIED).
Deviations: instrument = (auction file, _bucket) Yes-series; No prints mirrored as 1-price (files are per-auction, not per-contract); auctions with unparseable noon-ET slug window are excluded (reported), prints >= window end dropped; signals only at ts >= window start; pre-start prints used for lookback only; rebate +0.01/leg is the PRE-REGISTERED non-default; ex-rebate total reported alongside