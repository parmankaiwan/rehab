-- Cover every research-vault foreign key used for parent updates/deletes.
-- Additive only; no records or objects are modified.
create index if not exists flexmap_browser_label_audit_sample_fk_idx
  on public.flexmap_browser_label_audit(sample_id);
create index if not exists flexmap_browser_samples_label_fk_idx
  on public.flexmap_browser_samples(label_id);
create index if not exists flexmap_collection_sessions_dataset_fk_idx
  on public.flexmap_collection_sessions(dataset_id);
create index if not exists flexmap_emg_recordings_label_fk_idx
  on public.flexmap_emg_recordings(label_id);
create index if not exists flexmap_upload_sessions_sample_fk_idx
  on public.flexmap_upload_sessions(sample_id);
