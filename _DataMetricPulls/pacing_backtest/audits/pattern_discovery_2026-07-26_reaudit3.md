# Audit log: pattern_discovery_2026-07-26 (re-audit #3, FINAL)
**Auditor:** `@backtest-auditor` (fourth pass). **Date:** 2026-07-29.
**Verdict history:** FAIL -> WARN -> WARN -> **PASS**.
**Scope:** (b) pure forecast-accuracy / calibration diagnostic. No P&L, no fills.
**Pre-registration:** `_DataMetricPulls/pacing_backtest/prereg/pattern_discovery_2026-07-26.md`

> Transcribed verbatim from the auditor's returned report. The auditor's own Bash write was denied by the permission system and it had no Write tool in session, so the orchestrator persisted the content unaltered. Analysis, figures and verdict are the auditor's.

## VERDICT: PASS

Both items from re-audit #2 are confirmed fixed by independent recomputation, not by trusting the builder's change-log. No fatal finding. One LOW/advisory schema-hygiene note is recorded but does not block.

## Reproduced headline number: YES (exact)

Rebuilt `compute_skill_table`'s logic from scratch in a standalone script against `per_row.csv` (not copied from the runner):

| target | n_full | n_b4_admissible | PRIMARY (B4) verdict, mine | PRIMARY, reported |
|---|---|---|---|---|
| elon_2day sealed | 28 | 19 | NONE, best is M7(M6) unproven, skill=-0.0953 CI[-0.2394,+0.0427] | NONE |
| trump_7day sealed | 20 | 20 | NONE, all LOSE/unproven | NONE |
| elon_7day sealed | 19 | 3 | M7(M6) BEATS, skill=+0.2597 CI[+0.0032,+0.7573], jk_full=+0.2597, jk_drop=+0.0109 | M7(M6), gated to sentinel per Finding 2 |

Every line (~80) in summary.md's Headline tables for elon_2day and trump_7day sealed matched my recompute to 4 decimals. The elon_7day BEATS line was re-derived down to the 3 raw per-auction skill values (may-29-june-5: +0.018645, june-2-june-9: +0.003214, june-5-june-12: +0.757317), matching the disclosure text exactly.

## Findings

### [CLASS D] Item 2 (n-floor): CONFIRMED FIXED
`SUCCESS_N_FLOOR = 10` at `pattern_discovery_2026-07-26.py:65`. `_headline_flag` (lines 841-857) gates `n_for_gate = n_auctions_b4_admissible if baseline=="B4" else n_auctions_total`, returns the sentinel before building any method list, and is the sole producer of RUN_META's `primary_success_*` keys.

RUN_META diff vs `_prewarnfix2_backup_2026-07-29` shows exactly 2 hunks: the flag (list -> sentinel) and the `notes` field. summary.md diff shows exactly 3 hunks: the new floor-explainer paragraph, the PRIMARY line, and the corrected disclosure.

Verified the gate fires only where it should: elon_2day (n_admissible=19) and trump_7day (n=20) both report their real `NONE` verdicts ungated; elon_7day's SECONDARY/TERTIARY (n_total=19, above floor) also report real `NONE` ungated. Only PRIMARY (n_admissible=3) is gated. Nothing hidden: the raw skill/CI/jackknife row for the gated cell is still printed verbatim one section above.

**Residual, non-blocking:** `primary_success_*_beats_B4` is now polymorphic across four shapes (`"no_sealed_data"`, `"none"`, the noise sentinel string, or `list[str]`). Grepped the repo, no downstream consumer reads this JSON key today, so there is no live truthiness/iteration trap, but a naive `if field:` check is truthy for all four variants (the `"none"` string was already this way pre-fix). Recommend, non-blocking: replace with `{"status": "beats"|"none"|"noise"|"no_sealed_data", "methods": [...], "n": X}`. Severity LOW, zero live blast radius.

### [CLASS D] Item 1 (false "unchanged" claim): CONFIRMED FIXED against source, not against the builder's retelling
Pulled `_prereaudit_backup_2026-07-29/summary.md:325` directly and confirmed it literally reads `M7(M6) vs B4: skill=+0.2711 CI[-0.0056,+0.6654] n=3 -> unproven`, the exact "before" figure the correction cites. The "after" figure and the 35,029/225,039-row RNG attribution (carried from re-audit #2's own diff, still valid since `per_row.csv` is MD5-identical) both check out. The P=25% same-sign argument and jackknife collapse (+0.2597 -> +0.0109) reproduce exactly. No new false statement was introduced by the correction.

## Fresh re-verification this round (not carried over on trust)
- `per_row.csv` MD5 `1fceb62e273c19231d7f3ec5810f0ec7` identical on both runs; `diff -q` empty. Zero model recompute.
- `b4_admissible` gate: 0/781 B4 winner-rows mismatched (320 admissible / 461 inadmissible, matches summary.md's 59.0%).
- B4 non-renormalization: fresh partial-coverage auction (`elon-musk-of-tweets-january-15-january-17`), 9/10 brackets equal `market_price` exactly, sum approx 1.000001, not renormalized.
- THE WALL: `train_units = [u for u in units if u["s"] < wall_ts]` at lines 378/583, `priors = [p for p in units if p["e"] < u["s"]]` at line 410, present verbatim.
- `model_version` `"ensemble-cap1.5+calibsigma.2026-07-11"` equals `api/modules/shared/locked_pace.py:22` exactly. No drift.
- `trial_count`: 32+38+4+12+8+4+24+3 = 125, matches RUN_META exactly.
- Prereg mtime unchanged (2026-07-26 11:21:06.956665) across all four rounds.

## What could NOT be checked
- No git diff exists for the script (untracked). Relied on RUN_META/summary.md byte-diffs plus the `per_row.csv` MD5 match as indirect but strong evidence.
- Did not re-derive the root cause of the 63.6%/78.2% Elon winner-token price-coverage gap. Open, out of scope, carried forward from all three prior rounds.
- Did not independently confirm the builder's claimed 28.5s runtime with a timestamped log (the only log present times the prior round's 2588.9s cold recompute). Checkpoint pkl mtimes (all pre-dating this run's output) and the legitimate load-from-disk cache at lines 1111-1130 support the claim indirectly.

## What this PASS means and does not mean
It certifies the artifact is now internally honest and reproducible: every reported number reproduces exactly from `per_row.csv`, the one seed-sensitive flag is structurally (not just prose-ly) labeled noise, and the prior false claim about it is corrected and itself accurate.

**It does not mean "no tradeable pattern exists."** On the auctions the market actually priced (19/28 = 68% of sealed Elon 2-day, 20/20 = 100% of sealed Trump 7-day), no method beat the market. The other 9 Elon 2-day and 16 Elon 7-day sealed auctions where the market never priced the winner are untestable by this study's own PRIMARY criterion. Not confirmed efficient, not confirmed inefficient. An open question, not a result.
