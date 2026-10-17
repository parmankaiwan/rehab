"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, Database, RefreshCw } from "lucide-react";

type Dataset = {
  dataset_id: string;
  name: string;
  description: string;
  muscle_under_study?: string;
  recording_purpose?: string;
  labels: Array<{ label_id: string; display_name: string }>;
  recording_count: number;
  approved_count: number;
  training_eligible_count: number;
  duration_seconds: number;
  channel_count: number;
  last_recording_at?: string;
};
type Recording = { recording_id: string; dataset_id: string; research_label: string; subject_code: string; duration_seconds: number; channel_count: number; review_status: string; persistence_status: string; created_at: string };

const endpoint = "/api/master/data/emg/datasets";

export function EmgCloudDatasetVault() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [response, recordingResponse] = await Promise.all([fetch(endpoint, { cache: "no-store" }), fetch("/api/master/data/emg/cloud-recordings", { cache: "no-store" })]);
      const [payload, recordingPayload] = await Promise.all([response.json().catch(() => ({})), recordingResponse.json().catch(() => ({}))]);
      if (!response.ok) throw new Error(payload.detail || payload.error || `Dataset request failed (${response.status})`);
      if (!recordingResponse.ok) throw new Error(recordingPayload.detail || recordingPayload.error || `Recording request failed (${recordingResponse.status})`);
      if (!Array.isArray(payload) || !Array.isArray(recordingPayload)) throw new Error("EMG vault response has an invalid shape");
      setDatasets(payload); setRecordings(recordingPayload);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "EMG cloud vault is unavailable");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);
  const visible = useMemo(() => datasets.filter((dataset) => `${dataset.name} ${dataset.description} ${dataset.muscle_under_study || ""}`.toLowerCase().includes(query.toLowerCase())), [datasets, query]);
  const totals = datasets.reduce((value, dataset) => ({ recordings: value.recordings + dataset.recording_count, duration: value.duration + dataset.duration_seconds, channels: Math.max(value.channels, dataset.channel_count), approved: value.approved + dataset.approved_count }), { recordings: 0, duration: 0, channels: 0, approved: 0 });

  return <section className="collection-legacy" aria-label="Authoritative EMG datasets">
    <div className="ml-page-head">
      <div><span className="eyebrow">Authoritative private storage</span><h2>Cloud EMG datasets</h2><p>EMG metadata and artifacts are isolated from the CV vault.</p></div>
      <button onClick={load} disabled={loading}><RefreshCw />Refresh</button>
    </div>
    {error && <div className="emgc-alert"><AlertTriangle />{error}</div>}
    <div className="emgc-kpis">
      <article><Database /><span>Datasets<strong>{datasets.length}</strong></span></article>
      <article><Activity /><span>Recordings<strong>{totals.recordings}</strong></span></article>
      <article><Activity /><span>Recorded duration<strong>{Math.round(totals.duration)}s</strong></span></article>
      <article><Activity /><span>Approved<strong>{totals.approved}</strong></span></article>
    </div>
    <label>Search EMG datasets<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Dataset, muscle, or description" /></label>
    {loading ? <p>Loading EMG datasets…</p> : visible.length ? <div className="browser-dataset-grid">{visible.map((dataset) => <article className="browser-dataset-card" key={dataset.dataset_id}>
      <span className="eyebrow">{dataset.muscle_under_study || "EMG research"}</span>
      <h3>{dataset.name}</h3>
      <p>{dataset.description || dataset.recording_purpose || "No description"}</p>
      <p>{dataset.labels.map((label) => label.display_name).join(" · ") || "No labels"}</p>
      <dl><div><dt>Recordings</dt><dd>{dataset.recording_count}</dd></div><div><dt>Channels</dt><dd>{dataset.channel_count || "—"}</dd></div><div><dt>Approved</dt><dd>{dataset.approved_count}</dd></div></dl>
      <Link href="/master/emg">Collect more data</Link>
    </article>)}</div> : !error && <p>No durable EMG datasets exist yet. Create one from EMG Collection.</p>}
    {recordings.length > 0 && <div className="emgc-table-card"><div><span className="eyebrow">Stored waveforms</span><h2>Recent cloud EMG recordings</h2></div><table><thead><tr><th>Recording</th><th>Dataset / label</th><th>Subject</th><th>Signal</th><th>Status</th><th /></tr></thead><tbody>{recordings.map((recording) => <tr key={recording.recording_id}><td>{recording.recording_id}</td><td>{datasets.find((dataset) => dataset.dataset_id === recording.dataset_id)?.name || recording.dataset_id}<small>{recording.research_label}</small></td><td>{recording.subject_code}</td><td>{recording.channel_count} ch · {recording.duration_seconds.toFixed(1)}s</td><td>{recording.review_status}</td><td><Link href={`/master/dataset/emg/${recording.recording_id}`}>Open waveform</Link></td></tr>)}</tbody></table></div>}
  </section>;
}
