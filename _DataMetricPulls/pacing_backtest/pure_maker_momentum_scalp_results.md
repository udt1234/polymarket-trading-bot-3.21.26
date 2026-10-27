# Pure-maker momentum scalp (spec) - run 2026-10-27T19:18:02.357575+00:00 git f1a8d85
NEEDS @backtest-auditor REVIEW BEFORE ANY NUMBER IS TRUSTED.
**Control:** CONTROL PROFITABLE under spec fills -> FILL MODEL IS FANTASY; headline NOT VALID

Window: 2024-06-14T20:20:16+00:00 -> 2026-06-05T05:31:22+00:00
Universe: 297 admissible auctions; used 273; instruments 4392 (liq>50k ever: 312)

| metric | spec | hardened | control(spec) | control(hardened) |
|---|---|---|---|---|
| breakouts pre-liq/ctrl elig | 29351 | 29351 | 364265 | 364265 |
| breakouts post-filter | 7122 | 7122 | 364265 | 364265 |
| filled | 347 | 334 | 927 | 889 |
| fill rate % (of breakouts) | 4.872 | 4.69 | 0.2545 | 0.2441 |
| win rate % | 60.23 | 59.28 | 75.84 | 74.69 |
| adverse sel rate | 0.3977 | 0.4072 | 0.2416 | 0.2531 |
| spread pnl | 14.63 | 13.86 | 49.21 | 46.48 |
| rebate pnl | 5.56 | 0 | 16.3 | 0 |
| resolution pnl | -19.08 | -18.8 | -62.37 | -62.11 |
| TOTAL | 1.114 | -4.936 | 3.136 | -15.63 |
| total ex-rebate | -4.446 | -4.936 | -13.16 | -15.63 |
| max DD $ | 2.226 | 4.936 | 3.007 | 15.63 |
| max DD % peak capital | 11.67 | 26.26 | 4.821 | 25.17 |
| excluded_n | 0 | 0 | 0 | 0 |
| n auctions w/ trades | 118 | 117 | 134 | 133 |

Spec by-auction CI/jackknife: {"n_auctions": 118, "total": 1.1140000000000008, "boot_ci95_total": [-2.997999999999999, 5.334224999999998], "mean_per_trade": 0.0032103746397694564, "jackknife_drop_best_auction_total": 0.46900000000000075, "best_auction": "elon-musk-of-tweets-february-3-february-10", "best_auction_pnl": 0.645, "ci_includes_zero": true}

Caveats: touch-fill/no-latency/no-queue under spec; hardened is strict-through + rebate 0 only (no queue haircut - UNVERIFIED).
Deviations: instrument = (auction file, _bucket) Yes-series; No prints mirrored as 1-price (files are per-auction, not per-contract); auctions with unparseable noon-ET slug window are excluded (reported), prints >= window end dropped; signals only at ts >= window start; pre-start prints used for lookback only; rebate +0.01/leg is the PRE-REGISTERED non-default; ex-rebate total reported alongside