"use client";
/* eslint-disable @next/next/no-img-element */

import Link from "next/link";
import { Check, Download, RotateCcw, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { BrowserCollectionDataset, BrowserCollectionSample } from "@/types/browserCollection";

type SampleDetail = BrowserCollectionSample & {
  notes?: string;
  reviewed_label?: string | null;
  training_eligible?: boolean;
  training_ineligibility_reason?: string | null;
  trashed_at?: string | null;
};

export function BrowserSampleDetail({ id }: { id: string }) {
  const [sample, setSample] = useState<SampleDetail | null>();
  const [labels, setLabels] = useState<Array<{ name: string; display_name: string }>>([]);
  const [notes, setNotes] = useState("");
  const [label, setLabel] = useState("");
  const [trainingEligible, setTrainingEligible] = useState(false);
  const [exclusionReason, setExclusionReason] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    fetch(`/api/master/data/browser-collections/samples/${id}`, { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("Sample not found");
        const value = await response.json() as SampleDetail;
        const datasetResponse = await fetch(`/api/master/data/browser-collections/${value.dataset_id}`, { cache: "no-store" });
        const dataset = datasetResponse.ok ? await datasetResponse.json() as BrowserCollectionDataset : null;
        if (!active) return;
        setSample(value);
        setLabels(dataset?.labels?.filter((item) => !item.archived) ?? []);
        setNotes(value.notes || "");
        setLabel(value.reviewed_label || value.label_at_capture);
        setTrainingEligible(Boolean(value.training_eligible));
        setExclusionReason(value.training_ineligibility_reason || "");
      })
      .catch(() => active && setSample(null));
    return () => { active = false; };
  }, [id]);

  const media = useMemo(() => sample?.artifact_manifest.find((item) => item.role === "RAW"), [sample]);

  async function update(reviewStatus: "REVIEWED" | "APPROVED" | "REJECTED") {
    if (!sample) return;
    setBusy(true);
    setMessage("");
    const eligible = reviewStatus === "APPROVED" && trainingEligible;
    const response = await fetch(`/api/master/data/browser-collections/samples/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        reviewed_label: label,
        notes,
        review_status: reviewStatus,
        training_eligible: eligible,
        training_ineligibility_reason: eligible ? null : exclusionReason || (reviewStatus === "REJECTED" ? "REJECTED_DURING_REVIEW" : "REVIEWER_EXCLUDED"),
      }),
    });
    const body = await response.json().catch(() => ({}));
    if (response.ok) {
      setSample(body);
      setTrainingEligible(Boolean(body.training_eligible));
      setExclusionReason(body.training_ineligibility_reason || "");
      setMessage(`${reviewStatus.replaceAll("_", " ")} saved. Raw artifacts were not modified.`);
    } else setMessage(body.detail || "Review update failed.");
    setBusy(false);
  }

  async function trash(restore: boolean) {
    setBusy(true);
    const response = await fetch(`/api/master/data/browser-collections/samples/${id}/${restore ? "restore" : "trash"}`, { method: "POST" });
    const body = await response.json().catch(() => ({}));
    if (response.ok) {
      setSample(body);
      setTrainingEligible(Boolean(body.training_eligible));
      setMessage(restore ? "Sample restored." : "Sample moved to trash. Artifacts remain recoverable.");
    } else setMessage(body.detail || "Sample state could not be changed.");
    setBusy(false);
  }

  if (sample === undefined) return <p>Loading browser sample…</p>;
  if (!sample) return <section><h1>Sample not found</h1><Link href="/master/dataset/cv">Back to CV Dataset Vault</Link></section>;
  const mediaUrl = media ? `/api/master/data/browser-collections/samples/${id}/artifacts/${encodeURIComponent(media.name)}` : "";

  return <section>
    <nav className="breadcrumbs"><Link href="/master/dataset/cv">CV Dataset Vault</Link><span>›</span><strong>{sample.sample_id}</strong></nav>
    <span className="eyebrow">Browser MediaPipe · {sample.sample_type}</span>
    <h1>Sample {sample.sample_id.slice(-8)}</h1>
    {message && <p className="source-note" role="status">{message}</p>}
    <div className="detail-grid">
      <article className="master-card">
        {media ? sample.sample_type === "STILL"
          ? <img className="sample-media" src={mediaUrl} alt="Clean captured sample" />
          : <video className="detail-video" src={mediaUrl} controls preload="metadata" />
          : <div className="master-empty"><p>Landmarks-only sample. No media artifact was retained.</p></div>}
        <dl>
          <div><dt>Label at capture</dt><dd>{sample.label_at_capture}</dd></div>
          <div><dt>Subject</dt><dd>{sample.subject_id}</dd></div>
          <div><dt>Quality</dt><dd>{sample.technical_quality}</dd></div>
          <div><dt>Review</dt><dd>{sample.review_status}</dd></div>
          <div><dt>Training</dt><dd>{sample.training_eligible ? "Eligible" : "Excluded"}</dd></div>
          <div><dt>Capture</dt><dd>{sample.capture_state}</dd></div>
        </dl>
        <h2>Authorized artifacts</h2>
        <div className="downloads">{sample.artifact_manifest.map((artifact) => <a key={artifact.name} href={`/api/master/data/browser-collections/samples/${id}/artifacts/${encodeURIComponent(artifact.name)}`} download><Download /> {artifact.name}</a>)}</div>
      </article>
      <aside className="master-card edit-meta">
        <h2>Research review</h2>
        <label>Reviewed label
          <select value={label} onChange={(event) => setLabel(event.target.value)}>
            {labels.length ? labels.map((item) => <option value={item.name} key={item.name}>{item.display_name}</option>) : <option value={label}>{label}</option>}
          </select>
        </label>
        <label>Review notes<textarea value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
        <label className="check"><input type="checkbox" checked={trainingEligible} onChange={(event) => setTrainingEligible(event.target.checked)} />Eligible for training after approval</label>
        {!trainingEligible && <label>Exclusion reason<input value={exclusionReason} onChange={(event) => setExclusionReason(event.target.value)} placeholder="Reviewer exclusion reason" /></label>}
        <div className="review-actions">
          <button disabled={busy} onClick={() => void update("REVIEWED")}>Save review</button>
          <button className="primary" disabled={busy} onClick={() => void update("APPROVED")}><Check />Approve</button>
          <button className="danger" disabled={busy} onClick={() => void update("REJECTED")}><X />Reject</button>
        </div>
        {sample.trashed_at
          ? <button disabled={busy} onClick={() => void trash(true)}><RotateCcw />Restore sample</button>
          : <button className="danger" disabled={busy} onClick={() => void trash(false)}><Trash2 />Move to trash</button>}
        <p>Every review, relabel, approval, rejection, trash, and restore action is written to the audit log. Raw artifacts are immutable.</p>
      </aside>
    </div>
  </section>;
}
