# Supabase setup for FlexMap

FlexMap supports two explicit authority modes. `local` keeps SQLite and local recording folders authoritative and may use the older controlled mirror. `supabase` makes Supabase Postgres and the private Storage bucket authoritative for hosted browser collection data. Never enable `FLEXMAP_SUPABASE_SYNC_ENABLED` while using `supabase` mode.

## Apply the schema

1. Confirm the intended Supabase project and data region.
2. In Supabase SQL Editor, apply migrations in order:
   - `supabase/migrations/202610150001_flexmap_dataset_vault.sql`
   - `supabase/migrations/202610160001_authoritative_collection_storage.sql`
3. Confirm `flexmap-dataset` is **private**. Do not add anon/authenticated policies to research tables or Storage.
4. In the Render **API service** Environment page, set:
   - `FLEXMAP_DATA_BACKEND=supabase`
   - `FLEXMAP_SUPABASE_URL=https://<project-ref>.supabase.co`
   - `FLEXMAP_SUPABASE_SECRET_KEY=<backend secret key>`
   - `FLEXMAP_SUPABASE_VAULT_BUCKET=flexmap-dataset`
   - `FLEXMAP_SUPABASE_VAULT_TABLE=flexmap_dataset_recordings`
   - `FLEXMAP_SUPABASE_TIMEOUT_SECONDS=20`
   - `FLEXMAP_SUPABASE_SYNC_ENABLED=false`
5. Do not add the secret to the web service and never create a `NEXT_PUBLIC_` secret variable.
6. Open Master → System → Storage authority and select **Test connection**. Ready means database connectivity, required migration, and a private bucket were all checked remotely.

Current `sb_secret_` keys are sent in Supabase's `apikey` header and never treated as JWTs. Legacy service-role JWT keys remain supported with both `apikey` and Bearer headers.

## Operational safety

Before changing production storage mode or restarting Render, export any data held only on Render. A Postgres backup does not include Storage objects: back up database metadata and the private bucket independently. Cloud transfer of participant data requires approved consent and governance.

The current browser capture endpoint accepts bounded packages up to 150 MB and verifies uploaded bytes by read-back before marking a recording `STORED`. For unreliable networks or routine large video collection, deploy a TUS/resumable direct-upload extension before increasing that bound; do not raise the proxy memory limit.
