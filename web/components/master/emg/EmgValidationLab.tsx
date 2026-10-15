"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  Download,
  Play,
  RefreshCw,
  Square,
  Usb,
  X,
} from "lucide-react";
import { useEmgStream } from "@/hooks/useEmgStream";
import type { EmgStatus, HardwareProfile } from "@/types/emg";
import { EmgChart } from "./EmgChart";

const api = "/api/master/data/emg";
type TestState = "NOT_RUN" | "RUNNING" | "PASS" | "WARNING" | "FAIL";
type ValidationTest = {
  state: TestState;
  started_at?: string;
  completed_at?: string;
  progress?: number;
  metrics: Record<string, unknown>;
  warnings: string[];
  failures: string[];
};
type ValidationRun = {
  validation_run_id: string;
  hardware_profile_id: string;
  hardware_profile_version: number;
  device_identity?: Record<string, unknown>;
  status: string;
  selected_port: string;
  baud_rate?: number;
  serial_protocol?: string;
  configured_sample_rate_hz?: number;
  started_at: string;
  completed_at?: string;
  tests: Record<string, ValidationTest>;
  warnings: string[];
  failures: string[];
};
type Device = {
  port: string;
  is_usb?: boolean;
  description?: string;
  manufacturer?: string;
  usb_vid?: string;
  usb_pid?: string;
  serial_number?: string;
  hwid?: string;
};
type Baseline = {
  baseline_id: string;
  hardware_profile_id?: string;
  sample_count?: number;
};
type Diagnostics = {
  bytes_received?: number;
  valid_packets?: number;
  invalid_packets?: number;
  first_valid_packet_latency_ms?: number;
  latest_data_age_ms?: number;
  [key: string]: unknown;
};

const steps = [
  { label: "USB Detection", ids: ["usb_detection"] },
  { label: "Serial Connection", ids: ["serial_connection"] },
  { label: "Stream Check", ids: ["stream"] },
  { label: "Channel Check", ids: ["channels"] },
  { label: "Baseline", ids: ["baseline"] },
  { label: "Fixed Trial", ids: ["fixed_trial"] },
  { label: "Manual Trial", ids: ["manual_trial", "event_markers", "review"] },
  { label: "Interruption", ids: ["interruption"] },
  { label: "Reconnect", ids: ["reconnect", "retry"] },
  { label: "Long Run", ids: ["long_run"] },
  {
    label: "Dataset Check",
    ids: ["dataset", "raw_integrity", "processing", "training_eligibility"],
  },
  { label: "Final Report", ids: [] },
];
const prerequisites: Record<string, string[]> = {
  serial_connection: ["usb_detection"],
  stream: ["serial_connection"],
  channels: ["stream"],
  baseline: ["channels"],
  fixed_trial: ["baseline"],
  manual_trial: ["fixed_trial"],
  review: ["manual_trial", "event_markers"],
  interruption: ["review"],
  reconnect: ["interruption"],
  retry: ["reconnect"],
  long_run: ["retry"],
  dataset: ["long_run", "review"],
  raw_integrity: ["dataset"],
  processing: ["raw_integrity"],
  training_eligibility: ["processing"],
};
const details = [
  [
    "usb_detection",
    "USB detection",
    "Confirm the exact selected USB device identity. No board identity is inferred.",
  ],
  [
    "serial_connection",
    "Serial connection",
    "Passes only when the existing single-owner service receives multiple valid packets.",
  ],
  [
    "stream",
    "30-second stream",
    "Measures real host receive timing, gaps, packet validity, drops, queues, CPU, and memory.",
  ],
  [
    "channels",
    "Channel check",
    "Checks configured channels update, remain valid, and stay inside the declared raw range.",
  ],
  [
    "baseline",
    "Three rest baselines",
    "Create three real 5-second baselines in EMG Collection, then enter their IDs below.",
  ],
  [
    "fixed_trial",
    "Fixed-duration trial",
    "Runs a 3-2-1 countdown, records for the requested duration, and finalizes for review.",
  ],
  [
    "manual_trial",
    "Manual-stop trial",
    "Starts a real validation recording that ends only when Stop trial is pressed.",
  ],
  [
    "event_markers",
    "Event markers",
    "Adds MOVEMENT_STARTED, TARGET_REACHED, and SENSOR_ISSUE during the manual trial.",
  ],
  [
    "review",
    "Review behavior",
    "Approve the current engineering recording; it remains excluded from training.",
  ],
  [
    "retry",
    "Retry traceability",
    "Verifies the prior and replacement attempts have distinct recording IDs.",
  ],
  [
    "interruption",
    "USB interruption",
    "Arm while streaming, then physically unplug USB. The button never substitutes for detected disconnect.",
  ],
  [
    "reconnect",
    "Reconnect / COM change",
    "Replug and reconnect through EMG Live, then verify new valid samples and any COM renumbering.",
  ],
  [
    "long_run",
    "Five-minute long run",
    "Sustained real stream test. Keep this page open until the timer finishes.",
  ],
  [
    "dataset",
    "Dataset registration",
    "Confirms the validation recording is registered with its run and hardware references.",
  ],
  [
    "raw_integrity",
    "Raw integrity",
    "Recalculates the raw CSV SHA-256 and compares it with the stored integrity report.",
  ],
  [
    "processing",
    "Processing compatibility",
    "Creates derived signals and proves the source raw file hash is unchanged.",
  ],
  [
    "training_eligibility",
    "Training exclusion",
    "Confirms engineering validation data are not training eligible.",
  ],
] as const;

