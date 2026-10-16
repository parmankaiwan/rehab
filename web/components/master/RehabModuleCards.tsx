"use client";

import Link from "next/link";
import { Activity, ArrowRight, Database, Folder, Move3d, PersonStanding, Play, Radio, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { RehabModule } from "@/types/dataset";
import { apiErrorMessage, masterApiGet } from "@/lib/masterApi";

const icons = [PersonStanding, Move3d, Activity, Folder];

export function RehabModuleCards({ destination }: { destination: "collection" | "dataset" }) {
  const [modules, setModules] = useState<RehabModule[]>([]);
  const [emg, setEmg] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const rows = await masterApiGet<RehabModule[]>("/api/master/data/rehab-modules", { validate: (value): value is RehabModule[] => Array.isArray(value) });
      setModules(rows);

      if (destination === "dataset") {
        const emgRows = await masterApiGet<{ id: string; emg_stats?: { total_recordings: number } }[]>("/api/master/data/emg/rehab-modules", { validate: (value): value is { id: string; emg_stats?: { total_recordings: number } }[] => Array.isArray(value), retries: 1 });
        setEmg(Object.fromEntries(emgRows.map((row) => [row.id, row.emg_stats?.total_recordings || 0])));
      }
    } catch (cause) {
      setError(apiErrorMessage(cause));
    } finally {
      setLoading(false);
    }
  }, [destination]);

  useEffect(() => { void load(); }, [load]);

  if (loading) return <div className="module-loading" role="status"><i/><i/><span>Loading posture datasets…</span></div>;
  if (error && !modules.length) return <div className="module-load-error" role="alert"><div><strong>Could not load posture datasets</strong><span>{error}</span></div><button onClick={load}><RefreshCw/>Retry</button></div>;
  if (!modules.length) return <div className="master-empty">No posture datasets are configured.</div>;

  return <>{error && <div className="module-load-error" role="status"><div><strong>Showing previously loaded datasets</strong><span>{error}</span></div><button onClick={load}><RefreshCw/>Retry</button></div>}<div className="module-grid">
    {modules.map((module, index) => {
      const Icon = icons[index % icons.length];
      const unassigned = module.id === "UNASSIGNED";
      if (destination === "collection" && unassigned) return null;
      return <article className={`module-card module-card-with-actions ${!module.enabled && !unassigned ? "archived" : ""}`} key={module.id}>
        <Icon/>
        <div className="module-card-content">
          <span className="eyebrow">{unassigned ? "Legacy review" : module.enabled ? "Rehab dataset" : "Archived"}</span>
          <h2>{module.name}</h2>
          <p>{module.description}</p>
          <dl>
            <div><dt>{destination === "dataset" ? "Computer Vision" : "Recordings"}</dt><dd>{module.stats.total_samples}</dd></div>
            <div><dt>{destination === "dataset" ? "EMG" : "Training eligible"}</dt><dd>{destination === "dataset" ? emg[module.id] || 0 : module.stats.training_eligible}</dd></div>
          </dl>
          <ModuleActions module={module} destination={destination} unassigned={unassigned}/>
        </div>
      </article>;
    })}
  </div></>;
}

function ModuleActions({ module, destination, unassigned }: { module: RehabModule; destination: "collection" | "dataset"; unassigned: boolean }) {
  const collectionHref = `/master/cv-data/${module.slug}`;
  const datasetHref = `/master/dataset/${module.slug}`;
  return <div className="module-action-box" aria-label={`${module.name} actions`}>
    <span>Actions</span>
    <div>
      {destination === "collection" && module.enabled && <Link className="module-action-primary" href={collectionHref}>
        <Play/>{module.stats.total_samples ? "Continue collection" : "Collect first sample"}<ArrowRight/>
      </Link>}
      {destination === "dataset" && <Link className="module-action-primary" href={datasetHref}>
        <Database/>{unassigned ? "Review unassigned" : "Open dataset"}<ArrowRight/>
      </Link>}
      {!unassigned && <Link href={destination === "collection" ? datasetHref : collectionHref}>
        {destination === "collection" ? <Database/> : <Play/>}{destination === "collection" ? "Review recordings" : "Collect posture data"}
      </Link>}
      {!unassigned && module.enabled && <Link href="/master/live/cv"><Radio/>Open live posture</Link>}
      {!module.enabled && destination === "collection" && <small>Collection disabled for this archived module.</small>}
    </div>
  </div>;
}
