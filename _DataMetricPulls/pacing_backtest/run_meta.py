"""RUN_META footer - the machine-readable provenance every backtest must emit.

Why: the @backtest-auditor can only deterministically check instruction-compliance
(class C) if each backtest declares what it actually ran. Without this, the auditor
has to grep 100+ inline literals and guess. With it, config/drift checks are a diff.

Usage at the END of any backtest, right after you print the headline number:

    from run_meta import emit_run_meta
    emit_run_meta(
        script=__file__,
        headline={"roi_per_100": 4.4, "n_auctions": 8},   # the number(s) you claim
        data_paths=[CANON + "/auctions/elonmusk", "pmxt L2"],
        window_basis="noon-ET from slug",                  # how the auction window was derived
        fills="maker post-only through-fill, real L2 depth, taker_fee=0.05",
        trial_count=1,                                      # configs swept to pick this result
        notes="",
    )

It stamps the LOCKED model version + git sha automatically and writes both a printed
block (so it lands in captured stdout / .out files) and a sidecar JSON next to the
script's output dir, which the auditor reads.
"""
import json
import subprocess
import sys
from pathlib import Path


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent, stderr=subprocess.DEVNULL,
            text=True, timeout=5).strip()
    except Exception:
        return "unknown"


def _model_version() -> str:
    """Pull the LOCKED model version from the single source of truth if importable."""
    try:
        root = Path(__file__).resolve().parents[2]  # repo root
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from api.modules.shared.locked_pace import MODEL_VERSION
        return MODEL_VERSION
    except Exception:
        return "unimported"


def emit_run_meta(script: str, headline: dict, *, data_paths=None,
                  window_basis: str = "", fills: str = "", trial_count: int = 1,
                  scope: str = "", notes: str = "", out_dir: str = "audit_out3") -> dict:
    """Build, print, and persist the RUN_META footer. Returns the dict."""
    meta = {
        "run_meta_version": 1,
        "script": Path(script).name,
        "model_version": _model_version(),
        "git_sha": _git_sha(),
        "headline": headline,
        "n_auctions": headline.get("n_auctions"),
        "trial_count": trial_count,
        "scope": scope,                 # e.g. "claims-pnl / taker-sim / maker-resting / sweep"
        "window_basis": window_basis,   # how the auction window was derived
        "fills": fills,                 # fill model + fee assumptions (the taker-fee-zero trap)
        "data_paths": data_paths or [],
        "notes": notes,
    }
    block = json.dumps(meta, indent=2, default=str)
    print("\n===RUN_META===")
    print(block)
    print("===END_RUN_META===")
    try:
        d = Path(script).resolve().parent / out_dir
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{Path(script).stem}.run_meta.json").write_text(block, encoding="utf-8")
    except Exception:
        pass  # printing is the primary channel; sidecar is best-effort
    return meta
