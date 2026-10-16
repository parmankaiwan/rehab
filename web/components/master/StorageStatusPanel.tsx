"use client";

import { Database, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { apiErrorMessage, masterApiGet } from "@/lib/masterApi";

type StorageStatus = { mode: "LOCAL" | "SUPABASE"; state: string; database: string; schema: string; bucket: string; checked_at: string; last_successful_check?: string | null; pending_or_failed_uploads?: number | null; last_successful_upload?: string | null; verified_storage_bytes?: number | null; error?: string };

export function StorageStatusPanel() {
  const [status, setStatus] = useState<StorageStatus | null>(null), [error, setError] = useState(""), [notice, setNotice] = useState(""), [testing, setTesting] = useState(false);
  const load = useCallback(async () => { setError(""); try { setStatus(await masterApiGet<StorageStatus>("/api/master/data/storage/status", { retries: 1 })); } catch (cause) { setError(apiErrorMessage(cause)); } }, []);
  useEffect(() => { void load(); }, [load]);
  async function testConnection() { setTesting(true); setError(""); try { const response = await fetch("/api/master/data/storage/test", { method: "POST" }); const payload = await response.json(); if (!response.ok) throw new Error(payload?.error?.message || "Storage check failed."); setStatus(payload); } catch (cause) { setError(cause instanceof Error ? cause.message : "Storage check failed."); } finally { setTesting(false); } }
  async function reconcile() { setTesting(true); setError(""); setNotice(""); try { const response = await fetch("/api/master/data/storage/reconcile", { method: "POST" }); const payload = await response.json(); if (!response.ok) throw new Error(payload?.error?.message || "Reconciliation failed."); setNotice(`Checked ${payload.checked}; recovered ${payload.recovered}; still failed ${payload.still_failed}.`); await load(); } catch (cause) { setError(cause instanceof Error ? cause.message : "Reconciliation failed."); } finally { setTesting(false); } }
  return <section className="master-card storage-status-panel">
    <div><span className="eyebrow"><Database/>Durable collection storage</span><h2>Storage authority</h2><p>Connection checks run on the trusted backend. Secrets are never returned to this page.</p></div>
    {error && <p className="master-alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {status ? <dl>
      <div><dt>Active mode</dt><dd>{status.mode === "SUPABASE" ? "Supabase" : "Local"}</dd></div><div><dt>Overall state</dt><dd>{status.state.replaceAll("_", " ")}</dd></div>
      <div><dt>Database</dt><dd>{status.database.replaceAll("_", " ")}</dd></div><div><dt>Required schema</dt><dd>{status.schema.replaceAll("_", " ")}</dd></div>
      <div><dt>Private bucket</dt><dd>{status.bucket.replaceAll("_", " ")}</dd></div><div><dt>Pending / failed uploads</dt><dd>{status.pending_or_failed_uploads ?? "Unavailable"}</dd></div>
      <div><dt>Last successful check</dt><dd>{status.last_successful_check ? new Date(status.last_successful_check).toLocaleString() : "None"}</dd></div><div><dt>Verified storage usage</dt><dd>{status.verified_storage_bytes == null ? "Unavailable" : `${(status.verified_storage_bytes / 1048576).toFixed(1)} MB`}</dd></div>
    </dl> : <p>Checking storage…</p>}
    <div className="review-actions horizontal"><button className="system-refresh" onClick={testConnection} disabled={testing}><RefreshCw/>{testing ? "Working…" : "Test connection"}</button><button className="system-refresh" onClick={reconcile} disabled={testing || status?.mode !== "SUPABASE"}>Retry failed uploads</button></div>
  </section>;
}
