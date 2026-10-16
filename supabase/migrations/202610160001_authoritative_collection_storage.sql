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
alter table public.flexmap_collection_sessions enable row level security;
alter table public.flexmap_recording_artifacts enable row level security;
alter table public.flexmap_upload_sessions enable row level security;
alter table public.flexmap_research_audit_events enable row level security;

revoke all on public.flexmap_schema_migrations, public.flexmap_rehab_modules,
  public.flexmap_collection_sessions, public.flexmap_recording_artifacts,
  public.flexmap_upload_sessions, public.flexmap_research_audit_events from anon, authenticated;
revoke all on public.flexmap_browser_dataset_stats from anon, authenticated;
grant select, insert, update, delete on public.flexmap_schema_migrations,
  public.flexmap_rehab_modules, public.flexmap_collection_sessions,
  public.flexmap_recording_artifacts, public.flexmap_upload_sessions,
  public.flexmap_research_audit_events to service_role;
grant select on public.flexmap_browser_dataset_stats to service_role;
grant usage, select on sequence public.flexmap_research_audit_events_audit_id_seq to service_role;

insert into public.flexmap_schema_migrations(version, description)
values ('202610160001', 'Authoritative collection metadata, artifact lifecycle, and audit schema')
on conflict (version) do nothing;

commit;
