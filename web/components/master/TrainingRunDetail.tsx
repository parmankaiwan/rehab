"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { CheckCircle, Download, FlaskConical, RefreshCw, ShieldAlert } from "lucide-react";
import type { TrainingRun } from "@/types/ml";

const api = "/api/master/data/ml";
const pct = (value: unknown) => typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "—";

interface TrainingMetrics {
  f1_macro: number;
  balanced_accuracy: number;
  accuracy: number;
  evaluation_samples: number;
  confusion_matrix: { labels: string[]; values: number[][] };
  evaluation_scope: string;
  training_samples: number;
  validation?: TrainingMetricSet | null;
  test?: TrainingMetricSet | null;
  development_training?: TrainingMetricSet | null;
}

type TrainingMetricSet = Pick<TrainingMetrics, "f1_macro" | "balanced_accuracy" | "accuracy" | "evaluation_samples" | "confusion_matrix">;

export function TrainingRunDetail({ id }: { id: string }) {
  const [run, setRun] = useState<TrainingRun | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    const response = await fetch(`${api}/runs/${id}`, { cache: "no-store" });
    if (response.ok) setRun(await response.json());
    else setError("Could not load Training Run");
  }, [id]);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 1000);
    return () => clearInterval(timer);
  }, [load]);

  async function register() {
    const response = await fetch(`${api}/models/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        training_run_id: id,
        status: "EXPERIMENTAL",
        notes: "Registered from reviewed FlexMap Training Run",
      }),
    });
    if (response.ok) location.href = "/master/ml/models";
    else setError("Model registration failed");
  }

  if (error) return <div className="master-error-state"><h2>{error}</h2><button onClick={load}><RefreshCw />Retry</button></div>;
  if (!run) return <div className="loading-skeleton"><i /><i /><i /></div>;

  const active = ["QUEUED", "RUNNING"].includes(run.status);
  const metrics = run.metrics as TrainingMetrics | undefined;
  const matrix = metrics?.confusion_matrix;
  const maxImportance = Math.max(...(run.feature_importance ?? []).map((item) => item.importance), 1);

  return <section className="ml-run">
    <nav className="breadcrumbs"><Link href="/master/model-training">Training</Link><span>›</span><Link href="/master/ml/runs">Runs</Link><span>›</span><strong>{id}</strong></nav>
    <div className="ml-page-head">
      <div><span className="eyebrow">Training Run</span><h1>{id}</h1><p className="master-lead">{run.model_type.replaceAll("_", " ")} · {run.evaluation_scope}</p></div>
      <span className={`ml-run-status ${run.status.toLowerCase()}`}>{active && <RefreshCw />}{run.status}</span>
    </div>
    <article className="master-card ml-progress-card">
      <div><strong>{run.stage.replaceAll("_", " ")}</strong><span>{Math.round(run.progress * 100)}%</span></div>
      <progress max="1" value={run.progress} />
      <ol>{["VALIDATING DATASET", "EXTRACTING FEATURES", "FITTING PREPROCESSOR", "TRAINING MODEL", "EVALUATING", "SAVING ARTIFACTS"].map((stage) => <li key={stage}>{stage}</li>)}</ol>
      {run.error && <p className="master-alert"><ShieldAlert />{run.error}</p>}
    </article>
    {run.status === "COMPLETED" && metrics && <>
      {metrics.evaluation_scope === "DEVELOPMENT_ONLY" && <p className="master-alert"><ShieldAlert />Development-only results were calculated on training data. They are not held-out test performance.</p>}
      <div className="ml-metrics">
        <div><strong>{pct(metrics.f1_macro)}</strong><span>Macro F1</span></div>
        <div><strong>{pct(metrics.balanced_accuracy)}</strong><span>Balanced accuracy</span></div>
        <div><strong>{pct(metrics.accuracy)}</strong><span>Accuracy</span></div>
        <div><strong>{metrics.evaluation_samples}</strong><span>Evaluation samples</span></div>
      </div>
      <div className="ml-results-grid">
        <MetricPanel title="Validation set" metrics={metrics.validation} />
        <MetricPanel title="Held-out test set" metrics={metrics.test} />
      </div>
      <div className="ml-results-grid">
        <article className="master-card"><h2>Confusion matrix</h2>{matrix && <table className="ml-matrix"><thead><tr><th>True ↓ / Predicted →</th>{matrix.labels.map((label) => <th key={label}>{label}</th>)}</tr></thead><tbody>{matrix.values.map((row, index) => <tr key={matrix.labels[index]}><th>{matrix.labels[index]}</th>{row.map((value, column) => <td key={column}>{value}</td>)}</tr>)}</tbody></table>}</article>
        <article className="master-card"><h2>Feature importance</h2><div className="ml-importance">{run.feature_importance?.slice(0, 10).map((item) => <div key={item.feature}><span>{item.feature}</span><i style={{ width: `${item.importance / maxImportance * 100}%` }} /><strong>{item.importance.toFixed(3)}</strong></div>)}</div></article>
      </div>
      <article className="master-card"><h2>Error review</h2><p>Predictions are stored separately. Research labels remain unchanged.</p><div className="table-wrap"><table><thead><tr><th>Recording</th><th>True label</th><th>Prediction</th><th>Confidence</th></tr></thead><tbody>{run.predictions.filter((prediction) => !prediction.correct).map((prediction) => <tr key={prediction.recording_id}><td><Link href={prediction.recording_id.startsWith("EMG-") ? `/master/emg/recordings/${prediction.recording_id}` : `/master/dataset/${prediction.recording_id}`}>{prediction.recording_id}</Link></td><td>{prediction.true_research_label}</td><td>{prediction.predicted_label}</td><td>{prediction.confidence != null ? pct(prediction.confidence) : "—"}</td></tr>)}</tbody></table>{!run.predictions.some((prediction) => !prediction.correct) && <p className="empty-row">No misclassified evaluation recordings.</p>}</div></article>
      <div className="ml-run-actions"><a href={`${api}/runs/${id}/artifacts/metrics.json`}><Download />Metrics</a><a href={`${api}/runs/${id}/artifacts/predictions.csv`}><Download />Predictions</a><Link href={`/master/ml/train?dataset=${run.dataset_version_id}`}><FlaskConical />Train another model</Link><button className="primary" onClick={register}><CheckCircle />Register as Experimental</button></div>
    </>}
  </section>;
}

function MetricPanel({ title, metrics }: { title: string; metrics?: TrainingMetricSet | null }) {
  return <article className="master-card"><h2>{title}</h2>{metrics ? <dl><div><dt>Samples</dt><dd>{metrics.evaluation_samples}</dd></div><div><dt>Macro F1</dt><dd>{pct(metrics.f1_macro)}</dd></div><div><dt>Balanced accuracy</dt><dd>{pct(metrics.balanced_accuracy)}</dd></div><div><dt>Accuracy</dt><dd>{pct(metrics.accuracy)}</dd></div></dl> : <p>Not available for this split.</p>}</article>;
}
