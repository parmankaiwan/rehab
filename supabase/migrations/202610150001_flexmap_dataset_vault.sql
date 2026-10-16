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

-- Browser-owned CV Collection Studio. These entities are intentionally
-- distinct from rehabilitation modules and from legacy engine recordings.
create table if not exists public.flexmap_browser_datasets (
  dataset_id text primary key,
  storage_key text not null unique,
  name text not null,
  rehabilitation_module_id text not null,
  description text not null default '',
  instructions text not null default '',
  camera_view text not null default 'FRONT',
  relevant_side text not null default 'N/A',
  observation_profile text not null default 'FULL_POSE',
  permitted_capture_types text not null check (permitted_capture_types in ('STILL', 'VIDEO', 'BOTH')),
  protocol_id text,
  session_id text,
  data_purpose text not null default 'RESEARCH',
  allow_raw_media boolean not null default true,
  allow_annotated_media boolean not null default false,
  allow_thumbnails boolean not null default true,
  archived boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (rehabilitation_module_id, name)
);

create table if not exists public.flexmap_browser_labels (
  label_id text primary key,
  dataset_id text not null references public.flexmap_browser_datasets(dataset_id) on delete restrict,
  name text not null,
  display_name text not null,
  description text not null default '',
  tracking_failure_label boolean not null default false,
  archived boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (dataset_id, name)
);

create table if not exists public.flexmap_browser_samples (
  sample_id text primary key,
  dataset_id text not null references public.flexmap_browser_datasets(dataset_id) on delete restrict,
  label_id text not null references public.flexmap_browser_labels(label_id) on delete restrict,
  label_at_capture text not null,
  reviewed_label text,
  sample_type text not null check (sample_type in ('STILL', 'VIDEO')),
  source text not null check (source = 'BROWSER_MEDIAPIPE'),
  subject_id text not null,
  session_id text,
  protocol_id text,
  trial_id text,
  attempt_number integer not null default 1,
  notes text not null default '',
  capture_state text not null check (capture_state in ('COMPLETE', 'INTERRUPTED')),
  technical_quality text not null,
  tracking_quality text not null,
  review_status text not null default 'REVIEW_REQUIRED',
  training_eligible boolean not null default false,
  training_ineligibility_reason text,
  storage_prefix text not null unique,
  artifact_manifest jsonb not null default '[]'::jsonb,
  metadata jsonb not null default '{}'::jsonb,
  idempotency_key text not null unique,
  created_at timestamptz not null default now(),
  server_received_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  trashed_at timestamptz
);

create table if not exists public.flexmap_browser_label_audit (
  audit_id bigint generated always as identity primary key,
  sample_id text not null references public.flexmap_browser_samples(sample_id) on delete restrict,
  previous_label text not null,
  new_label text not null,
  changed_at timestamptz not null default now()
);

create index if not exists flexmap_browser_datasets_module_idx on public.flexmap_browser_datasets(rehabilitation_module_id, updated_at desc);
create index if not exists flexmap_browser_samples_dataset_idx on public.flexmap_browser_samples(dataset_id, created_at desc);
create index if not exists flexmap_browser_samples_review_idx on public.flexmap_browser_samples(review_status) where trashed_at is null;

alter table public.flexmap_browser_datasets enable row level security;
alter table public.flexmap_browser_labels enable row level security;
alter table public.flexmap_browser_samples enable row level security;
alter table public.flexmap_browser_label_audit enable row level security;
revoke all on table public.flexmap_browser_datasets, public.flexmap_browser_labels, public.flexmap_browser_samples, public.flexmap_browser_label_audit from anon, authenticated;
grant select, insert, update, delete on table public.flexmap_browser_datasets, public.flexmap_browser_labels, public.flexmap_browser_samples, public.flexmap_browser_label_audit to service_role;
grant usage, select on sequence public.flexmap_browser_label_audit_audit_id_seq to service_role;
