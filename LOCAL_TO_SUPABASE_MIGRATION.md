# Local-to-Supabase migration

Do not upload existing participant recordings merely because credentials are configured. Confirm the target project, consent scope, retention policy, and an independent local backup first.

## 1. Back up

Stop active collection, then copy the local database and recording root to a separate protected location. Verify the copy can be read. Keep this backup after migration; the importer never deletes source data.

## 2. Inventory (dry run)

```powershell
python scripts/migrate_local_to_supabase.py --source "D:\FlexMapVault" --backup-dir "E:\FlexMapBackup" --report ".\migration-report.json" --checkpoint ".\migration-checkpoint.json"
```

Review record/file/byte counts and the report. The command does not contact Supabase unless `--execute` is supplied.

## 3. Execute after approval

Set backend-only Supabase variables in the shell, then add both flags:

```powershell
python scripts/migrate_local_to_supabase.py --source "D:\FlexMapVault" --backup-dir "E:\FlexMapBackup" --report ".\migration-report.json" --checkpoint ".\migration-checkpoint.json" --execute --consent-approved
```

The importer uses immutable uploads, collision checks, SHA-256 manifests, checkpoints, and an audit report. Matching completed imports are skipped. Conflicting recording IDs are reported as `COLLISION` and are not merged or overwritten. A failed run can be repeated with the same checkpoint. Local files are never removed.

## Ownership and rollback

Once `FLEXMAP_DATA_BACKEND=supabase`, later review, relabel, trash, and restore decisions in Supabase are authoritative. Do not run a stale local upsert over those decisions. To roll back application traffic, first stop collection, export both Postgres metadata and Storage objects, then switch to `local`; this does not automatically copy cloud changes back into SQLite.

Soft-deleted rows retain their objects for restoration. Permanent deletion requires a separate audited operation that deletes Storage objects explicitly; deleting a database row alone does not delete its media.
