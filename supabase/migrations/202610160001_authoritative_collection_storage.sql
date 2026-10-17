-- FlexMap authoritative collection storage (additive; no destructive data reset).
begin;

create table if not exists public.flexmap_schema_migrations (
  version text primary key,
  description text not null,
  applied_at timestamptz not null default now()
);

create table if not exists public.flexmap_rehab_modules (
  module_id text primary key,
  slug text not null unique,
  display_name text not null,
  description text not null default '',
  enabled boolean not null default true,
  patient_enabled boolean not null default false,
  display_order integer not null default 0,
  configuration jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Seed once only. Later user edits are preserved because conflicts are ignored.
insert into public.flexmap_rehab_modules(module_id, slug, display_name, description, patient_enabled, display_order)
values
  ('STARTING_POSTURE','starting_posture','Starting Posture','Starting-position and setup posture recordings.',false,1),
  ('REACHING','reaching','Reaching','Goal-directed upper-limb reaching recordings.',true,2),
  ('ELBOW_EXTENSION','elbow_extension','Elbow Extension','Elbow-extension movement recordings.',true,3),
  ('TRUNK_CONTROL','trunk_control','Trunk Control','Trunk-position and trunk-movement recordings.',false,4)
on conflict (module_id) do nothing;

-- Some early FlexMap projects applied only the legacy vault foundation. Keep
-- this migration additive and self-contained so its foreign keys never assume
-- that the later browser-collection tables already exist.
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

create table if not exists public.flexmap_collection_sessions (
  session_id text primary key,
  dataset_id text references public.flexmap_browser_datasets(dataset_id) on delete restrict,
  subject_code text,
  protocol_id text,
  protocol_snapshot jsonb not null default '{}'::jsonb,
  hardware_snapshot jsonb not null default '{}'::jsonb,
  model_snapshot jsonb not null default '{}'::jsonb,
  consent_scope jsonb not null default '{}'::jsonb,
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  revision bigint not null default 1
);

alter table public.flexmap_browser_samples
  add column if not exists cloud_id uuid default gen_random_uuid(),
  add column if not exists original_recording_id text,
  add column if not exists modality text not null default 'CV',
  add column if not exists persistence_status text not null default 'STORED',
  add column if not exists verified_at timestamptz,
  add column if not exists failure_reason text,
  add column if not exists revision bigint not null default 1,
  add column if not exists consent_scope jsonb not null default '{}'::jsonb,
  add column if not exists processing_versions jsonb not null default '{}'::jsonb;

create unique index if not exists flexmap_browser_samples_cloud_id_idx on public.flexmap_browser_samples(cloud_id);
create index if not exists flexmap_browser_samples_persistence_idx on public.flexmap_browser_samples(persistence_status, updated_at);

create table if not exists public.flexmap_recording_artifacts (
  artifact_id uuid primary key default gen_random_uuid(),
  sample_id text not null references public.flexmap_browser_samples(sample_id) on delete restrict,
  artifact_role text not null,
  object_path text not null unique,
  content_type text not null,
  byte_size bigint not null check (byte_size >= 0),
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  verification_status text not null default 'PENDING' check (verification_status in ('PENDING','VERIFIED','FAILED')),
  derived_version text,
  created_at timestamptz not null default now(),
  verified_at timestamptz,
  unique(sample_id, artifact_role, derived_version)
);

create table if not exists public.flexmap_upload_sessions (
  upload_id uuid primary key default gen_random_uuid(),
  sample_id text not null references public.flexmap_browser_samples(sample_id) on delete restrict,
  state text not null check (state in ('DRAFT','UPLOADING','VERIFYING','STORED','FAILED','INTERRUPTED')),
  expected_artifacts jsonb not null default '[]'::jsonb,
  error_code text,
  expires_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.flexmap_research_audit_events (
  audit_id bigint generated always as identity primary key,
  entity_type text not null,
  entity_id text not null,
  action text not null,
  previous_revision bigint,
  new_revision bigint,
  details jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now()
);

create index if not exists flexmap_recording_artifacts_sample_idx on public.flexmap_recording_artifacts(sample_id);
create index if not exists flexmap_upload_sessions_state_idx on public.flexmap_upload_sessions(state, updated_at);
create index if not exists flexmap_research_audit_entity_idx on public.flexmap_research_audit_events(entity_type, entity_id, occurred_at desc);

create or replace view public.flexmap_browser_dataset_stats
with (security_invoker = true) as
select d.dataset_id,
  coalesce(l.label_count, 0)::bigint as label_count,
  coalesce(s.still_count, 0)::bigint as still_count,
  coalesce(s.video_count, 0)::bigint as video_count,
  coalesce(s.reviewed_count, 0)::bigint as reviewed_count,
  coalesce(s.approved_count, 0)::bigint as approved_count,
  s.last_sample_at
from public.flexmap_browser_datasets d
left join (
  select dataset_id, count(*) filter (where not archived) as label_count
  from public.flexmap_browser_labels group by dataset_id
) l on l.dataset_id = d.dataset_id
left join (
  select dataset_id,
    count(*) filter (where sample_type = 'STILL') as still_count,
    count(*) filter (where sample_type = 'VIDEO') as video_count,
    count(*) filter (where review_status <> 'REVIEW_REQUIRED') as reviewed_count,
    count(*) filter (where review_status = 'APPROVED') as approved_count,
    max(created_at) as last_sample_at
  from public.flexmap_browser_samples
  where trashed_at is null and persistence_status = 'STORED'
  group by dataset_id
) s on s.dataset_id = d.dataset_id;

alter table public.flexmap_schema_migrations enable row level security;
alter table public.flexmap_rehab_modules enable row level security;
alter table public.flexmap_browser_datasets enable row level security;
alter table public.flexmap_browser_labels enable row level security;
alter table public.flexmap_browser_samples enable row level security;
alter table public.flexmap_browser_label_audit enable row level security;
alter table public.flexmap_collection_sessions enable row level security;
alter table public.flexmap_recording_artifacts enable row level security;
alter table public.flexmap_upload_sessions enable row level security;
alter table public.flexmap_research_audit_events enable row level security;

revoke all on public.flexmap_schema_migrations, public.flexmap_rehab_modules,
  public.flexmap_browser_datasets, public.flexmap_browser_labels,
  public.flexmap_browser_samples, public.flexmap_browser_label_audit,
  public.flexmap_collection_sessions, public.flexmap_recording_artifacts,
  public.flexmap_upload_sessions, public.flexmap_research_audit_events from anon, authenticated;
revoke all on public.flexmap_browser_dataset_stats from anon, authenticated;
grant select, insert, update, delete on public.flexmap_schema_migrations,
  public.flexmap_rehab_modules, public.flexmap_browser_datasets,
  public.flexmap_browser_labels, public.flexmap_browser_samples,
  public.flexmap_browser_label_audit, public.flexmap_collection_sessions,
  public.flexmap_recording_artifacts, public.flexmap_upload_sessions,
  public.flexmap_research_audit_events to service_role;
grant select on public.flexmap_browser_dataset_stats to service_role;
grant usage, select on sequence public.flexmap_research_audit_events_audit_id_seq to service_role;
grant usage, select on sequence public.flexmap_browser_label_audit_audit_id_seq to service_role;

insert into public.flexmap_schema_migrations(version, description)
values ('202610160001', 'Authoritative collection metadata, artifact lifecycle, and audit schema')
on conflict (version) do nothing;

commit;
