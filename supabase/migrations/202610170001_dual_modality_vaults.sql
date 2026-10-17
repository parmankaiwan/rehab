-- FlexMap dual-modality research vaults.
-- Additive only: existing browser CV and local-mirror records remain intact.
begin;

-- flexmap_browser_* is the authoritative CV schema. These additions make the
-- modality and lifecycle guarantees explicit without creating a second CV
-- source of truth.
alter table public.flexmap_browser_datasets
  add column if not exists schema_version text not null default 'CV_DATASET_1.0',
  add column if not exists deleted_at timestamptz;
alter table public.flexmap_browser_labels
  add column if not exists schema_version text not null default 'CV_LABEL_1.0';
do $$ begin
  if not exists (
    select 1 from pg_constraint where conname = 'flexmap_browser_samples_cv_only'
  ) then
    alter table public.flexmap_browser_samples
      add constraint flexmap_browser_samples_cv_only check (modality = 'CV') not valid;
  end if;
end $$;
alter table public.flexmap_browser_samples validate constraint flexmap_browser_samples_cv_only;
do $$ begin
  if not exists (
    select 1 from pg_constraint where conname = 'flexmap_browser_samples_review_status'
  ) then
    alter table public.flexmap_browser_samples
      add constraint flexmap_browser_samples_review_status
      check (review_status in ('REVIEW_REQUIRED','REVIEWED','APPROVED','REJECTED')) not valid;
  end if;
  if not exists (
    select 1 from pg_constraint where conname = 'flexmap_browser_samples_training_reviewed'
  ) then
    alter table public.flexmap_browser_samples
      add constraint flexmap_browser_samples_training_reviewed
      check (not training_eligible or (review_status = 'APPROVED' and trashed_at is null)) not valid;
  end if;
end $$;
alter table public.flexmap_browser_samples validate constraint flexmap_browser_samples_review_status;
alter table public.flexmap_browser_samples validate constraint flexmap_browser_samples_training_reviewed;

create table if not exists public.flexmap_cv_review_audit (
  audit_id bigint generated always as identity primary key,
  sample_id text not null references public.flexmap_browser_samples(sample_id) on delete restrict,
  action text not null,
  previous_value jsonb,
  new_value jsonb,
  actor text not null default 'MASTER',
  occurred_at timestamptz not null default now()
);

create table if not exists public.flexmap_emg_datasets (
  dataset_id text primary key,
  storage_key text not null unique,
  name text not null,
  description text not null default '',
  muscle_under_study text,
  recording_purpose text,
  target_count integer check (target_count is null or target_count >= 0),
  schema_version text not null default 'EMG_DATASET_1.0',
  archived boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  unique(name)
);

create table if not exists public.flexmap_emg_labels (
  label_id text primary key,
  dataset_id text not null references public.flexmap_emg_datasets(dataset_id) on delete restrict,
  name text not null,
  display_name text not null,
  description text not null default '',
  schema_version text not null default 'EMG_LABEL_1.0',
  archived boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(dataset_id, name)
);

create table if not exists public.flexmap_emg_recordings (
  recording_id text primary key,
  dataset_id text not null references public.flexmap_emg_datasets(dataset_id) on delete restrict,
  label_id text not null references public.flexmap_emg_labels(label_id) on delete restrict,
  research_label text not null,
  subject_code text not null,
  session_id text,
  protocol_id text,
  protocol_version integer,
  trial_id text,
  attempt_number integer not null default 1 check (attempt_number > 0),
  tested_side text,
  muscle_under_study text,
  channel_count integer not null check (channel_count > 0),
  sample_count bigint not null check (sample_count >= 0),
  sample_rate_hz double precision,
  duration_seconds double precision not null check (duration_seconds >= 0),
  signal_units text not null default 'ADC_COUNTS',
  hardware_snapshot jsonb not null default '{}'::jsonb,
  processing_versions jsonb not null default '{}'::jsonb,
  metadata jsonb not null default '{}'::jsonb,
  quality_report jsonb,
  persistence_status text not null default 'DRAFT'
    check (persistence_status in ('DRAFT','UPLOADING','VERIFYING','STORED','FAILED','INTERRUPTED')),
  review_status text not null default 'REVIEW_REQUIRED',
  review_notes text not null default '',
  training_eligible boolean not null default false,
  excluded boolean not null default false,
  exclusion_reason text,
  storage_prefix text not null,
  artifact_manifest jsonb not null default '[]'::jsonb,
  idempotency_key text not null unique,
  schema_version text not null default 'EMG_RECORDING_1.0',
  revision bigint not null default 1,
  failure_reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  verified_at timestamptz,
  trashed_at timestamptz
);