function stateClass(state?: string) {
  return state === "PASS"
    ? "pass"
    : state === "WARNING"
      ? "warning"
      : state === "FAIL"
        ? "fail"
        : state === "RUNNING"
          ? "running"
          : "idle";
}
function text(value: unknown) {
  return value === null || value === undefined || value === ""
    ? "—"
    : typeof value === "number"
      ? Number.isInteger(value)
        ? value.toLocaleString()
        : value.toFixed(2)
      : String(value);
}

export function EmgValidationLab() {
  const [profiles, setProfiles] = useState<HardwareProfile[]>([]),
    [selected, setSelected] = useState(""),
    [devices, setDevices] = useState<Device[]>([]),
    [port, setPort] = useState(""),
    [run, setRun] = useState<ValidationRun | null>(null),
    [history, setHistory] = useState<ValidationRun[]>([]),
    [profileCheck, setProfileCheck] = useState<Record<string, unknown> | null>(
      null,
    ),
    [diagnostics, setDiagnostics] = useState<Diagnostics>({}),
    [board, setBoard] = useState<EmgStatus | null>(null),
    [baselines, setBaselines] = useState<Baseline[]>([]),
    [baselineIds, setBaselineIds] = useState(""),
    [recordingId, setRecordingId] = useState(""),
    [priorRecordingId, setPriorRecordingId] = useState(""),
    [rehabType, setRehabType] = useState("REACHING"),
    [researchLabel, setResearchLabel] = useState("full_trial"),
    [duration, setDuration] = useState(10),
    [longDuration, setLongDuration] = useState(300),
    [busy, setBusy] = useState(""),
    [error, setError] = useState("");
  const stream = useEmgStream(true);
  const loadDevices = useCallback(async () => {
    const response = await fetch(`${api}/devices`);
    const rows = response.ok ? await response.json() : [];
    const usbOnly = Array.isArray(rows)
      ? rows.filter((device: Device) => device.is_usb)
      : [];
    setDevices(usbOnly);
    setPort((current) =>
      usbOnly.some((device: Device) => device.port === current)
        ? current
        : usbOnly[0]?.port || "",
    );
  }, []);
  const loadStatic = useCallback(async () => {
    const [p, b] = await Promise.all([
      fetch(`${api}/hardware-profiles`),
      fetch(`${api}/baselines`),
    ]);
    const profileRows = p.ok ? await p.json() : [],
      baselineRows = b.ok ? await b.json() : [];
    setProfiles(Array.isArray(profileRows) ? profileRows : []);
    setBaselines(Array.isArray(baselineRows) ? baselineRows : []);
    setSelected(
      (current) =>
        current ||
        new URLSearchParams(location.search).get("hardware") ||
        profileRows.find(
          (x: HardwareProfile) => !x.archived && x.transport_type !== "MOCK",
        )?.hardware_profile_id ||
        "",
    );
  }, []);
  const loadLive = useCallback(async () => {
    const [s, d] = await Promise.all([
      fetch(`${api}/status`),
      fetch(`${api}/serial-diagnostics`),
    ]);
    if (s.ok) {
      const value = await s.json();
      setBoard(value);
      if (value.serial_port) setPort(value.serial_port);
    }
    if (d.ok) setDiagnostics(await d.json());
  }, []);
  const loadProfile = useCallback(
    async (profileId: string) => {
      if (!profileId) return;
      const [h, c] = await Promise.all([
        fetch(
          `${api}/commissioning/runs?hardware_profile_id=${encodeURIComponent(profileId)}`,
        ),
        fetch(`${api}/commissioning/profiles/${encodeURIComponent(profileId)}`),
      ]);
      if (h.ok) {
        const rows = await h.json();
        setHistory(rows);
        if (rows[0]?.status === "RUNNING") setRun((current) => current || rows[0]);
      }
      if (c.ok) setProfileCheck(await c.json());
    },
    [],
  );
  useEffect(() => {
    loadStatic().catch(() =>
      setError("Validation setup data are unavailable."),
    );
    loadDevices().catch(() => setDevices([]));
    void loadLive();
  }, [loadStatic, loadDevices, loadLive]);
  useEffect(() => {
    if (stream.status?.connection_state === "STREAMING") return;
    const timer = window.setInterval(() => void loadDevices(), 2000);
    return () => window.clearInterval(timer);
  }, [loadDevices, stream.status?.connection_state]);
  useEffect(() => {
    void loadProfile(selected);
  }, [selected, loadProfile]);
  const validationRunId = run?.validation_run_id;
  useEffect(() => {
    if (!validationRunId) return;
    const timer = window.setInterval(async () => {
      const [r] = await Promise.all([
        fetch(`${api}/commissioning/runs/${validationRunId}`),
        loadLive(),
      ]);
      if (r.ok) {
        const value = await r.json();
        setRun(value);
        const rid =
          value.tests.manual_trial?.metrics?.recording_id ||
          value.tests.fixed_trial?.metrics?.recording_id;
        if (rid) setRecordingId(rid);
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [validationRunId, loadLive]);
  const profile = profiles.find((x) => x.hardware_profile_id === selected),
    status = stream.status || board,
    channels = status?.channels || [];
  const completed = useMemo(
    () =>
      run
        ? Object.values(run.tests).filter((t) =>
            ["PASS", "WARNING"].includes(t.state),
          ).length
        : 0,
    [run],
  );
  function blockedBy(id: string) {
    if (!run) return ["validation run"];
    if (id === "event_markers")
      return run.tests.manual_trial?.state === "RUNNING"
        ? []
        : ["manual trial must be recording"];
    return (prerequisites[id] || []).filter(
      (required) => !["PASS", "WARNING"].includes(run.tests[required]?.state),
    );
  }

  async function post(path: string, body: Record<string, unknown> = {}) {
    setBusy(path);
    setError("");
    try {
      const response = await fetch(`${api}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const value = await response.json();
      if (!response.ok)
        throw new Error(
          value.detail || value.error || "Validation action failed",
        );
      if (value.tests) setRun(value);
      return value;
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Validation action failed",
      );
      return null;
    } finally {
      setBusy("");
    }
  }
  async function create() {
    if (!selected) return;
    const value = await post("/commissioning/runs", {
      hardware_profile_id: selected,
      hardware_profile_version: profile?.profile_version,
      selected_port: port,
      baud_rate: status?.baud_rate,
      serial_protocol: status?.protocol,
      notes: "Physical ESP32 acquisition commissioning",
    });
    if (value) {
      setRun(value);
      setHistory((rows) => [value, ...rows]);
    }
  }
  async function test(id: string, extra: Record<string, unknown> = {}) {
    if (!run) return;
    await post(`/commissioning/runs/${run.validation_run_id}/tests/${id}`, {
      duration_seconds: id === "long_run" ? longDuration : duration,
      baseline_ids: baselineIds
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean),
      recording_id: recordingId || undefined,
      prior_recording_id: priorRecordingId || undefined,
      rehab_type: rehabType,
      research_label: researchLabel,
      notes: "Engineering hardware validation",
      ...extra,
    });
  }
  async function review(decision: string) {
    if (!run) return;
    await post(`/commissioning/runs/${run.validation_run_id}/review`, {
      decision,
      notes: "Engineering hardware validation review",
    });
  }
  function exportDiagnostics() {
    const payload = {
      exported_at: new Date().toISOString(),
      validation_run_id: run?.validation_run_id,
      device: status?.device,
      port: status?.serial_port || port,
      baud: status?.baud_rate,
      protocol: status?.protocol,
      configured_sample_rate_hz: profile?.expected_sample_rate_hz,
      received_rate_hz: status?.received_rate_hz,
      packet_stats: diagnostics,
      quality: run?.tests.channels?.metrics,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: "application/json",
      }),
      url = URL.createObjectURL(blob),
      a = document.createElement("a");
    a.href = url;
    a.download = `${run?.validation_run_id || "emg"}-diagnostics.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section className="validation-page">
      <nav className="breadcrumbs">
        <Link href="/master/emg">EMG Data</Link>
        <span>›</span>
        <Link href="/master/emg/hardware">Hardware</Link>
        <span>›</span>
        <strong>Validation</strong>
      </nav>
      <header className="validation-title">
        <div>
          <span className="eyebrow">
            Engineering commissioning · real hardware only
          </span>
          <h1>EMG Hardware Commissioning</h1>
          <p className="master-lead">
            Systematically verify the physical ESP32 acquisition path without
            making physiological, electrical-safety, or clinical claims.
          </p>
        </div>
        <span
          className={`validation-overall ${stateClass(run?.status === "COMPLETE" ? "PASS" : run?.status === "FAILED" ? "FAIL" : run?.status === "COMPLETE_WITH_WARNINGS" ? "WARNING" : "RUNNING")}`}
        >
          {run?.status.replaceAll("_", " ") || "NOT STARTED"}
        </span>
      </header>
      <div className="validation-safety">
        <AlertTriangle />
        <span>
          <strong>Technical acquisition validation only.</strong>{" "}
          Human-connected prototype safety still depends on hardware design,
          power/isolation, electrodes, and research supervision.
        </span>
      </div>

      {!devices.length && (
        <div className="validation-no-device" role="status">
          <Usb />
          <div>
            <strong>NO USB ESP32 DETECTED</strong>
            <ol>
              <li>Plug the ESP32 into USB using a data cable.</li>
              <li>Confirm Windows detects the board.</li>
              <li>Close Arduino Serial Monitor, PuTTY, and other serial tools.</li>
              <li>Click Refresh; automatic detection also runs every 2 seconds.</li>
            </ol>
            <small>Bluetooth, virtual, and built-in COM ports are ignored.</small>
          </div>
        </div>
      )}

      <article className="master-card validation-setup">
        <div>
          <label>
            Hardware profile
            <select
              value={selected}
              disabled={Boolean(run)}
              onChange={(e) => {
                setSelected(e.target.value);
                setRun(null);
              }}
            >
              <option value="">Select real hardware</option>
              {profiles
                .filter((x) => x.transport_type !== "MOCK")
                .map((x) => (
                  <option
                    key={x.hardware_profile_id}
                    value={x.hardware_profile_id}
                  >
                    {x.display_name} · v{x.profile_version}
                  </option>
                ))}
            </select>
          </label>
          <label>
            Detected port
            <select
              value={port}
              disabled={Boolean(run)}
              onChange={(e) => setPort(e.target.value)}
            >
              <option value="">Select port</option>
              {devices.map((x) => (
                <option key={x.port} value={x.port}>
                  {x.port} · {x.description}
                </option>
              ))}
            </select>
          </label>
        </div>
        {profile && (
          <div className="validation-config">
            <span>
              Profile{" "}
              <strong>
                {profile.hardware_profile_id} v{profile.profile_version}
              </strong>
            </span>
            <span>
              Channels <strong>{profile.channel_count}</strong>
            </span>
            <span>
              Configured rate{" "}
              <strong>{profile.expected_sample_rate_hz} Hz</strong>
            </span>
            <span>
              Raw format <strong>{profile.raw_representation}</strong>
            </span>
            <span>
              Baud <strong>{profile.serial_baud_rate || 115200}</strong>
            </span>
            <span>
              Protocol <strong>{profile.protocol || "CSV_CHANNELS"}</strong>
            </span>
          </div>
        )}
        {devices.find((device) => device.port === port) && (
          <dl className="validation-device-identity">
            {Object.entries({
              Port: port,
              Description: devices.find((device) => device.port === port)?.description,
              Manufacturer: devices.find((device) => device.port === port)?.manufacturer,
              VID: devices.find((device) => device.port === port)?.usb_vid,
              PID: devices.find((device) => device.port === port)?.usb_pid,
              Serial: devices.find((device) => device.port === port)?.serial_number,
            }).map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value ? text(value) : "NOT AVAILABLE"}</dd>
              </div>
            ))}
          </dl>
        )}
        <div className="validation-actions">
          <button
            onClick={() => {
              void loadDevices();
              void loadLive();
            }}
          >
            <RefreshCw />
            Refresh devices
          </button>
          {!run ? (
            <button
              className="primary"
              disabled={!selected || !port || busy !== ""}
              onClick={create}
            >
              <Play />
              Start validation run
            </button>
          ) : (
            <>
              <strong>{run.validation_run_id}</strong>
              <button onClick={exportDiagnostics}>
                <Download />
                Export diagnostics
              </button>
            </>
          )}
        </div>
      </article>
      {Boolean(profileCheck?.warning) && (
        <div className="validation-mismatch">
          <AlertTriangle />
          <strong>{String(profileCheck?.warning)}</strong>
          <span>Rerun validation for the current profile version.</span>
        </div>
      )}

      <ol className="validation-stepper">
        {steps.map((step, index) => {
          const states = step.ids.length && run
            ? step.ids.map((id) => run.tests[id]?.state)
            : ["NOT_RUN"];
          const state = step.label === "Final Report" && run?.completed_at
            ? run.status === "FAILED"
              ? "FAIL"
              : run.status === "INCOMPLETE"
                ? "WARNING"
                : "PASS"
            : states.includes("FAIL")
            ? "FAIL"
            : states.includes("RUNNING")
              ? "RUNNING"
              : states.every((x) => ["PASS", "WARNING"].includes(x))
                ? states.includes("WARNING")
                  ? "WARNING"
                  : "PASS"
                : "NOT_RUN";
          return (
            <li key={step.label} className={stateClass(state)}>
              <i>
                {state === "PASS" ? (
                  <Check />
                ) : state === "FAIL" ? (
                  <X />
                ) : (
                  index + 1
                )}
              </i>
              <span>{step.label}</span>
            </li>
          );
        })}
      </ol>

      <div className="validation-grid">
        <article className="master-card validation-live">
          <div className="master-card-head">
            <div>
              <span className="eyebrow">Live real signal</span>
              <h2>Existing EMG renderer</h2>
            </div>
            <span
              className={`validation-chip ${stateClass(status?.connection_state === "STREAMING" ? "PASS" : "FAIL")}`}
            >
              {status?.connection_state || "DISCONNECTED"}
            </span>
          </div>
          <EmgChart
            samples={stream.samples}
            channels={channels}
            paused={false}
          />
        </article>
        <article className="master-card validation-serial">
          <span className="eyebrow">Raw serial status</span>
          <h2>Connection telemetry</h2>
          <dl>
            <div>
              <dt>Port</dt>
              <dd>{text(status?.serial_port || port)}</dd>
            </div>
            <div>
              <dt>Baud</dt>
              <dd>{text(status?.baud_rate)}</dd>
            </div>
            <div>
              <dt>Protocol</dt>
              <dd>{text(status?.protocol)}</dd>
            </div>
            <div>
              <dt>Bytes</dt>
              <dd>{text(diagnostics.bytes_received)}</dd>
            </div>
            <div>
              <dt>Valid packets</dt>
              <dd>
                {text(diagnostics.valid_packets ?? status?.valid_samples)}
              </dd>
            </div>
            <div>
              <dt>Invalid packets</dt>
              <dd>
                {text(diagnostics.invalid_packets ?? status?.invalid_packets)}
              </dd>
            </div>
            <div>
              <dt>Data age</dt>
              <dd>{text(status?.latest_data_age_ms)} ms</dd>
            </div>
            <div>
              <dt>Host receive</dt>
              <dd>{text(status?.received_rate_hz)} Hz</dd>
            </div>
          </dl>
        </article>
      </div>

      <section className="validation-tests">
        <header>
          <div>
            <span className="eyebrow">Test details</span>
            <h2>
              {completed} of {details.length} checks completed
            </h2>
          </div>
          <progress max={details.length} value={completed} />
        </header>
        {details.map(([id, title, instructions]) => {
          const item = run?.tests[id];
          return (
            <details
              className={`validation-test ${stateClass(item?.state)}`}
              key={id}
              open={item?.state === "RUNNING"}
            >
              <summary>
                <span>
                  {item?.state === "PASS" ? (
                    <Check />
                  ) : item?.state === "FAIL" ? (
                    <X />
                  ) : item?.state === "WARNING" ? (
                    <AlertTriangle />
                  ) : (
                    <Usb />
                  )}
                </span>
                <div>
                  <strong>{title}</strong>
                  <small>{instructions}</small>
                </div>
                <b>{item?.state.replaceAll("_", " ") || "NOT RUN"}</b>
              </summary>
              <div className="validation-test-body">
                {blockedBy(id).length > 0 && (
                  <p className="validation-locked">
                    Locked — complete {blockedBy(id).join(", ")} first.
                  </p>
                )}
                {id === "baseline" && (
                  <label>
                    Three baseline IDs
                    <input
                      value={baselineIds}
                      list="baseline-options"
                      placeholder="BASE-001, BASE-002, BASE-003"
                      onChange={(e) => setBaselineIds(e.target.value)}
                    />
                    <datalist id="baseline-options">
                      {baselines.map((x) => (
                        <option key={x.baseline_id} value={x.baseline_id} />
                      ))}
                    </datalist>
                    <Link href="/master/collect/emg">
                      Open existing baseline workflow
                    </Link>
                  </label>
                )}
                {["fixed_trial", "manual_trial"].includes(id) && (
                  <div className="validation-fields">
                    <label>
                      Rehab module ID
                      <input
                        value={rehabType}
                        onChange={(e) => setRehabType(e.target.value)}
                      />
                    </label>
                    <label>
                      Existing research label
                      <input
                        value={researchLabel}
                        onChange={(e) => setResearchLabel(e.target.value)}
                      />
                    </label>
                    <label>
                      Duration (seconds)
                      <input
                        type="number"
                        min="1"
                        max="120"
                        value={duration}
                        onChange={(e) => setDuration(+e.target.value)}
                      />
                    </label>
                  </div>
                )}
                {[
                  "dataset",
                  "raw_integrity",
                  "processing",
                  "training_eligibility",
                ].includes(id) && (
                  <label>
                    Validation recording ID
                    <input
                      value={recordingId}
                      placeholder="EMG-..."
                      onChange={(e) => setRecordingId(e.target.value)}
                    />
                  </label>
                )}
                {id === "retry" && (
                  <div className="validation-fields">
                    <label>
                      Prior recording ID
                      <input
                        value={priorRecordingId}
                        onChange={(e) => setPriorRecordingId(e.target.value)}
                      />
                    </label>
                    <label>
                      Replacement recording ID
                      <input
                        value={recordingId}
                        onChange={(e) => setRecordingId(e.target.value)}
                      />
                    </label>
                  </div>
                )}
                {id === "long_run" && (
                  <label>
                    Duration (seconds)
                    <input
                      type="number"
                      min="60"
                      max="900"
                      value={longDuration}
                      onChange={(e) => setLongDuration(+e.target.value)}
                    />
                  </label>
                )}
                {id === "interruption" && (
                  <div className="manual-callout">
                    <strong>UNPLUG BOARD NOW</strong>
                    <span>
                      First arm this test while streaming and preferably during
                      a TEST recording. Then physically unplug USB.
                    </span>
                    <button onClick={() => void loadLive()}>
                      I unplugged the board
                    </button>
                  </div>
                )}
                {id === "reconnect" && (
                  <div className="manual-callout">
                    <strong>REPLUG AND RECONNECT</strong>
                    <span>
                      Use EMG Live if the COM port changed. This check passes
                      only after real samples return.
                    </span>
                    <Link href="/master/live/emg">Open EMG Live</Link>
                  </div>
                )}
                <div className="validation-test-actions">
              {id !== "review" && (
                <button
                  disabled={
                    !run ||
                    busy !== "" ||
                    item?.state === "RUNNING" ||
                    blockedBy(id).length > 0
                  }
                  onClick={() => test(id)}
                >
                  {item?.state === "RUNNING" ? "Running…" : `Run ${title}`}
                </button>
              )}
                  {id === "manual_trial" && (
                    <button
                      disabled={!run}
                      onClick={() =>
                        post(
                          `/commissioning/runs/${run!.validation_run_id}/manual-stop`,
                        )
                      }
                    >
                      <Square />
                      Stop trial
                    </button>
                  )}
                  {id === "review" && (
                    <>
                      <button onClick={() => review("APPROVE")}>Approve</button>
                      <button onClick={() => review("APPROVE_WITH_WARNINGS")}>
                        Approve with warnings
                      </button>
                      <button onClick={() => review("RETRY")}>
                        Retry required
                      </button>
                    </>
                  )}
                </div>
                {item?.progress !== undefined && (
                  <progress max={1} value={item.progress} />
                )}
                {item?.warnings.length || item?.failures.length ? (
                  <div className="validation-findings">
                    {item.warnings.map((x) => (
                      <span key={x}>Warning: {x}</span>
                    ))}
                    {item.failures.map((x) => (
                      <span key={x}>Failure: {x}</span>
                    ))}
                  </div>
                ) : null}
                {item && Object.keys(item.metrics).length > 0 && (
                  <pre className="validation-output">
                    {JSON.stringify(item.metrics, null, 2)}
                  </pre>
                )}
              </div>
            </details>
          );
        })}
      </section>

      {run && (
        <article className="master-card validation-report">
          <div>
            <span className="eyebrow">Persistent evidence</span>
            <h2>Final hardware validation report</h2>
            <p>
              Completing summarizes all performed and not-run checks. A failed
              check produces FAIL; incomplete checks produce warnings.
            </p>
          </div>
          <div className="validation-actions">
            <button
              disabled={
                busy !== "" ||
                Object.values(run.tests).some((x) => x.state === "RUNNING")
              }
              onClick={() =>
                post(`/commissioning/runs/${run.validation_run_id}/complete`)
              }
            >
              Complete report
            </button>
            {run.completed_at && (
              <a
                className="button"
                href={`${api}/commissioning/runs/${run.validation_run_id}/evidence/emg_hardware_validation_report.json`}
              >
                <Download />
                Download report
              </a>
            )}
          </div>
        </article>
      )}

      <article className="master-card validation-history">
        <span className="eyebrow">Hardware profile</span>
        <h2>Validation history</h2>
        {history.length ? (
          <div>
            {history.map((x) => (
              <button key={x.validation_run_id} onClick={() => setRun(x)}>
                <strong>{x.validation_run_id}</strong>
                <span>Profile v{x.hardware_profile_version}</span>
                <b
                  className={stateClass(
                    x.status === "COMPLETE"
                      ? "PASS"
                      : x.status === "FAILED"
                        ? "FAIL"
                        : "WARNING",
                  )}
                >
                  {x.status.replaceAll("_", " ")}
                </b>
              </button>
            ))}
          </div>
        ) : (
          <p>No saved validation runs for this hardware profile.</p>
        )}
      </article>
      {error && <div className="master-alert">{error}</div>}
    </section>
  );
}
