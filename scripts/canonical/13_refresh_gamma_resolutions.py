"""
Phase 13 - Re-resolve the falsely-demoted auctions from a FRESH Gamma pull.

Background: 08_normalize_bucket_labels.py demoted 91 Elon auctions to
confidence='low' + resolution_status='..._bracket_mismatch' because their
winning bracket did not appear in canonical's PRICES table. Root cause is NOT
a wrong winner: on 7-day markets Polymarket adds the higher brackets late, and
canonical's early trade snapshot predated them, so those brackets had no trades
-> no price rows -> false "mismatch". Gamma has the complete, closed bracket set
and confirms the winner (verified: winning_bucket == fresh Gamma YES winner).

This script, for each demoted/unresolved auction:
  1. Fresh Gamma /events?slug (bypasses the stale 06 cache).
  2. Extract the FULL bracket set: label -> condition_id / yes_token / no_token.
  3. Confirm the single YES winner (outcomePrices == ["1","0"]).
  4. Rewrite the complete bracket dicts + winner fields, and restore
     resolution_status='resolved_yes_gamma' + confidence='high'.
  5. Only upgrade when exactly one YES winner is found AND it is in the set;
     otherwise leave the row flagged (no silent guesses).

CORRECTION 2026-07-30: step 4 originally restored confidence='high' whether or
not the winning bracket had any price rows. Knowing WHO won is not the same as
HAVING market data for them, and this script's own reasoning above conflates the
two. Restoring 'high' erased the only signal downstream backtests had, and 134
of 244 Elon auctions silently entered the admissible set with no market price
for the bracket that won. A row is now only upgraded to 'high' when prices
actually covers the winner; otherwise it keeps confidence='low' and is tagged
'_no_winner_price', so the documented `confidence in ('high','medium')` filter
still excludes it. The winner fields are written either way -- the label is
correct, it is the market data that is missing. Repair the data with
14_repair_bracket_coverage.py + 04_build_prices.py, then re-run this.

Idempotent. Rate-limited. Backs up the handle's auction dir before writing.

Usage: python -u scripts/canonical/13_refresh_gamma_resolutions.py [elonmusk]
"""
from __future__ import annotations
import json, sys, time, shutil, urllib.error, urllib.request
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _canon import CANON, ROOT, load_partitioned, normalize_bucket  # noqa: E402

AUCTIONS_DIR = CANON / "auctions"
GAMMA = "https://gamma-api.polymarket.com"
RATE = 0.5
TARGET_STATUSES = ("resolved_yes_gamma_bracket_mismatch", "unresolved")
NO_PRICE_SUFFIX = "_no_winner_price"


def http_get(url: str, tries: int = 4):
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (canonical-refresh)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and a < tries - 1:
                time.sleep(2 ** a); continue
            return None
        except Exception:
            if a < tries - 1:
                time.sleep(2 ** a); continue
            return None
    return None


def extract_brackets(ev: dict) -> list[dict]:
    out = []
    for m in ev.get("markets", []):
        label = (m.get("groupItemTitle") or "").strip()
        cid = m.get("conditionId") or ""
        try:
            toks = json.loads(m.get("clobTokenIds") or "[]")
        except Exception:
            toks = []
        try:
            outs = json.loads(m.get("outcomes") or "[]")
        except Exception:
            outs = []
        yt = nt = ""
        for i, o in enumerate(outs):
            if str(o).lower() in ("yes", "1") and i < len(toks):
                yt = str(toks[i])
            elif str(o).lower() in ("no", "0") and i < len(toks):
                nt = str(toks[i])
        try:
            op = json.loads(m.get("outcomePrices") or "[]")
        except Exception:
            op = []
        out.append({"label": label, "cid": cid, "yes": yt, "no": nt, "op": op})
    return out


def resolve(slug: str) -> dict | None:
    d = http_get(f"{GAMMA}/events?slug={slug}")
    if not (isinstance(d, list) and d):
        return {"status": "no_event"}
    ev = d[0]
    if not ev.get("closed"):
        return {"status": "event_not_closed"}
    br = extract_brackets(ev)
    if not br:
        return {"status": "no_markets"}
    winners = [b for b in br if b["op"] == ["1", "0"]]
    return {"status": "ok", "brackets": br, "winners": winners}


