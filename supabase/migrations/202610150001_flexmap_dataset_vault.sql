-- FlexMap Dataset Vault: private metadata mirror and private artifact bucket.
-- Run this once in the Supabase SQL editor before enabling synchronization.

create table if not exists public.flexmap_dataset_recordings (
  recording_id text primary key,
  modality text not null check (modality in ('CV', 'EMG')),
  subject_id text,
  session_id text,
  study_id text,
  collection_id text,
  protocol_id text,
  protocol_version integer,
  trial_id text,
  rehab_type text,
  rehab_slug text,
  research_label text,
  affected_side text,
  created_at timestamptz,
  duration_seconds double precision,
  technical_quality text,
  review_status text,
  training_eligible boolean not null default false,
  excluded boolean not null default false,
  is_mock boolean not null default false,
  dataset_schema_version text,
  local_relative_path text,
  storage_prefix text,
  files jsonb not null default '[]'::jsonb,
  metadata jsonb not null default '{}'::jsonb,
  quality_report jsonb,
  artifact_references jsonb not null default '{}'::jsonb,
  schema_versions jsonb not null default '{}'::jsonb,
  deleted_at timestamptz,
  synced_at timestamptz not null default now()
);

create index if not exists flexmap_dataset_recordings_created_at_idx
  on public.flexmap_dataset_recordings (created_at desc);
create index if not exists flexmap_dataset_recordings_subject_idx
  on public.flexmap_dataset_recordings (subject_id);
create index if not exists flexmap_dataset_recordings_rehab_label_idx
  on public.flexmap_dataset_recordings (rehab_type, research_label);
create index if not exists flexmap_dataset_recordings_training_idx
  on public.flexmap_dataset_recordings (training_eligible)
  where deleted_at is null;

alter table public.flexmap_dataset_recordings enable row level security;
revoke all on table public.flexmap_dataset_recordings from anon, authenticated;
grant select, insert, update, delete on table public.flexmap_dataset_recordings to service_role;

insert into storage.buckets (id, name, public)
values ('flexmap-dataset', 'flexmap-dataset', false)
on conflict (id) do update set public = false;
