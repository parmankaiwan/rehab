-- FlexMap ML Training V2 durable experiment storage.
-- Additive only. Existing local SQLite experiment records are not modified.
begin;

create table if not exists public.flexmap_ml_dataset_versions (
  dataset_version_id text primary key,
  name text not null,
  modality text not null check (modality in ('CV','EMG')),
  rehab_type text not null,
  status text not null check (status in ('DRAFT','FROZEN')),
  manifest_sha256 text check (manifest_sha256 is null or manifest_sha256 ~ '^[0-9a-f]{64}$'),
  recording_ids jsonb not null default '[]'::jsonb,
  source_query jsonb not null default '{}'::jsonb,
  distributions jsonb not null default '{}'::jsonb,
  health jsonb not null default '{}'::jsonb,
  manifest jsonb,
  mock_included boolean not null default false,
  created_by text not null default 'MASTER',
  created_at timestamptz not null default now(),
  frozen_at timestamptz
);

create table if not exists public.flexmap_ml_feature_pipelines (
  feature_pipeline_id text primary key,
  name text not null,
  modality text not null check (modality in ('CV','EMG')),
  version text not null,
  configuration jsonb not null,
  source_fields jsonb not null,
  code_version text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.flexmap_ml_splits (
  split_id text primary key,
  dataset_version_id text not null references public.flexmap_ml_dataset_versions(dataset_version_id) on delete restrict,
  strategy text not null,
  seed integer not null,
  configuration jsonb not null,
  assignments jsonb not null,
  leakage_report jsonb not null,
  created_at timestamptz not null default now()
);

create table if not exists public.flexmap_ml_training_runs (
  training_run_id text primary key,
  dataset_version_id text not null references public.flexmap_ml_dataset_versions(dataset_version_id) on delete restrict,
  manifest_sha256 text not null check (manifest_sha256 ~ '^[0-9a-f]{64}$'),
  split_id text not null references public.flexmap_ml_splits(split_id) on delete restrict,
  feature_pipeline_id text not null references public.flexmap_ml_feature_pipelines(feature_pipeline_id) on delete restrict,
  task text not null,
  model_type text not null check (model_type in ('LOGISTIC_REGRESSION','RANDOM_FOREST')),
  status text not null check (status in ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')),
  stage text not null,
  evaluation_scope text not null check (evaluation_scope in ('RESEARCH','DEVELOPMENT_ONLY')),
  configuration jsonb not null,
  metrics jsonb,
  feature_importance jsonb,
  artifact_manifest jsonb not null default '[]'::jsonb,
  error text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz
);

create table if not exists public.flexmap_ml_models (
  model_id text primary key,
  version integer not null check (version > 0),
  training_run_id text not null unique references public.flexmap_ml_training_runs(training_run_id) on delete restrict,
  dataset_version_id text not null references public.flexmap_ml_dataset_versions(dataset_version_id) on delete restrict,
  manifest_sha256 text not null check (manifest_sha256 ~ '^[0-9a-f]{64}$'),
  split_id text not null references public.flexmap_ml_splits(split_id) on delete restrict,
  feature_pipeline_id text not null references public.flexmap_ml_feature_pipelines(feature_pipeline_id) on delete restrict,
  task text not null,
  model_type text not null,
  status text not null check (status in ('EXPERIMENTAL','VALIDATED')),
  notes text not null default '',
  created_at timestamptz not null default now()
);

create table if not exists public.flexmap_ml_audit (
  audit_id bigint generated always as identity primary key,
  entity_type text not null,
  entity_id text not null,
  action text not null,
  previous_value jsonb,
  new_value jsonb,
  actor text not null default 'MASTER',
  occurred_at timestamptz not null default now()
);

create table if not exists public.flexmap_emg_comparison_experiments (
  experiment_id text primary key,
  name text not null,
  source_type text not null,
  task text not null,
  status text not null check (status in ('QUEUED','RUNNING','COMPLETED','FAILED','CANCEL_REQUESTED','CANCELLED')),
  configuration jsonb not null,
  results jsonb,
  artifact_manifest jsonb not null default '[]'::jsonb,
  evaluation_scope text not null default 'DEVELOPMENT_ONLY' check (evaluation_scope = 'DEVELOPMENT_ONLY'),
  error text,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

create index if not exists flexmap_ml_training_runs_dataset_idx on public.flexmap_ml_training_runs(dataset_version_id, created_at desc);
create index if not exists flexmap_ml_models_task_idx on public.flexmap_ml_models(task, model_type, version desc);
create index if not exists flexmap_ml_audit_entity_idx on public.flexmap_ml_audit(entity_type, entity_id, occurred_at desc);
create index if not exists flexmap_emg_comparison_created_idx on public.flexmap_emg_comparison_experiments(created_at desc);

-- Provision the private `flexmap-ml-vault` bucket through the Supabase
-- Storage API or Dashboard before applying this migration. Current Supabase
-- guidance treats storage schema metadata as read-only; this migration only
-- installs narrowly scoped object policies for that pre-created bucket.

alter table public.flexmap_ml_dataset_versions enable row level security;
alter table public.flexmap_ml_feature_pipelines enable row level security;
alter table public.flexmap_ml_splits enable row level security;
alter table public.flexmap_ml_training_runs enable row level security;
alter table public.flexmap_ml_models enable row level security;
alter table public.flexmap_ml_audit enable row level security;
alter table public.flexmap_emg_comparison_experiments enable row level security;

revoke all on public.flexmap_ml_dataset_versions, public.flexmap_ml_feature_pipelines,
  public.flexmap_ml_splits, public.flexmap_ml_training_runs, public.flexmap_ml_models,
  public.flexmap_ml_audit, public.flexmap_emg_comparison_experiments from anon, authenticated;
grant select, insert, update on public.flexmap_ml_dataset_versions, public.flexmap_ml_feature_pipelines,
  public.flexmap_ml_splits, public.flexmap_ml_training_runs, public.flexmap_ml_models to service_role;
grant select, insert, update on public.flexmap_emg_comparison_experiments to service_role;
grant select, insert on public.flexmap_ml_audit to service_role;
grant usage, select on sequence public.flexmap_ml_audit_audit_id_seq to service_role;

drop policy if exists flexmap_ml_service_read on storage.objects;
drop policy if exists flexmap_ml_service_write on storage.objects;
create policy flexmap_ml_service_read on storage.objects for select to service_role
  using (bucket_id = 'flexmap-ml-vault');
create policy flexmap_ml_service_write on storage.objects for all to service_role
  using (bucket_id = 'flexmap-ml-vault') with check (bucket_id = 'flexmap-ml-vault');

commit;