def main(handle: str = "elonmusk") -> int:
    files = sorted((AUCTIONS_DIR / handle).glob("*.parquet"))
    if not files:
        print(f"no files for {handle}"); return 1
    # backup
    bak = AUCTIONS_DIR / f"{handle}_backup_pre13"
    if bak.exists():
        shutil.rmtree(bak)
    shutil.copytree(AUCTIONS_DIR / handle, bak)
    print(f"[13] backed up {handle} auctions -> {bak.name}")

    df = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
    before = df["confidence"].value_counts().to_dict()
    targets = df[df["resolution_status"].isin(TARGET_STATUSES)].copy()
    print(f"[13] {handle}: {len(df)} auctions, {len(targets)} to re-resolve (statuses {TARGET_STATUSES})")

    # Confirming the winner from Gamma does not conjure market data for it.
    # Look up what prices ACTUALLY covers so an upgrade cannot outrun the data.
    prc = load_partitioned("prices", handle)
    covered: dict[str, set[str]] = {}
    if len(prc):
        covered = prc.assign(bucket=prc["bucket"].map(normalize_bucket)) \
                     .groupby("auction_slug")["bucket"].agg(set).to_dict()

    fixed = no_price = failed = still_flagged = 0
    for i, (idx, row) in enumerate(targets.iterrows(), 1):
        slug = row["auction_slug"]
        r = resolve(slug); time.sleep(RATE)
        if not r or r["status"] != "ok":
            failed += 1
            if i % 10 == 0:
                print(f"  {i}/{len(targets)} last={slug[:36]} -> {r['status'] if r else 'none'}")
            continue
        br, winners = r["brackets"], r["winners"]
        labels = [b["label"] for b in br if b["label"]]
        if len(winners) != 1 or not winners[0]["label"]:
            still_flagged += 1
            df.at[idx, "gamma_resolution_source"] = f"refresh_{len(winners)}_winners"
            continue
        w = winners[0]
        df.at[idx, "winning_bucket"] = w["label"]
        df.at[idx, "gamma_winning_bucket"] = w["label"]
        df.at[idx, "all_buckets"] = ", ".join(labels)
        df.at[idx, "n_buckets"] = len(labels)
        df.at[idx, "bracket_condition_ids"] = json.dumps({b["label"]: b["cid"] for b in br if b["label"]})
        df.at[idx, "bracket_yes_token_ids"] = json.dumps({b["label"]: b["yes"] for b in br if b["label"]})
        df.at[idx, "bracket_no_token_ids"] = json.dumps({b["label"]: b["no"] for b in br if b["label"]})
        df.at[idx, "winner_condition_id"] = w["cid"]
        df.at[idx, "winner_asset_yes_token_id"] = w["yes"]
        df.at[idx, "winner_asset_no_token_id"] = w["no"]
        df.at[idx, "gamma_resolution_source"] = "gamma_refresh_13"
        if normalize_bucket(w["label"]) in covered.get(slug, set()):
            df.at[idx, "resolution_status"] = "resolved_yes_gamma"
            df.at[idx, "confidence"] = "high"
            fixed += 1
        else:
            # winner is known but has no price row -- admissible for "who won"
            # questions, NOT for anything scored against the market.
            df.at[idx, "resolution_status"] = "resolved_yes_gamma" + NO_PRICE_SUFFIX
            df.at[idx, "confidence"] = "low"
            no_price += 1
        if i % 10 == 0:
            print(f"  {i}/{len(targets)} fixed={fixed} no_price={no_price} "
                  f"last={slug[:36]} -> {w['label']}")

    # re-partition write
    for p in files:
        p.unlink()
    df["start_utc"] = pd.to_datetime(df["start_utc"], utc=True)
    df["_part"] = df["start_utc"].dt.strftime("%Y-%m")
    for part, sub in df.groupby("_part"):
        out = AUCTIONS_DIR / handle / f"{part}.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        sub.drop(columns=["_part"]).to_parquet(out, index=False)

    after = df["confidence"].value_counts().to_dict()
    print(f"\n[13] DONE. fixed={fixed} no_winner_price={no_price} "
          f"still_flagged={still_flagged} failed={failed}")
    if no_price:
        print(f"  !! {no_price} auctions have a confirmed winner with NO price row. "
              f"Run 14_repair_bracket_coverage.py -> 04_build_prices.py -> re-run this.")
    print(f"  confidence BEFORE: {before}")
    print(f"  confidence AFTER:  {after}")
    print(f"  resolution_status AFTER: {df['resolution_status'].value_counts().to_dict()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "elonmusk"))
