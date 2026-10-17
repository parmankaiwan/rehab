"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckSquare, Cloud, Database, FlaskConical, RefreshCw, Trash2, X } from "lucide-react";
import type { DatasetHealth, SupabaseSyncResult, SupabaseVaultStatus } from "@/types/dataset";
import type { DatasetVersion, MlVaultRecording } from "@/types/ml";
function Distribution({
  title,
  values,
}: {
  title: string;
  values: Record<string, number>;
}) {
  return (
    <div className="distribution">
      <h3>{title}</h3>
      {Object.entries(values)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 12)
        .map(([name, count]) => (
          <div key={name}>
            <span>{name}</span>
            <strong>{count}</strong>
          </div>
        ))}
    </div>
  );
}
function message(value: string) {
  return value.replaceAll("_", " ").toLowerCase();
}
export function DatasetVault({ modalityFilter, title }: { modalityFilter?: "CV" | "EMG"; title?: string } = {}) {
  const router = useRouter(),
    [rows, setRows] = useState<MlVaultRecording[]>([]),
    [stats, setStats] = useState<DatasetHealth | null>(null),
    [search, setSearch] = useState(""),
    [rehab, setRehab] = useState(""),
    [modality, setModality] = useState(modalityFilter || ""),
    [eligible, setEligible] = useState(true),
    [selecting, setSelecting] = useState(false),
    [selected, setSelected] = useState<Set<string>>(new Set()),
    [draft, setDraft] = useState<DatasetVersion | null>(null),
    [busy, setBusy] = useState(false),
    [syncing, setSyncing] = useState(false),
    [supabase, setSupabase] = useState<SupabaseVaultStatus | null>(null),
    [syncMessage, setSyncMessage] = useState(""),
    [deleting, setDeleting] = useState<string | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    const q = new URLSearchParams();
    if (rehab) q.set("rehab_type", rehab);
    const selectedModality = modalityFilter || modality;
    if (selectedModality) q.set("modality", selectedModality);
    if (eligible) q.set("eligible", "true");
    Promise.all([
      fetch(`/api/master/data/ml/vault-recordings?${q}`),
      fetch("/api/master/data/dataset/stats"),
      fetch("/api/master/data/ml/supabase/status?check=true"),
    ]).then(async ([a, b, c]) => {
      if (a.ok) setRows(await a.json());
      if (b.ok) setStats(await b.json());
      if (c.ok) setSupabase(await c.json());
    });
  }, [rehab, modality, modalityFilter, eligible]);
  const filtered = useMemo(
    () =>
      rows.filter(
        (x) =>
          !search ||
          [x.recording_id, x.subject_id, x.session_id, x.research_label].some(
            (v) => v?.toLowerCase().includes(search.toLowerCase()),
          ),
      ),
    [rows, search],
  );
  const chosen = filtered.filter((x) => selected.has(x.recording_id)),
    modalities = new Set(chosen.map((x) => x.modality)),
    rehabs = new Set(chosen.map((x) => x.rehab_type));
  function toggle(id: string) {
    setSelected((old) => {
      const next = new Set(old);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  async function preview() {
    setBusy(true);
    setError("");
    const response = await fetch("/api/master/data/ml/datasets/from-vault", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        recording_ids: [...selected],
        name: `${rehabs.values().next().value || "DATASET"}_${modalities.values().next().value || "DATA"}_${new Date().toISOString().slice(0, 10)}`,
        source_query: {
          rehab_type: rehab,
          modality: modalityFilter || modality,
          eligible: String(eligible),
        },
      }),
    });
    const body = await response.json();
    setBusy(false);
    if (response.ok) setDraft(body);
    else
      setError(
        typeof body.detail === "string"
          ? body.detail
          : body.detail?.health?.errors?.join(" · ") || "Dataset is not ready",
      );
  }
  async function freeze() {
    if (!draft) return;
    setBusy(true);
    const response = await fetch(
      `/api/master/data/ml/datasets/${draft.dataset_version_id}/freeze`,
      { method: "POST" },
    );
    const body = await response.json();
    setBusy(false);
    if (response.ok)
      router.push(`/master/ml/train?dataset=${body.dataset_version_id}`);
    else setError(body.detail || "Could not freeze dataset");
  }
  async function deleteRecording(row: MlVaultRecording) {
    const confirmed = window.confirm(
      `Permanently delete ${row.recording_id} and all of its saved ${row.modality} files? This cannot be undone.`,
    );
    if (!confirmed) return;
    setDeleting(row.recording_id);
    setError("");
    try {
      const id = encodeURIComponent(row.recording_id);
      const response = await fetch(
        `/api/master/data/ml/vault-recordings/${id}?confirm=${id}`,
        { method: "DELETE" },
      );
      const body = await response.json().catch(() => ({}));
      if (!response.ok)
        throw new Error(body.detail || "Recording could not be deleted");
      setRows((current) =>
        current.filter((item) => item.recording_id !== row.recording_id),
      );
      setSelected((current) => {
        const next = new Set(current);
        next.delete(row.recording_id);
        return next;
      });
      const statsResponse = await fetch("/api/master/data/dataset/stats", {
        cache: "no-store",
      });
      if (statsResponse.ok) setStats(await statsResponse.json());
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Recording could not be deleted",
      );
    } finally {
      setDeleting(null);
    }
  }
  async function syncVault() {
    setSyncing(true);
    setSyncMessage("");
    setError("");
    try {
      const response = await fetch("/api/master/data/ml/supabase/sync", {
        method: "POST",
      });
      const body = (await response.json().catch(() => ({}))) as Partial<SupabaseSyncResult> & { detail?: string };
      if (!response.ok) throw new Error(body.detail || "Supabase sync failed");
      setSyncMessage(`${body.synced || 0} of ${body.total || 0} recordings synced${body.failed ? `, ${body.failed} failed` : ""}.`);
      const statusResponse = await fetch("/api/master/data/ml/supabase/status?check=true", { cache: "no-store" });
      if (statusResponse.ok) setSupabase(await statusResponse.json());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Supabase sync failed");
    } finally {
      setSyncing(false);
    }
  }
  return (
    <section className="vault-page">
      <div className="ml-page-head">
        <div>
          <span className="eyebrow">Canonical research data</span>
          <h1>{title || "Dataset Vault"}</h1>
          <p className="master-lead">
            Review recordings or freeze an eligible selection for reproducible
            model training.
          </p>
        </div>
        <button
          className={selecting ? "secondary" : "primary"}
          onClick={() => {
            setSelecting(!selecting);
            setSelected(new Set());
            setDraft(null);
          }}
        >
          {selecting ? <X /> : <FlaskConical />}
          {selecting ? "Exit selection" : "Select for training"}
        </button>
      </div>
      <div className="stat-grid">
        <div>
          <strong>{stats?.total_samples || 0}</strong>
          <span>Recordings</span>
        </div>
        <div>
          <strong>{stats?.training_eligible || 0}</strong>
          <span>Training eligible</span>
        </div>
        <div>
          <strong>{stats?.excluded || 0}</strong>
          <span>Excluded</span>
        </div>
        <div>
          <strong>
            {((stats?.storage_bytes || 0) / 1048576).toFixed(1)} MB
          </strong>
          <span>Canonical storage</span>
        </div>
      </div>
      <section className={`vault-cloud-status ${supabase?.reachable ? "is-online" : ""}`} aria-label="Supabase vault connection">
        <Cloud />
        <div>
          <strong>Supabase vault mirror</strong>
          <span>
            {!supabase?.configured
              ? "Not configured — local Dataset Vault remains active."
              : !supabase.enabled
                ? "Configured but synchronization is disabled."
                : supabase.reachable
                  ? `Connected to ${supabase.project_host}`
                  : `Connection unavailable${supabase.error ? `: ${supabase.error}` : ""}`}
          </span>
          {syncMessage && <small>{syncMessage}</small>}
        </div>
        <button disabled={!supabase?.configured || !supabase.enabled || syncing} onClick={() => void syncVault()}>
          <RefreshCw className={syncing ? "is-spinning" : ""} />
          {syncing ? "Syncing…" : "Sync vault"}
        </button>
      </section>
      {!selecting && (
        <div className="health-distributions">
          <Distribution
            title="Label distribution"
            values={stats?.label_counts || {}}
          />
          <Distribution
            title="Anonymous subjects"
            values={stats?.subject_counts || {}}
          />
          <Distribution
            title="Technical quality"
            values={stats?.quality_counts || {}}
          />
        </div>
      )}
      <div className="vault-tools ml-vault-filters">
        <input
          aria-label="Search recordings"
          placeholder="Recording, subject, session, or label"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {!modalityFilter && <select
          aria-label="Rehab type"
          value={rehab}
          onChange={(e) => setRehab(e.target.value)}
        >
          <option value="">All rehab modules</option>
          {[...new Set(rows.map((x) => x.rehab_type))].map((x) => (
            <option key={x}>{x}</option>
          ))}
        </select>}
        <select
          aria-label="Modality"
          value={modality}
          onChange={(e) => {
            setModality(e.target.value);
            setSelected(new Set());
          }}
        >
          <option value="">CV and EMG</option>
          <option>CV</option>
          <option>EMG</option>
        </select>
        {selecting && (
          <label className="ml-inline-check">
            <input
              type="checkbox"
              checked={eligible}
              onChange={(e) => setEligible(e.target.checked)}
            />
            Eligible only
          </label>
        )}
        <Link href="/master/ml/datasets">
          <Database />
          Frozen datasets
        </Link>
      </div>
      {selecting && (
        <div className="ml-selection-tools">
          <button
            onClick={() =>
              setSelected(
                new Set(
                  filtered
                    .filter((x) => x.training_eligible)
                    .map((x) => x.recording_id),
                ),
              )
            }
          >
            <CheckSquare />
            Select all matching filtered results (
            {filtered.filter((x) => x.training_eligible).length})
          </button>
          <span>This selects all matching results, not only visible rows.</span>
        </div>
      )}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {selecting && <th>Select</th>}
              <th>Recording</th>
              <th>Subject / Session</th>
              <th>Rehab / Label</th>
              <th>Modality</th>
              <th>Quality</th>
              <th>Governance</th>
              {!selecting && <th className="vault-delete-cell">Actions</th>}
            </tr>
          </thead>
          <tbody>
            {filtered.map((row) => (
              <tr
                key={row.recording_id}
                className={!row.training_eligible ? "ml-row-disabled" : ""}
              >
                {selecting && (
                  <td>
                    <input
                      aria-label={`Select ${row.recording_id}`}
                      type="checkbox"
                      disabled={!row.training_eligible}
                      checked={selected.has(row.recording_id)}
                      onChange={() => toggle(row.recording_id)}
                    />
                  </td>
                )}
                <td>
                  <Link
                    href={
                      row.modality === "CV"
                        ? `/master/dataset/${row.recording_id}`
                        : `/master/emg/recordings/${row.recording_id}`
                    }
                  >
                    {row.recording_id}
                  </Link>
                  <small>{new Date(row.created_at).toLocaleString()}</small>
                </td>
                <td>
                  {row.subject_id}
                  <small>{row.session_id || "No session"}</small>
                </td>
                <td>
                  {row.rehab_type}
                  <small>{row.research_label}</small>
                </td>
                <td>
                  <span className="status-token">{row.modality}</span>
                </td>
                <td>{row.technical_quality || "UNKNOWN"}</td>
                <td>
                  <span className="approved">{row.review_status}</span>
                  <small>
                    {row.training_eligible
                      ? "Training eligible"
                      : message(row.eligibility_reason)}
                  </small>
                </td>
                {!selecting && (
                  <td className="vault-delete-cell">
                    <button
                      className="vault-delete-button"
                      disabled={deleting === row.recording_id}
                      onClick={() => void deleteRecording(row)}
                      aria-label={`Delete ${row.recording_id}`}
                    >
                      <Trash2 />
                      {deleting === row.recording_id ? "Deleting…" : "Delete"}
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {!filtered.length && (
          <p className="empty-row">No recordings match these filters.</p>
        )}
      </div>
      {selecting && selected.size > 0 && (
        <div className="ml-selection-bar">
          <strong>{selected.size} recordings selected</strong>
          <span>
            {modalities.size > 1
              ? "Multiple modalities selected — create separate datasets."
              : rehabs.size > 1
                ? "Multiple rehab modules selected — selection blocked."
                : "Ready to review as one frozen dataset."}
          </span>
          <button onClick={() => setSelected(new Set())}>Clear</button>
          <button
            className="primary"
            disabled={busy || modalities.size !== 1 || rehabs.size !== 1}
            onClick={preview}
          >
            Use for training
          </button>
        </div>
      )}
      {draft && (
        <div className="ml-modal-backdrop">
          <article className="ml-dataset-preview">
            <button
              className="ml-close"
              onClick={() => setDraft(null)}
              aria-label="Close preview"
            >
              <X />
            </button>
            <span className="eyebrow">Create training dataset</span>
            <h2>{draft.name}</h2>
            <div className="ml-summary-grid">
              <div>
                <strong>{draft.modality}</strong>
                <span>Modality</span>
              </div>
              <div>
                <strong>{draft.recording_ids.length}</strong>
                <span>Recordings</span>
              </div>
              <div>
                <strong>
                  {Object.keys(draft.subject_distribution).length}
                </strong>
                <span>Subjects</span>
              </div>
              <div>
                <strong>{Object.keys(draft.label_distribution).length}</strong>
                <span>Labels</span>
              </div>
            </div>
            <Distribution
              title="Target labels"
              values={draft.label_distribution}
            />
            <Distribution
              title="Subject distribution"
              values={draft.subject_distribution}
            />
            <div className={`ml-health ${draft.health.state.toLowerCase()}`}>
              <strong>{draft.health.state}</strong>
              {draft.health.warnings.map((x) => (
                <span key={x}>{message(x)}</span>
              ))}
            </div>
            {error && <p className="master-alert">{error}</p>}
            <button
              className="primary"
              disabled={busy || draft.health.state === "NOT_READY"}
              onClick={freeze}
            >
              Freeze & continue to training
            </button>
          </article>
        </div>
      )}
      {error && !draft && <p className="master-alert">{error}</p>}
    </section>
  );
}
