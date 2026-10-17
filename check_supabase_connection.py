"""Read-only local configuration and authenticated vault readiness check.

Run from the repository root. Never prints key values or research records.
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from backend.data_backend import StorageStatusService
from backend.supabase_vault import SupabaseVaultConfig


def main():
    config = SupabaseVaultConfig.from_env()
    if config.url.rstrip("/") != "https://luhrcmbtijdtbmqzommk.supabase.co":
        print(json.dumps({"state": "PROJECT_MISMATCH"}))
        return 2
    # Diagnostic mode only; does not change the saved environment or app mode.
    os.environ["FLEXMAP_DATA_BACKEND"] = "supabase"
    result = StorageStatusService(config).check()
    print(json.dumps({key: result[key] for key in ("state", "database", "schema", "bucket")}, indent=2))
    return 0 if result["state"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
