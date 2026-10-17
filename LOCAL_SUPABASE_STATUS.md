# Local FlexMap integration

Target: flexmapv (`luhrcmbtijdtbmqzommk`). No remote writes or migration application were performed during this repair.

## Verified

- Repository was clean at commit `8a2d144` before these changes.
- `backend/app.py` loads the repository `.env` before importing services. Shell environment values take precedence; a backend restart is required after changing `.env` because service configuration is captured at import time.
- `.env` contains the project URL and has no value for any supported server key name. Its contents were not printed.
- Authenticated management SQL, restricted to schema/bucket metadata, found only `public.flexmap_dataset_recordings` with RLS enabled and private bucket `flexmap-dataset`.
- Browser CV uses `flexmap_browser_*` plus `flexmap_recording_artifacts`; EMG uses `flexmap_emg_*`. New artifacts use separate private buckets. Legacy CV reads retain the existing bucket fallback. Local recordings are not migrated automatically.
- EMG now verifies uploaded bytes by streamed read-back and SHA-256 before indexing them as verified or marking the recording STORED. Corrupt read-back leaves FAILED state.
- Storage readiness now checks required CV/EMG tables even when the migration marker exists. CV status reports the CV bucket. Configuration representation omits the secret.

## Required local action

1. Open `C:\Users\Parman\Desktop\rehab\Software part\.env` in your own editor. Set `FLEXMAP_SUPABASE_SECRET_KEY` to a backend secret key from the project's Dashboard Settings → API Keys. Never paste it into chat or put it in frontend environment files. Keep `FLEXMAP_SUPABASE_SYNC_ENABLED=false` for authoritative Supabase mode.
2. Run the read-only check from this repository:

   `& '..\CV part\.venv\Scripts\python.exe' .\check_supabase_connection.py`

3. The deployed foundation is insufficient for Collection Studio. The existing SQL files contain the missing additive schema. Review and apply them in order to an explicitly approved non-production target, or separately authorize changes to this project if it is the intended writable target:
   - `supabase/migrations/202610150001_flexmap_dataset_vault.sql` (also creates the missing browser tables; its existing table/bucket statements are idempotent)
   - `supabase/migrations/202610160001_authoritative_collection_storage.sql`
   - `supabase/migrations/202610170001_dual_modality_vaults.sql`

   Do not drop the foundation table or remove the legacy bucket. The files enable RLS and restrict metadata access to the backend service role. No new migration is needed for the Python fixes.
4. Rerun the connection check, then restart only the local backend after active collection has stopped.

## Verification still blocked

Real application-key REST/Storage checks require the missing private key. Real synthetic CV and EMG save/retrieve/restart tests additionally require the full schema and a writable non-production target. They have not been run against Supabase. Management SQL access does not prove the application's private key works. No hardware was connected, stopped, or reconfigured, and no existing participant data was read or uploaded.

The local automated tests use synthetic data and mocked Supabase responses; they are not evidence of remote persistence. For remote acceptance, use clearly named synthetic datasets in each vault, save tiny CV observations and EMG CSV artifacts, reopen through fresh backend processes, compare bytes/hashes and IDs, confirm modality isolation and idempotent retry, and retain or remove only those test artifacts according to the target's test policy.
