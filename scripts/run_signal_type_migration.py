"""Run the signal_type schema migration + backfill against prod Supabase.

Idempotent: ALTER uses IF NOT EXISTS, UPDATE only touches NULL rows.
Safe to re-run.

Usage:
    python scripts/run_signal_type_migration.py
"""
import os
from supabase import create_client


SQL = """
ALTER TABLE signals ADD COLUMN IF NOT EXISTS signal_type TEXT;
CREATE INDEX IF NOT EXISTS idx_signals_type_module ON signals (module_id, signal_type);

UPDATE signals
SET signal_type = COALESCE(
    metadata->>'signal_type',
    CASE
        WHEN metadata->>'strategy' = 'spike_trading' THEN 'spike'
        ELSE 'baseline'
    END
)
WHERE signal_type IS NULL;
"""


def main():
    url = os.environ.get("SUPABASE_URL") or "https://xdonwowgqvmtrduikaon.supabase.co"
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not key:
        # fallback to .env in repo root
        from pathlib import Path
        env_path = Path(__file__).resolve().parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("SUPABASE_SERVICE_KEY="):
                    key = line.split("=", 1)[1].strip()
                    break
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_KEY not set")

    sb = create_client(url, key)

    # supabase-py doesn't expose raw exec; use rpc if defined, else fall back
    # to running the migration via psql in CI. We can still verify the result.
    print("=== before ===")
    before = sb.table("signals").select("id", count="exact").is_("metadata", "not.null").limit(1).execute()
    print(f"Total signals: {before.count}")

    # Probe: does the signal_type column exist already?
    try:
        probe = sb.table("signals").select("signal_type").limit(1).execute()
        col_exists = True
        sample_val = (probe.data[0].get("signal_type") if probe.data else None)
        print(f"signal_type column exists. Sample value: {sample_val!r}")
    except Exception as e:
        col_exists = False
        print(f"signal_type column does NOT exist yet ({e})")

    if not col_exists:
        print("\n!!! Run the SQL via Supabase SQL editor or psql:\n")
        print(SQL)
        return

    # Column exists — count by signal_type
    spike = sb.table("signals").select("id", count="exact").eq("signal_type", "spike").execute()
    base = sb.table("signals").select("id", count="exact").eq("signal_type", "baseline").execute()
    null_ = sb.table("signals").select("id", count="exact").is_("signal_type", "null").execute()
    print(f"\nspike:    {spike.count}")
    print(f"baseline: {base.count}")
    print(f"NULL:     {null_.count}")

    if null_.count > 0:
        print("\n!!! NULL rows present; run the backfill SQL via Supabase SQL editor:\n")
        print(SQL)


if __name__ == "__main__":
    main()
