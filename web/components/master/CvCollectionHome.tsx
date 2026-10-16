"use client";

import Link from "next/link";
import { Camera, Database, Image as ImageIcon, Plus, Search, Video, X } from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import type { BrowserCollectionDataset, BrowserCollectionStatus, CaptureType } from "@/types/browserCollection";
import type { RehabModule } from "@/types/dataset";
import { RehabModuleCards } from "./RehabModuleCards";

const api = "/api/master/data";
const initial = { name: "", rehabilitation_module_id: "", description: "", initial_label_name: "", instructions: "", camera_view: "FRONT", relevant_side: "N/A", observation_profile: "FULL_POSE", permitted_capture_types: "BOTH" as CaptureType, protocol_id: "", session_id: "", data_purpose: "RESEARCH", allow_raw_media: true, allow_annotated_media: false, allow_thumbnails: true };

export function CvCollectionHome() {
  const [datasets, setDatasets] = useState<BrowserCollectionDataset[]>([]);
  const [modules, setModules] = useState<RehabModule[]>([]);
  const [storage, setStorage] = useState<BrowserCollectionStatus | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState(initial);
  const [search, setSearch] = useState("");
  const [moduleFilter, setModuleFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("ACTIVE");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const query = new URLSearchParams({ search, module_id: moduleFilter, capture_type: typeFilter, status: statusFilter });
    const [datasetResponse, moduleResponse, statusResponse] = await Promise.all([
      fetch(`${api}/browser-collections?${query}`, { cache: "no-store" }),
      fetch(`${api}/rehab-modules`, { cache: "no-store" }),
      fetch(`${api}/browser-collections/status`, { cache: "no-store" }),
    ]);
    if (moduleResponse.ok) setModules((await moduleResponse.json()).filter((item: RehabModule) => item.id !== "UNASSIGNED"));
    if (statusResponse.ok) setStorage(await statusResponse.json());
    if (datasetResponse.ok) { setDatasets(await datasetResponse.json()); setError(""); }
    else { const body = await datasetResponse.json().catch(() => ({})); setDatasets([]); setError(body.detail || "Browser datasets could not be loaded."); }
  }, [search, moduleFilter, typeFilter, statusFilter]);

  useEffect(() => { void load(); }, [load]);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!storage?.configured) return;
    setBusy(true); setError("");
    const response = await fetch(`${api}/browser-collections`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...form, protocol_id: form.protocol_id || null, session_id: form.session_id || null }) });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) setError(body.detail || "Dataset creation failed.");
    else { setForm(initial); setShowNew(false); await load(); }
    setBusy(false);
  }

  const recent = useMemo(() => [...datasets].filter((item) => item.last_sample_at).sort((a, b) => String(b.last_sample_at).localeCompare(String(a.last_sample_at))).slice(0, 5), [datasets]);

  return <section className="collection-home">
    <header className="collection-home-title">
      <div><span className="eyebrow">Master-only browser and engine acquisition</span><h1>CV Collection Studio</h1><p className="master-lead">Create posture datasets, capture browser MediaPipe stills or videos, and review durable Vault samples.</p></div>
      <button className="primary" onClick={() => setShowNew(true)}><Plus/>New dataset</button>
    </header>

    <div className={`collection-storage ${storage?.configured ? "is-ready" : "is-blocked"}`}>
      <Database/>
      <div><strong>{storage?.configured ? "Durable collection storage ready" : "Browser collection storage is not configured"}</strong><span>{storage?.configured ? `Private Supabase bucket: ${storage.bucket}` : `Missing: ${storage?.missing.join(", ") || "checking configuration"}. Cloud save is blocked; captured packages can still be downloaded locally.`}</span></div>
    </div>

    {showNew && <div className="collection-modal-backdrop"><form className="collection-modal" onSubmit={create}>
      <button type="button" className="modal-close" aria-label="Close" onClick={() => setShowNew(false)}><X/></button>
      <span className="eyebrow">New posture dataset</span><h2>Create dataset</h2>
      <label>Dataset name*<input required maxLength={120} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })}/></label>
      <label>Parent rehabilitation module*<select required value={form.rehabilitation_module_id} onChange={(event) => setForm({ ...form, rehabilitation_module_id: event.target.value })}><option value="">Select module</option>{modules.map((module) => <option key={module.id} value={module.id}>{module.name}</option>)}</select></label>
      <label>Initial posture label*<input required pattern="[a-zA-Z][a-zA-Z0-9 _-]+" placeholder="acceptable_start" value={form.initial_label_name} onChange={(event) => setForm({ ...form, initial_label_name: event.target.value })}/></label>
      <label>Description<textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })}/></label>
      <details><summary>Advanced settings</summary>
        <label>Capture instructions<textarea value={form.instructions} onChange={(event) => setForm({ ...form, instructions: event.target.value })}/></label>
        <div className="field-pair"><label>Camera view<select value={form.camera_view} onChange={(event) => setForm({ ...form, camera_view: event.target.value })}><option>FRONT</option><option>LEFT</option><option>RIGHT</option><option>OTHER</option></select></label><label>Relevant side<select value={form.relevant_side} onChange={(event) => setForm({ ...form, relevant_side: event.target.value })}><option>N/A</option><option>LEFT</option><option>RIGHT</option><option>BILATERAL</option></select></label></div>
        <label>Permitted capture types<select value={form.permitted_capture_types} onChange={(event) => setForm({ ...form, permitted_capture_types: event.target.value as CaptureType })}><option>BOTH</option><option>STILL</option><option>VIDEO</option></select></label>
        <div className="field-pair"><label>Protocol ID<input value={form.protocol_id} onChange={(event) => setForm({ ...form, protocol_id: event.target.value })}/></label><label>Session ID<input value={form.session_id} onChange={(event) => setForm({ ...form, session_id: event.target.value })}/></label></div>
        <label className="check"><input type="checkbox" checked={form.allow_raw_media} onChange={(event) => setForm({ ...form, allow_raw_media: event.target.checked })}/> Permit private raw camera media</label>
        <label className="check"><input type="checkbox" checked={form.allow_thumbnails} onChange={(event) => setForm({ ...form, allow_thumbnails: event.target.checked })}/> Permit private thumbnails</label>
      </details>
      {!storage?.configured && <p className="master-alert">Configure the listed Supabase variables and run the additive migration before creating hosted datasets.</p>}
      {error && <p className="master-alert">{error}</p>}
      <div className="collection-modal-actions"><button type="button" onClick={() => setShowNew(false)}>Cancel</button><button className="primary" disabled={busy || !storage?.configured}>{busy ? "Creating…" : "Create dataset"}</button></div>
    </form></div>}

    <div className="collection-filters">
      <label><Search/><input aria-label="Search browser datasets" placeholder="Search datasets" value={search} onChange={(event) => setSearch(event.target.value)}/></label>
      <select aria-label="Filter rehabilitation module" value={moduleFilter} onChange={(event) => setModuleFilter(event.target.value)}><option value="">All modules</option>{modules.map((module) => <option key={module.id} value={module.id}>{module.name}</option>)}</select>
      <select aria-label="Filter capture type" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}><option value="">Still and video</option><option>STILL</option><option>VIDEO</option></select>
      <select aria-label="Filter source" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}><option value="">All sources</option><option value="BROWSER_MEDIAPIPE">Browser MediaPipe</option><option value="FLEXMAP_ENGINE">FlexMap Engine</option></select>
      <select aria-label="Filter status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="ACTIVE">Active</option><option value="ARCHIVED">Archived</option><option value="">All statuses</option></select>
    </div>

    {error && <p className="master-alert">{error}</p>}
    {sourceFilter !== "FLEXMAP_ENGINE" && <div className="collection-dataset-grid">{datasets.map((dataset) => <article className="collection-dataset-card" key={dataset.dataset_id}>
      <div className="collection-dataset-head"><Camera/><span>{dataset.archived ? "ARCHIVED" : dataset.permitted_capture_types}</span></div>
      <h2>{dataset.name}</h2><p>{dataset.description || "No description"}</p><small>{modules.find((module) => module.id === dataset.rehabilitation_module_id)?.name || dataset.rehabilitation_module_id}</small>
      <dl><div><dt>Labels</dt><dd>{dataset.label_count}</dd></div><div><dt>Stills</dt><dd>{dataset.still_count}</dd></div><div><dt>Videos</dt><dd>{dataset.video_count}</dd></div><div><dt>Approved</dt><dd>{dataset.approved_count}</dd></div></dl>
      <span className="collection-updated">Updated {new Date(dataset.updated_at).toLocaleString()}</span>
      <Link className="primary" href={`/master/cv-data/studio?dataset=${dataset.dataset_id}`}>Collect samples</Link>
    </article>)}</div>}
    {!datasets.length && storage?.configured && !error && <div className="master-empty"><ImageIcon/><h2>No browser datasets yet</h2><p>Create a dataset to begin still or video collection.</p></div>}

    {recent.length > 0 && <section className="collection-recent"><h2>Recent collection activity</h2>{recent.map((dataset) => <Link key={dataset.dataset_id} href={`/master/cv-data/studio?dataset=${dataset.dataset_id}`}><Video/><span><strong>{dataset.name}</strong><small>{dataset.last_sample_at ? new Date(dataset.last_sample_at).toLocaleString() : ""}</small></span></Link>)}</section>}

    {sourceFilter !== "BROWSER_MEDIAPIPE" && <div className="collection-legacy"><span className="eyebrow">Existing Python-engine collections</span><h2>Rehabilitation module collection</h2><p>These established modules continue to use the FlexMap engine recorder.</p><RehabModuleCards destination="collection"/></div>}
  </section>;
}
