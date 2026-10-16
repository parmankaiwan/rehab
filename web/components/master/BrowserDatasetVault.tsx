"use client";

import Link from "next/link";
import { Camera, Database, Video } from "lucide-react";
import { useEffect, useState } from "react";
import type { BrowserCollectionDataset } from "@/types/browserCollection";

export function BrowserDatasetVault() {
  const [datasets, setDatasets] = useState<BrowserCollectionDataset[]>([]);
  const [message, setMessage] = useState("Loading browser collections…");
  useEffect(() => { fetch("/api/master/data/browser-collections?status=", { cache: "no-store" }).then(async (response) => { if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "Browser collections unavailable"); setDatasets(await response.json()); setMessage(""); }).catch((error) => setMessage(error.message)); }, []);
  return <section className="browser-vault"><div className="browser-vault-title"><div><span className="eyebrow">Durable private Supabase storage</span><h2>Browser MediaPipe datasets</h2></div><Link className="primary" href="/master/cv-data">Open CV Collection</Link></div>{message && <p className="source-note">{message}</p>}<div className="collection-dataset-grid">{datasets.map((dataset) => <article className="collection-dataset-card" key={dataset.dataset_id}><div className="collection-dataset-head"><Database/><span>{dataset.archived ? "ARCHIVED" : "ACTIVE"}</span></div><h3>{dataset.name}</h3><p>{dataset.description || "No description"}</p><dl><div><dt>Stills</dt><dd>{dataset.still_count}</dd></div><div><dt>Videos</dt><dd>{dataset.video_count}</dd></div><div><dt>Labels</dt><dd>{dataset.label_count}</dd></div><div><dt>Approved</dt><dd>{dataset.approved_count}</dd></div></dl><Link href={`/master/cv-data/studio?dataset=${dataset.dataset_id}`}>{dataset.video_count ? <Video/> : <Camera/>} Open dataset & samples</Link></article>)}</div></section>;
}
