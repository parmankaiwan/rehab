"use client";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Check,
  ChevronRight,
  CirclePause,
  ClipboardCheck,
  Database,
  Play,
  RefreshCw,
  RotateCcw,
  SkipForward,
  Users,
  Video,
} from "lucide-react";
import { LiveCameraView } from "@/components/LiveCameraView";
import { usePostureStream } from "@/hooks/usePostureStream";

type Study = { study_id: string; name: string; status: string };
type Subject = { subject_id: string; affected_side?: string };
type Plan = {
  label: string;
  count: number;
  duration_seconds: number;
  duration_mode?: "FIXED" | "MANUAL_STOP";
  rest_after_seconds?: number;
};
type Protocol = {
  protocol_id: string;
  protocol_version: number;
  display_name: string;
  rehab_type: string;
  modality: "CV" | "EMG" | "PAIRED";
  status: string;
  allowed_labels: string[];
  trial_plan: Plan[];
  countdown_seconds: number;
};
type Trial = {
  trial_id: string;
  trial_number: number;
  research_label: string;
  duration_seconds: number;
  duration_mode?: "FIXED" | "MANUAL_STOP";
  countdown_seconds: number;
  countdown_remaining: number;
  elapsed_seconds?: number;
  recording_start_timestamp_ns?: number;
  state: string;
  attempt_number: number;
  active_modality?: string;
  quality_result?: string;
  quality_warnings: string[];
  recording_ids: { CV?: string; EMG?: string };
};
type Collection = {
  collection_id: string;
  study_id?: string;
  subject_id: string;
  session_id: string;
  protocol_id: string;
  protocol_version: number;
  protocol_snapshot: Protocol;
  rehab_type: string;
  modality: string;
  status: string;
  current_trial_id: string;
  trials: Trial[];
  revision: number;
};
type CheckRow = {
  name: string;
  state: "PASS" | "WARNING" | "BLOCKED";
  message: string;
};
type Preflight = {
  overall: "PASS" | "WARNING" | "BLOCKED";
  checked_at: string;
  checks: CheckRow[];
};
type Coverage = {
  recordings: number;
  unique_subjects: number;
  rows: Array<{
    subject_id: string;
    rehab_type: string;
    modality: string;
    label: string;
    protocol: string;
    recordings: number;
    unique_subjects: number;
    approved_trials: number;
    planned_trials: number;
    missing_trials: number;
  }>;
};
type LabelOption = { id: string; display_name: string };
type ApiModule = {
  id: string;
  display_name: string;
  labels: string[];
  label_options: LabelOption[];
  emg_labels: string[];
  emg_label_options: LabelOption[];
};
type Module = {
  id: string;
  display_name: string;
  labels: LabelOption[];
  emg_labels: LabelOption[];
};
const base = "/api/master/data";
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${base}/${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(
      data.detail || data.error || `Request failed (${response.status})`,
    );
  return data as T;
}
const title = (value: string) => value.replaceAll("_", " ");
const clock = (seconds = 0) =>
  `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;

export function AcquisitionDashboard() {
  const stream = usePostureStream(),
    snapshot = stream.isStale ? null : stream.snapshot;
  const [studies, setStudies] = useState<Study[]>([]),
    [subjects, setSubjects] = useState<Subject[]>([]),
    [protocols, setProtocols] = useState<Protocol[]>([]),
    [collections, setCollections] = useState<Collection[]>([]),
    [modules, setModules] = useState<Module[]>([]),
    [coverage, setCoverage] = useState<Coverage>({
      recordings: 0,
      unique_subjects: 0,
      rows: [],
    }),
    [active, setActive] = useState<Collection | null>(null),
    [preflight, setPreflight] = useState<Preflight | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [tab, setTab] = useState<"plan" | "coverage">("plan");
  const [studyForm, setStudyForm] = useState({ study_id: "", name: "" }),
    [subjectForm, setSubjectForm] = useState({
      subject_id: "",
      affected_side: "RIGHT",
    }),
    [protocolForm, setProtocolForm] = useState({
      protocol_id: "",
      display_name: "",
      rehab_type: "REACHING",
      modality: "CV",
      label: "reach",
      count: 5,
      duration_seconds: 8,
      countdown_seconds: 3,
    }),
    [runForm, setRunForm] = useState({
      study_id: "",
      subject_id: "",
      session_id: "",
      protocol_id: "",
      affected_side: "RIGHT",
      consent_recorded: false,
    });
  const load = useCallback(async () => {
    try {
      const [s, u, p, c, v, settings] = await Promise.all([
        request<Study[]>("studies"),
        request<Subject[]>("subjects"),
        request<Protocol[]>("collection-protocols"),
        request<Collection[]>("collections"),
        request<Coverage>("collection-coverage"),
        request<{ modules: ApiModule[] }>("dataset/settings"),
      ]);
      setStudies(s);
      setSubjects(u);
      setProtocols(p);
      setCollections(c);
      setCoverage(v);
      setModules(
        settings.modules.map((module) => ({
          id: module.id,
          display_name: module.display_name,
          labels: module.label_options,
          emg_labels: module.emg_label_options,
        })),
      );
      setError("");
      if (active) {
        const refreshed = await request<Collection>(
          `collections/${active.collection_id}`,
        );
        setActive(refreshed);
      }
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Acquisition service unavailable",
      );
    }
  }, [active]);
  useEffect(() => {
    void load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (
      !active ||
      !active.trials.some((x) =>
        ["COUNTDOWN", "RECORDING", "FINALIZING"].includes(x.state),
      )
    )
      return;
    const timer = setInterval(async () => {
      try {
        setActive(
          await request<Collection>(`collections/${active.collection_id}`),
        );
      } catch {}
    }, 700);
    return () => clearInterval(timer);
  }, [active]);
  const current =
    active?.trials.find((x) => x.trial_id === active.current_trial_id) ||
    active?.trials.find(
      (x) =>
        !["APPROVED", "APPROVED_WITH_WARNINGS", "SKIPPED"].includes(x.state),
    );
  const completed =
    active?.trials.filter((x) =>
      ["APPROVED", "APPROVED_WITH_WARNINGS", "SKIPPED"].includes(x.state),
    ).length || 0;
  const selectedModule = modules.find((x) => x.id === protocolForm.rehab_type);
  const labels =
    protocolForm.modality === "EMG"
      ? selectedModule?.emg_labels
      : selectedModule?.labels;
  async function run(task: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await task();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }
  async function createStudy(e: FormEvent) {
    e.preventDefault();
    await run(async () => {
      await request("studies", {
        method: "POST",
        body: JSON.stringify(studyForm),
      });
      setStudyForm({ study_id: "", name: "" });
    });
  }
  async function createSubject(e: FormEvent) {
    e.preventDefault();
    await run(async () => {
      await request("subjects", {
        method: "POST",
        body: JSON.stringify(subjectForm),
      });
      setSubjectForm({ subject_id: "", affected_side: "RIGHT" });
    });
  }
  async function createProtocol(e: FormEvent) {
    e.preventDefault();
    await run(async () => {
      await request("collection-protocols", {
        method: "POST",
        body: JSON.stringify({
          ...protocolForm,
          allowed_labels: [protocolForm.label],
          trial_plan: [
            {
              label: protocolForm.label,
              count: Number(protocolForm.count),
              duration_seconds: Number(protocolForm.duration_seconds),
            },
          ],
          required_sensors:
            protocolForm.modality === "CV"
              ? ["CAMERA"]
              : protocolForm.modality === "EMG"
                ? ["EMG_BOARD"]
                : ["CAMERA", "EMG_BOARD"],
        }),
      });
      setProtocolForm({ ...protocolForm, protocol_id: "", display_name: "" });
    });
  }
  async function createCollection(e: FormEvent) {
    e.preventDefault();
    const selectedProtocol = protocols.find(
      (x) => `${x.protocol_id}:${x.protocol_version}` === runForm.protocol_id,
    );
    if (!selectedProtocol) return;
    await run(async () => {
      const value = await request<Collection>("collections", {
        method: "POST",
        body: JSON.stringify({
          ...runForm,
          protocol_id: selectedProtocol.protocol_id,
          protocol_version: selectedProtocol.protocol_version,
          study_id: runForm.study_id || null,
        }),
      });
      setActive(value);
      setPreflight(
        await request<Preflight>(
          `collections/${value.collection_id}/preflight`,
        ),
      );
    });
  }
  async function action(path: string, body: object = {}) {
    if (!active) return;
    await run(async () => {
      const value = await request<Collection>(
        `collections/${active.collection_id}/${path}`,
        { method: "POST", body: JSON.stringify(body) },
      );
      setActive(value);
      if (path === "start")
        setPreflight(
          await request<Preflight>(
            `collections/${active.collection_id}/preflight`,
          ),
        );
    });
  }
  function openCollection(value: Collection) {
    setActive(value);
    setPreflight(null);
    void request<Preflight>(`collections/${value.collection_id}/preflight`)
      .then(setPreflight)
      .catch((e) => setError(e.message));
  }
  if (active)
    return (
      <section className="acq-page acq-focused">
        <header className="acq-focus-head">
          <div>
            <span className="eyebrow">Focused collection mode</span>
            <h1>
              {active.subject_id} · {title(active.rehab_type)}
            </h1>
            <p>
              {active.collection_id} · {active.protocol_id}_V
              {active.protocol_version}
            </p>
          </div>
          <div className="acq-head-actions">
            {active.status === "ACTIVE" ? (
              <button disabled={busy} onClick={() => action("pause")}>
                <CirclePause />
                Pause batch
              </button>
            ) : (
              <button disabled={busy} onClick={() => action("resume")}>
                <Play />
                Resume batch
              </button>
            )}
            <button onClick={() => setActive(null)}>Exit</button>
          </div>
        </header>
        {error && (
          <div className="acq-alert blocked">
            <AlertTriangle />
            {error}
          </div>
        )}
        <div
          className="acq-progress"
          aria-label={`${completed} of ${active.trials.length} trials complete`}
        >
          <span
            style={{ width: `${(completed / active.trials.length) * 100}%` }}
          />
        </div>
        <div className="acq-active-grid">
          <main className="acq-stage">
            <div className="acq-trial-head">
              <div>
                <span>Current trial</span>
                <strong>
                  {current
                    ? `${current.trial_number} / ${active.trials.length}`
                    : "Plan complete"}
                </strong>
              </div>
              <div>
                <span>Research label</span>
                <strong>{current ? title(current.research_label) : "—"}</strong>
              </div>
              <div>
                <span>Attempt</span>
                <strong>{current?.attempt_number || "—"}</strong>
              </div>
              <i className={`acq-state state-${current?.state.toLowerCase()}`}>
                {current?.state || active.status}
              </i>
            </div>
            {current && (
              <>
                {(current.active_modality || active.modality) !== "EMG" && (
                  <div className="acq-camera-stage">
                    <LiveCameraView
                      snapshot={snapshot}
                      unavailable={!snapshot?.connected}
                      research
                    />
                    {current.state === "COUNTDOWN" && (
                      <div
                        className="acq-countdown-overlay"
                        role="status"
                        aria-live="assertive"
                      >
                        <span>GET READY</span>
                        <strong key={current.countdown_remaining}>
                          {current.countdown_remaining ||
                            current.countdown_seconds}
                        </strong>
                      </div>
                    )}
                    {current.state === "RECORDING" && (
                      <div className="acq-recording-indicator">
                        <i /> RECORDING {clock(current.elapsed_seconds)}
                      </div>
                    )}
                  </div>
                )}
                <div className="acq-sensor-stage">
                  {(current.active_modality || active.modality) === "EMG" ? (
                    <Activity />
                  ) : (
                    <Video />
                  )}
                  <h2>
                    {current.state === "REVIEW"
                      ? "Trial ready for review"
                      : current.state === "COUNTDOWN"
                        ? `Get ready · ${current.countdown_remaining || current.countdown_seconds}`
                        : current.state === "RECORDING"
                          ? `Recording · ${clock(current.elapsed_seconds)}`
                          : current.state === "RETRY_REQUIRED" &&
                              current.quality_warnings?.some((warning) =>
                                warning.includes("Tracking"),
                              )
                            ? "Tracking lost — move back into view"
                            : "Ready for technical preflight"}
                  </h2>
                  <p>
                    {current.duration_seconds} seconds ·{" "}
                    {current.active_modality || active.modality} · Countdown:{" "}
                    {current.countdown_seconds ||
                      active.protocol_snapshot.countdown_seconds ||
                      3}{" "}
                    sec · server-timed
                  </p>
                  {current.state === "RETRY_REQUIRED" &&
                    current.quality_warnings?.some((warning) =>
                      warning.includes("Tracking"),
                    ) && (
                      <div className="acq-tracking-lost">
                        TRACKING LOST · Countdown reset. Restore tracking, then
                        retry.
                      </div>
                    )}
                  {current.quality_result && (
                    <b>Technical quality: {title(current.quality_result)}</b>
                  )}
                </div>
                <div className="acq-controls">
                  {active.status === "PLANNED" && (
                    <button
                      className="primary"
                      disabled={busy}
                      onClick={() => action("start")}
                    >
                      <Play />
                      Begin collection
                    </button>
                  )}
                  {active.status === "ACTIVE" &&
                    ["PLANNED", "READY", "RETRY_REQUIRED"].includes(
                      current.state,
                    ) && (
                      <button
                        className="primary"
                        disabled={busy || preflight?.overall === "BLOCKED"}
                        onClick={() =>
                          action(`trials/${current.trial_id}/start`, {
                            modality:
                              active.modality === "PAIRED" ? "CV" : undefined,
                            override_warnings: true,
                          })
                        }
                      >
                        <Play />
                        {current.state === "RETRY_REQUIRED"
                          ? "Retry countdown"
                          : "Start trial"}
                      </button>
                    )}
                  {current.state === "COUNTDOWN" &&
                    current.active_modality === "CV" && (
                      <button
                        disabled={busy}
                        onClick={() =>
                          action(`trials/${current.trial_id}/cancel-countdown`)
                        }
                      >
                        Cancel countdown
                      </button>
                    )}
                  {current.state === "RECORDING" &&
                    current.duration_mode === "MANUAL_STOP" && (
                      <button
                        disabled={busy}
                        onClick={() =>
                          action(`trials/${current.trial_id}/stop`)
                        }
                      >
                        Stop trial
                      </button>
                    )}
                  {current.state === "REVIEW" && (
                    <>
                      <button
                        className="primary"
                        disabled={busy}
                        onClick={() =>
                          action(`trials/${current.trial_id}/approve`)
                        }
                      >
                        <Check />
                        Approve
                      </button>
                      <button
                        disabled={busy}
                        onClick={() =>
                          action(
                            `trials/${current.trial_id}/approve-with-warning`,
                          )
                        }
                      >
                        <ClipboardCheck />
                        Approve with warning
                      </button>
                      <button
                        disabled={busy}
                        onClick={() =>
                          action(`trials/${current.trial_id}/retry`, {
                            retain_failed_attempt: true,
                            reason: "Technical retry",
                          })
                        }
                      >
                        <RotateCcw />
                        Retry
                      </button>
                      <button
                        disabled={busy}
                        onClick={() =>
                          action(`trials/${current.trial_id}/discard`)
                        }
                      >
                        Discard
                      </button>
                    </>
                  )}{" "}
                  {["PLANNED", "READY", "RETRY_REQUIRED", "DISCARDED"].includes(
                    current.state,
                  ) && (
                    <button
                      disabled={busy}
                      onClick={() => {
                        const reason = window.prompt(
                          "A reason is required to skip this trial",
                        );
                        if (reason)
                          void action(`trials/${current.trial_id}/skip`, {
                            reason,
                          });
                      }}
                    >
                      <SkipForward />
                      Skip with reason
                    </button>
                  )}
                </div>
                <div className="acq-marker-row">
                  <span>Manual event</span>
                  {[
                    "MOVEMENT_STARTED",
                    "TARGET_REACHED",
                    "MOVEMENT_ENDED",
                    "TRACKING_ISSUE",
                    "SENSOR_ISSUE",
                  ].map((marker) => (
                    <button
                      key={marker}
                      disabled={busy || current.state !== "RECORDING"}
                      onClick={() =>
                        action(`trials/${current.trial_id}/markers`, {
                          event_type: marker,
                          relative_timestamp_ms: 0,
                          recording_id:
                            current.recording_ids.CV ||
                            current.recording_ids.EMG,
                        })
                      }
                    >
                      {title(marker)}
                    </button>
                  ))}
                </div>
              </>
            )}
          </main>
          <aside className="acq-rail">
            <section>
              <div className="acq-section-title">
                <h2>Preflight</h2>
                <button
                  aria-label="Refresh preflight"
                  onClick={() =>
                    request<Preflight>(
                      `collections/${active.collection_id}/preflight`,
                    ).then(setPreflight)
                  }
                >
                  <RefreshCw />
                </button>
              </div>
              <b className={`acq-pill ${preflight?.overall.toLowerCase()}`}>
                {preflight?.overall || "CHECKING"}
              </b>
              {preflight?.checks.map((check) => (
                <div className="acq-check" key={check.name}>
                  <i className={check.state.toLowerCase()}>
                    {check.state === "PASS" ? <Check /> : <AlertTriangle />}
                  </i>
                  <span>
                    <strong>{check.name}</strong>
                    <small>{check.message}</small>
                  </span>
                </div>
              ))}
            </section>
            <section>
              <h2>Trial queue</h2>
              <div className="acq-queue">
                {active.trials.map((trial) => (
                  <button
                    className={
                      trial.trial_id === current?.trial_id ? "current" : ""
                    }
                    key={trial.trial_id}
                  >
                    <i>{trial.trial_number}</i>
                    <span>
                      {title(trial.research_label)}
                      <small>
                        Attempt {trial.attempt_number} ·{" "}
                        {trial.countdown_seconds ||
                          active.protocol_snapshot.countdown_seconds ||
                          3}
                        s countdown
                      </small>
                    </span>
                    <b>{trial.state}</b>
                  </button>
                ))}
              </div>
            </section>
          </aside>
        </div>
        <p className="acq-shortcuts">
          Keyboard safety: shortcuts are disabled while typing. Server state
          remains authoritative after refresh.
        </p>
      </section>
    );

  return (
    <section className="acq-page">
      <header className="acq-title">
        <div>
          <span className="eyebrow">Research acquisition manager</span>
          <h1>Data collection</h1>
          <p>
            Protocol-driven CV and EMG trials with technical quality control and
            traceable review.
          </p>
        </div>
        <button onClick={load}>
          <RefreshCw />
          Refresh
        </button>
      </header>
      {error && (
        <div className="acq-alert blocked">
          <AlertTriangle />
          {error}
        </div>
      )}
      <nav className="acq-tabs">
        <button
          className={tab === "plan" ? "active" : ""}
          onClick={() => setTab("plan")}
        >
          Plan & collect
        </button>
        <button
          className={tab === "coverage" ? "active" : ""}
          onClick={() => setTab("coverage")}
        >
          Coverage
        </button>
      </nav>
      {tab === "coverage" ? (
        <CoveragePanel coverage={coverage} />
      ) : (
        <>
          <div className="acq-kpis">
            <article>
              <Users />
              <span>
                Subjects<strong>{subjects.length}</strong>
              </span>
            </article>
            <article>
              <ClipboardCheck />
              <span>
                Protocols<strong>{protocols.length}</strong>
              </span>
            </article>
            <article>
              <Database />
              <span>
                Collections<strong>{collections.length}</strong>
              </span>
            </article>
            <article>
              <Check />
              <span>
                Approved recordings<strong>{coverage.recordings}</strong>
              </span>
            </article>
          </div>
          <div className="acq-builder">
            <section>
              <span className="step">1</span>
              <h2>Study</h2>
              <p>Optional research program container.</p>
              <form onSubmit={createStudy}>
                <label>
                  Study ID
                  <input
                    required
                    pattern="[A-Za-z0-9_-]+"
                    placeholder="STROKE_PILOT"
                    value={studyForm.study_id}
                    onChange={(e) =>
                      setStudyForm({
                        ...studyForm,
                        study_id: e.target.value.toUpperCase(),
                      })
                    }
                  />
                </label>
                <label>
                  Study name
                  <input
                    required
                    placeholder="Stroke Reaching Pilot"
                    value={studyForm.name}
                    onChange={(e) =>
                      setStudyForm({ ...studyForm, name: e.target.value })
                    }
                  />
                </label>
                <button disabled={busy}>Create study</button>
              </form>
            </section>
            <section>
              <span className="step">2</span>
              <h2>Subject</h2>
              <p>Pseudonymous IDs only—no patient PII.</p>
              <form onSubmit={createSubject}>
                <label>
                  Subject ID
                  <input
                    required
                    pattern="[A-Za-z0-9_-]+"
                    placeholder="P001"
                    value={subjectForm.subject_id}
                    onChange={(e) =>
                      setSubjectForm({
                        ...subjectForm,
                        subject_id: e.target.value.toUpperCase(),
                      })
                    }
                  />
                </label>
                <label>
                  Affected side
                  <select
                    value={subjectForm.affected_side}
                    onChange={(e) =>
                      setSubjectForm({
                        ...subjectForm,
                        affected_side: e.target.value,
                      })
                    }
                  >
                    <option>RIGHT</option>
                    <option>LEFT</option>
                    <option>UNKNOWN</option>
                    <option>N/A</option>
                  </select>
                </label>
                <button disabled={busy}>Add subject</button>
              </form>
            </section>
            <section>
              <span className="step">3</span>
              <h2>Protocol</h2>
              <p>
                Creating the same ID again produces a new immutable version.
              </p>
              <form onSubmit={createProtocol}>
                <label>
                  Protocol ID
                  <input
                    required
                    placeholder="REACHING_CV"
                    value={protocolForm.protocol_id}
                    onChange={(e) =>
                      setProtocolForm({
                        ...protocolForm,
                        protocol_id: e.target.value.toUpperCase(),
                      })
                    }
                  />
                </label>
                <label>
                  Display name
                  <input
                    required
                    placeholder="Reaching CV"
                    value={protocolForm.display_name}
                    onChange={(e) =>
                      setProtocolForm({
                        ...protocolForm,
                        display_name: e.target.value,
                      })
                    }
                  />
                </label>
                <label>
                  Rehabilitation
                  <select
                    value={protocolForm.rehab_type}
                    onChange={(e) =>
                      setProtocolForm({
                        ...protocolForm,
                        rehab_type: e.target.value,
                        label:
                          modules.find((x) => x.id === e.target.value)
                            ?.labels[0]?.id || "",
                      })
                    }
                  >
                    {modules.map((module) => (
                      <option key={module.id} value={module.id}>
                        {module.display_name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Modality
                  <select
                    value={protocolForm.modality}
                    onChange={(e) =>
                      setProtocolForm({
                        ...protocolForm,
                        modality: e.target.value,
                        label:
                          (e.target.value === "EMG"
                            ? selectedModule?.emg_labels
                            : selectedModule?.labels)?.[0]?.id || "",
                      })
                    }
                  >
                    <option>CV</option>
                    <option>EMG</option>
                    <option>PAIRED</option>
                  </select>
                </label>
                <label>
                  Research label
                  <select
                    value={protocolForm.label}
                    onChange={(e) =>
                      setProtocolForm({
                        ...protocolForm,
                        label: e.target.value,
                      })
                    }
                  >
                    {labels?.map((label) => (
                      <option key={label.id} value={label.id}>
                        {label.display_name}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="acq-inline">
                  <label>
                    Trials
                    <input
                      type="number"
                      min="1"
                      max="100"
                      value={protocolForm.count}
                      onChange={(e) =>
                        setProtocolForm({
                          ...protocolForm,
                          count: Number(e.target.value),
                        })
                      }
                    />
                  </label>
                  <label>
                    Seconds
                    <input
                      type="number"
                      min="1"
                      max="300"
                      value={protocolForm.duration_seconds}
                      onChange={(e) =>
                        setProtocolForm({
                          ...protocolForm,
                          duration_seconds: Number(e.target.value),
                        })
                      }
                    />
                  </label>
                </div>
                <label className="acq-countdown-setting">
                  Start countdown
                  <select
                    aria-label="Start countdown"
                    value={protocolForm.countdown_seconds}
                    onChange={(e) =>
                      setProtocolForm({
                        ...protocolForm,
                        countdown_seconds: Number(e.target.value),
                      })
                    }
                  >
                    <option value={3}>3 seconds</option>
                    <option value={5}>5 seconds</option>
                  </select>
                </label>
                <button disabled={busy}>Create protocol version</button>
              </form>
            </section>
          </div>
          <RunBuilder
            studies={studies}
            subjects={subjects}
            protocols={protocols}
            form={runForm}
            setForm={setRunForm}
            create={createCollection}
            busy={busy}
          />
          <CollectionList rows={collections} open={openCollection} />
        </>
      )}
    </section>
  );
}

function RunBuilder({
  studies,
  subjects,
  protocols,
  form,
  setForm,
  create,
  busy,
}: {
  studies: Study[];
  subjects: Subject[];
  protocols: Protocol[];
  form: {
    study_id: string;
    subject_id: string;
    session_id: string;
    protocol_id: string;
    affected_side: string;
    consent_recorded: boolean;
  };
  setForm: (value: typeof form) => void;
  create: (event: FormEvent) => void;
  busy: boolean;
}) {
  const protocol = protocols.find(
    (x) => `${x.protocol_id}:${x.protocol_version}` === form.protocol_id,
  );
  const trialCount =
    protocol?.trial_plan.reduce((sum, x) => sum + x.count, 0) || 0;
  return (
    <section className="acq-run-builder">
      <div>
        <span className="eyebrow">Steps 4–7 · Review plan</span>
        <h2>Start a collection run</h2>
        <p>
          Select the subject, session, rehabilitation protocol, then verify the
          immutable plan before collection.
        </p>
      </div>
      <form onSubmit={create}>
        <label>
          Study (optional)
          <select
            value={form.study_id}
            onChange={(e) => setForm({ ...form, study_id: e.target.value })}
          >
            <option value="">Legacy / no study</option>
            {studies
              .filter((x) => x.status === "ACTIVE")
              .map((x) => (
                <option key={x.study_id} value={x.study_id}>
                  {x.name} · {x.study_id}
                </option>
              ))}
          </select>
        </label>
        <label>
          Subject
          <select
            required
            value={form.subject_id}
            onChange={(e) => {
              const subject = subjects.find(
                (x) => x.subject_id === e.target.value,
              );
              setForm({
                ...form,
                subject_id: e.target.value,
                affected_side: subject?.affected_side || form.affected_side,
              });
            }}
          >
            <option value="">Select subject</option>
            {subjects.map((x) => (
              <option key={x.subject_id}>{x.subject_id}</option>
            ))}
          </select>
        </label>
        <label>
          Session ID
          <input
            required
            pattern="[A-Za-z0-9_-]+"
            placeholder="SESSION-001"
            value={form.session_id}
            onChange={(e) =>
              setForm({ ...form, session_id: e.target.value.toUpperCase() })
            }
          />
        </label>
        <label>
          Protocol
          <select
            required
            value={form.protocol_id}
            onChange={(e) => setForm({ ...form, protocol_id: e.target.value })}
          >
            <option value="">Select protocol</option>
            {protocols
              .filter((x) => x.status !== "ARCHIVED")
              .map((x) => (
                <option
                  key={`${x.protocol_id}:${x.protocol_version}`}
                  value={`${x.protocol_id}:${x.protocol_version}`}
                >
                  {x.display_name} · V{x.protocol_version} · {x.modality}
                </option>
              ))}
          </select>
        </label>
        <label>
          Affected side
          <select
            value={form.affected_side}
            onChange={(e) =>
              setForm({ ...form, affected_side: e.target.value })
            }
          >
            <option>RIGHT</option>
            <option>LEFT</option>
            <option>UNKNOWN</option>
            <option>N/A</option>
          </select>
        </label>
        <label className="acq-consent">
          <input
            type="checkbox"
            checked={form.consent_recorded}
            onChange={(e) =>
              setForm({ ...form, consent_recorded: e.target.checked })
            }
          />{" "}
          Documented research recording consent is confirmed
        </label>
        <div className="acq-plan-preview">
          <strong>
            {protocol
              ? `${protocol.display_name} · V${protocol.protocol_version}`
              : "Select a protocol"}
          </strong>
          <span>{trialCount} planned trials</span>
          {protocol?.trial_plan.map((item, index) => (
            <p
              key={`${item.label}:${item.duration_seconds}:${item.count}:${index}`}
            >
              {title(item.label)} × {item.count}
              <small>{item.duration_seconds}s each</small>
            </p>
          ))}
          {protocol && (
            <>
              <div className="acq-countdown-summary">
                <ChevronRight /> Countdown: {protocol.countdown_seconds || 3}{" "}
                seconds before every trial
              </div>
              <b>
                <ChevronRight />
                {protocol.modality} required · synchronization NOT CONFIGURED
              </b>
            </>
          )}
        </div>
        <button
          className="primary"
          disabled={busy || !form.consent_recorded || !protocol}
        >
          Create & review collection
        </button>
      </form>
    </section>
  );
}

function CollectionList({
  rows,
  open,
}: {
  rows: Collection[];
  open: (row: Collection) => void;
}) {
  return (
    <section className="acq-list">
      <div className="acq-section-title">
        <div>
          <span className="eyebrow">Recoverable server state</span>
          <h2>Collection runs</h2>
        </div>
      </div>
      {rows.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Collection</th>
                <th>Subject</th>
                <th>Session</th>
                <th>Protocol</th>
                <th>Progress</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const done = row.trials.filter((x) =>
                  ["APPROVED", "APPROVED_WITH_WARNINGS", "SKIPPED"].includes(
                    x.state,
                  ),
                ).length;
                return (
                  <tr key={row.collection_id}>
                    <td>{row.collection_id}</td>
                    <td>{row.subject_id}</td>
                    <td>{row.session_id}</td>
                    <td>
                      {row.protocol_id}_V{row.protocol_version}
                    </td>
                    <td>
                      {done} / {row.trials.length}
                    </td>
                    <td>
                      <span className="status-token">{row.status}</span>
                    </td>
                    <td>
                      <button onClick={() => open(row)}>
                        {row.status === "COMPLETE" ? "Review" : "Open"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="acq-empty">
          No collection runs yet. Complete the setup above to create the first
          protocol-driven run.
        </div>
      )}
    </section>
  );
}

function CoveragePanel({ coverage }: { coverage: Coverage }) {
  const labels = useMemo(
    () => Array.from(new Set(coverage.rows.map((x) => x.label))),
    [coverage.rows],
  );
  return (
    <section className="acq-coverage">
      <div className="acq-kpis">
        <article>
          <Database />
          <span>
            Approved recordings<strong>{coverage.recordings}</strong>
          </span>
        </article>
        <article>
          <Users />
          <span>
            Unique subjects<strong>{coverage.unique_subjects}</strong>
          </span>
        </article>
        <article>
          <Activity />
          <span>
            Research labels<strong>{labels.length}</strong>
          </span>
        </article>
        <article>
          <AlertTriangle />
          <span>
            Missing trials
            <strong>
              {coverage.rows.reduce((sum, x) => sum + x.missing_trials, 0)}
            </strong>
          </span>
        </article>
      </div>
      <div className="acq-list">
        <span className="eyebrow">Subject-aware dataset readiness</span>
        <h2>Coverage matrix</h2>
        <p>
          Recording count and unique-subject count are shown separately. Mock
          recordings are excluded by default.
        </p>
        {coverage.rows.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Subject</th>
                  <th>Rehabilitation</th>
                  <th>Modality</th>
                  <th>Label</th>
                  <th>Protocol</th>
                  <th>Approved</th>
                  <th>Planned</th>
                  <th>Missing</th>
                </tr>
              </thead>
              <tbody>
                {coverage.rows.map((row) => (
                  <tr
                    key={`${row.subject_id}:${row.rehab_type}:${row.modality}:${row.label}:${row.protocol}`}
                  >
                    <td>{row.subject_id}</td>
                    <td>{title(row.rehab_type)}</td>
                    <td>{row.modality}</td>
                    <td>{title(row.label)}</td>
                    <td>{row.protocol}</td>
                    <td>{row.approved_trials}</td>
                    <td>{row.planned_trials}</td>
                    <td>{row.missing_trials}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="acq-empty">
            Coverage appears after protocol collections are created.
          </div>
        )}
      </div>
    </section>
  );
}
