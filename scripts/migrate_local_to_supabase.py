"""Controlled local FlexMap vault inventory/import.

Dry-run is the default. Existing source files are never modified or deleted.
Execute only after governance approval and an independent backup.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.supabase_vault import SupabaseVaultConfig


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(source: Path) -> list[dict]:
    rows = []
    for metadata_path in sorted(source.rglob("metadata.json")):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        recording_id = str(metadata.get("recording_id") or metadata_path.parent.name)
        files = [{"path": path.relative_to(metadata_path.parent).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)} for path in sorted(metadata_path.parent.rglob("*")) if path.is_file()]
        rows.append({"recording_id": recording_id, "folder": str(metadata_path.parent.resolve()), "metadata": metadata, "files": files, "total_bytes": sum(item["bytes"] for item in files)})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory/import a local FlexMap vault without deleting local data")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True, help="Existing independent backup directory")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--consent-approved", action="store_true")
    args = parser.parse_args()
    source, backup = args.source.resolve(), args.backup_dir.resolve()
    if not source.is_dir() or not backup.is_dir() or backup == source or source in backup.parents:
        raise SystemExit("Source and a separate existing backup directory are required")
    rows = inventory(source)
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "mode": "EXECUTE" if args.execute else "DRY_RUN", "source": str(source), "backup": str(backup), "recordings": len(rows), "files": sum(len(row["files"]) for row in rows), "bytes": sum(row["total_bytes"] for row in rows), "results": []}
    if args.execute and not args.consent_approved:
        raise SystemExit("--execute also requires --consent-approved")
    if args.execute:
        config = SupabaseVaultConfig.from_env()
        config.validate()
        completed = set()
        if args.checkpoint.exists():
            completed = set(json.loads(args.checkpoint.read_text(encoding="utf-8")).get("completed", []))
        import httpx
        with httpx.Client(base_url=config.url, headers={**config.auth_headers(), "User-Agent": "FlexMap-Importer/1.0"}, timeout=config.timeout_seconds) as client:
            for row in rows:
                recording_id = row["recording_id"]
                if recording_id in completed:
                    report["results"].append({"recording_id": recording_id, "status": "CHECKPOINT_SKIPPED"}); continue
                existing = client.get(f"/rest/v1/{quote(config.table, safe='')}", params={"select": "recording_id,metadata", "recording_id": f"eq.{recording_id}", "limit": "1"})
                existing.raise_for_status()
                manifest_hash = hashlib.sha256(json.dumps(row["files"], sort_keys=True).encode()).hexdigest()
                found = existing.json()
                if found:
                    same = (found[0].get("metadata") or {}).get("import_manifest_hash") == manifest_hash
                    report["results"].append({"recording_id": recording_id, "status": "ALREADY_IMPORTED" if same else "COLLISION"})
                    if not same: continue
                    completed.add(recording_id); continue
                prefix = f"imports/{hashlib.sha256(recording_id.encode()).hexdigest()[:24]}"
                folder = Path(row["folder"])
                for item in row["files"]:
                    path = folder / item["path"]
                    with path.open("rb") as stream:
                        response = client.post(f"/storage/v1/object/{quote(config.bucket, safe='')}/{quote(prefix + '/' + item['path'], safe='/')}", headers={"content-type": "application/octet-stream", "x-upsert": "false"}, content=stream)
                    response.raise_for_status()
                payload = {"recording_id": recording_id, "modality": row["metadata"].get("modality", "CV"), "storage_prefix": prefix, "files": [item["path"] for item in row["files"]], "metadata": {**row["metadata"], "import_manifest_hash": manifest_hash}, "synced_at": datetime.now(timezone.utc).isoformat()}
                inserted = client.post(f"/rest/v1/{quote(config.table, safe='')}", headers={"Prefer": "return=minimal"}, json=payload)
                inserted.raise_for_status()
                completed.add(recording_id)
                args.checkpoint.write_text(json.dumps({"completed": sorted(completed)}, indent=2), encoding="utf-8")
                report["results"].append({"recording_id": recording_id, "status": "IMPORTED", "manifest_hash": manifest_hash})
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("mode", "recordings", "files", "bytes")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