do $$ begin
  if not exists (
    select 1 from pg_constraint where conname = 'flexmap_emg_recordings_review_status'
  ) then
    alter table public.flexmap_emg_recordings
      add constraint flexmap_emg_recordings_review_status
      check (review_status in ('REVIEW_REQUIRED','REVIEWED','APPROVED','REJECTED')) not valid;
  end if;
  if not exists (
    select 1 from pg_constraint where conname = 'flexmap_emg_recordings_training_reviewed'
  ) then
    alter table public.flexmap_emg_recordings
      add constraint flexmap_emg_recordings_training_reviewed
      check (not training_eligible or (review_status = 'APPROVED' and not excluded and trashed_at is null)) not valid;
  end if;
end $$;
alter table public.flexmap_emg_recordings validate constraint flexmap_emg_recordings_review_status;
alter table public.flexmap_emg_recordings validate constraint flexmap_emg_recordings_training_reviewed;

create table if not exists public.flexmap_emg_artifacts (
  artifact_id uuid primary key default gen_random_uuid(),
  recording_id text not null references public.flexmap_emg_recordings(recording_id) on delete restrict,
  artifact_role text not null,
  object_path text not null unique,
  content_type text not null,
  byte_size bigint not null check (byte_size >= 0),
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  verification_status text not null default 'PENDING'
    check (verification_status in ('PENDING','VERIFIED','FAILED')),
  processing_version text,
  created_at timestamptz not null default now(),
  verified_at timestamptz,
  unique(recording_id, artifact_role, processing_version)
);

create table if not exists public.flexmap_emg_review_audit (
  audit_id bigint generated always as identity primary key,
  recording_id text not null references public.flexmap_emg_recordings(recording_id) on delete restrict,
  action text not null,
  previous_value jsonb,
  new_value jsonb,
  actor text not null default 'MASTER',
  occurred_at timestamptz not null default now()
);

create index if not exists flexmap_emg_datasets_updated_idx on public.flexmap_emg_datasets(updated_at desc) where deleted_at is null;
create index if not exists flexmap_emg_recordings_dataset_idx on public.flexmap_emg_recordings(dataset_id, created_at desc);
create index if not exists flexmap_emg_recordings_subject_idx on public.flexmap_emg_recordings(subject_code, session_id);
create index if not exists flexmap_emg_recordings_review_idx on public.flexmap_emg_recordings(review_status, training_eligible) where trashed_at is null;
create index if not exists flexmap_emg_artifacts_recording_idx on public.flexmap_emg_artifacts(recording_id);
create index if not exists flexmap_cv_review_audit_sample_idx on public.flexmap_cv_review_audit(sample_id, occurred_at desc);
create index if not exists flexmap_emg_review_audit_recording_idx on public.flexmap_emg_review_audit(recording_id, occurred_at desc);

alter table public.flexmap_cv_review_audit enable row level security;
alter table public.flexmap_emg_datasets enable row level security;
alter table public.flexmap_emg_labels enable row level security;
alter table public.flexmap_emg_recordings enable row level security;
alter table public.flexmap_emg_artifacts enable row level security;
alter table public.flexmap_emg_review_audit enable row level security;

revoke all on public.flexmap_cv_review_audit, public.flexmap_emg_datasets,
  public.flexmap_emg_labels, public.flexmap_emg_recordings,
  public.flexmap_emg_artifacts, public.flexmap_emg_review_audit from anon, authenticated;
grant select, insert, update, delete on public.flexmap_cv_review_audit,
  public.flexmap_emg_datasets, public.flexmap_emg_labels,
  public.flexmap_emg_recordings, public.flexmap_emg_artifacts,
  public.flexmap_emg_review_audit to service_role;
grant usage, select on sequence public.flexmap_cv_review_audit_audit_id_seq,
  public.flexmap_emg_review_audit_audit_id_seq to service_role;

insert into storage.buckets (id, name, public)
values
  ('flexmap-cv-vault', 'flexmap-cv-vault', false),
  ('flexmap-emg-vault', 'flexmap-emg-vault', false)
on conflict (id) do update set public = false;

insert into public.flexmap_schema_migrations(version, description)
values ('202610170001', 'Independent CV and EMG metadata vaults and private storage buckets')
on conflict (version) do nothing;

commit;
