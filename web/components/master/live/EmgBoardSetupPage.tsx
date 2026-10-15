"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { EmgChart } from "../emg/EmgChart";
import { useEmgStream } from "@/hooks/useEmgStream";
import type { EmgStatus, FirmwareStatus } from "@/types/emg";
import type { EmgSerialDevice } from "@/types/emgDevice";
import { emgErrorMessage } from "./EmgLivePage";
const api = "/api/master/data/emg";
const channels = [
  { internal_id: "channel_1", display_name: "Channel 1", body_side: "UNKNOWN" },
  { internal_id: "channel_2", display_name: "Channel 2", body_side: "UNKNOWN" },
];
type BoardTest = {
  passed: boolean;
  checks: Record<string, unknown>;
  note: string;
};
type SerialDiagnostics = {
  state: string;
  config?: {
    baud_rate: number;
    protocol: string;
    expected_channels: number;
    read_timeout_s: number;
    boot_wait_s: number;
    first_data_timeout_s: number;
    stale_timeout_s: number;
    dtr: string;
    rts: string;
  };
  bytes_received: number;
  lines_received: number;
  valid_packets: number;
  invalid_packets: number;
  rejection_categories: Record<string, number>;
  latest_raw_lines: string[];
  latest_data_age_ms?: number | null;
  reader_alive: boolean;
  last_error?: string | null;
};
type SerialProtocol =
  | "VALUE_ONLY"
  | "TIMESTAMP_VALUE"
  | "CSV_CHANNELS"
  | "TIMESTAMP_CSV_CHANNELS"
  | "SEQUENCE_TIMESTAMP_CSV";
export function EmgBoardSetupPage() {
  const stream = useEmgStream(true),
    [status, setStatus] = useState<EmgStatus | null>(null),
    [devices, setDevices] = useState<EmgSerialDevice[]>([]),
    [port, setPort] = useState(""),
    [advanced, setAdvanced] = useState(false),
    [mock, setMock] = useState(false),
    [firmware, setFirmware] = useState<FirmwareStatus | null>(null),
    [test, setTest] = useState<BoardTest | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [baud, setBaud] = useState(115200),
    [protocol, setProtocol] = useState<SerialProtocol>("CSV_CHANNELS"),
    [channelCount, setChannelCount] = useState(2),
    [diagnostics, setDiagnostics] = useState<SerialDiagnostics | null>(null);
  const streaming = status?.connection_state === "STREAMING",
    active = Boolean(
      status && !["DISCONNECTED", "ERROR"].includes(status.connection_state),
    );
  async function refresh() {
    try {
      const [a, b] = await Promise.all([
        fetch(`${api}/devices${advanced ? "?include_non_usb=true" : ""}`),
        fetch(`${api}/status`),
      ]);
      if (!a.ok || !b.ok) throw new Error("EMG backend is unavailable");
      const list = (await a.json()) as EmgSerialDevice[],
        next = (await b.json()) as EmgStatus;
      setDevices(list);
      setStatus(next);
      setPort(
        (current) =>
          next.serial_port ||
          (list.some((item) => item.port === current) ? current : ""),
      );
      setError(
        next.connection_error ? next.connection_error.replaceAll("_", " ") : "",
      );
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "EMG backend is unavailable",
      );
    }
  }
  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [advanced]);
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!streaming) void refresh();
    }, 2500);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streaming, advanced]);
  useEffect(() => {
    if (stream.status) setStatus(stream.status);
  }, [stream.status]);
  useEffect(() => {
    if (!status || status.connection_state === "DISCONNECTED") return;
    void loadDiagnostics();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status?.connection_state]);
  useEffect(() => {
    if (!port || mock) {
      setFirmware(null);
      return;
    }
    void fetch(`${api}/firmware/status?port=${encodeURIComponent(port)}`).then(
      async (response) => {
        if (response.ok) setFirmware(await response.json());
      },
    );
  }, [port, mock]);
  async function connect() {
    setBusy(true);
    setError("");
    setTest(null);
    try {
      const response = await fetch(`${api}/connect`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            transport_type: mock ? "MOCK" : "USB_SERIAL",
            ...(mock ? { mock_scenario: "CLEAN_EMG_LIKE" } : {}),
            serial_port: mock ? null : port,
            baud_rate: baud,
            protocol,
            expected_sample_rate_hz: 1000,
            channels: channels.slice(0, channelCount),
          }),
        }),
        body: unknown = await response.json();
      if (!response.ok) throw new Error(emgErrorMessage(body));
      setStatus(body as EmgStatus);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Connection failed");
    } finally {
      setBusy(false);
    }
  }
  async function disconnect() {
    setBusy(true);
    await fetch(`${api}/disconnect`, { method: "POST" });
    setTest(null);
    await refresh();
    setBusy(false);
  }
  async function runTest() {
    const response = await fetch(`${api}/board-test`, { method: "POST" });
    if (response.ok) setTest(await response.json());
  }
  async function reconnect() {
    setBusy(true);
    setError("");
    const response = await fetch(`${api}/reconnect`, { method: "POST" }),
      body: unknown = await response.json();
    if (response.ok) setStatus(body as EmgStatus);
    else setError(emgErrorMessage(body));
    setBusy(false);
  }
  async function loadDiagnostics() {
    const response = await fetch(`${api}/serial-diagnostics`);
    if (response.ok) setDiagnostics(await response.json());
  }
  const selected = devices.find((item) => item.port === port),
    activeFirmware = status?.firmware || firmware,
    step = streaming ? (test?.passed ? 4 : 3) : port || mock ? 2 : 1,
    displayChannels = status?.channels?.length ? status.channels : channels,
    samples = useMemo(() => stream.samples.slice(-5000), [stream.samples]);
  return (
    <section className="emg-board-page">
      <nav className="breadcrumbs">
        <Link href="/master/live">Live Sensors</Link>
        <span>›</span>
        <strong>EMG Board</strong>
      </nav>
      <span className="eyebrow">Master engineering setup · no recording</span>
      <h1>Connect your EMG board</h1>
      <ol className="board-stepper">
        {["Board", "Firmware", "Signal", "Ready"].map((label, index) => (
          <li
            key={label}
            className={
              index + 1 < step
                ? "complete"
                : index + 1 === step
                  ? "current"
                  : ""
            }
          >
            <i>{index + 1 < step ? "✓" : index + 1}</i>
            <span>{label}</span>
          </li>
        ))}
      </ol>
      {error && (
        <div className="live-warning">
          <strong>Board connection needs attention</strong>
          <span>{error}</span>
          <button onClick={refresh}>Retry</button>
        </div>
      )}
      <article className="master-card board-hero">
        <div className="master-card-head">
          <div>
            <span className="eyebrow">EMG board</span>
            <h2>
              {streaming
                ? "Board connected"
                : active
                  ? "Connecting to board"
                  : "Plug in and select a board"}
            </h2>
          </div>
          <span className={`board-state ${streaming ? "ready" : ""}`}>
            {status?.connection_state || "NO DEVICE"}
          </span>
        </div>
        <div className="board-summary">
          <div>
            <span>USB device</span>
            <strong>
              {mock
                ? "Mock engineering source"
                : selected
                  ? `${selected.description || "USB serial device"} · ${selected.port}`
                  : "Not selected"}
            </strong>
            <small>
              {selected?.manufacturer ||
                "Select a currently connected USB serial device."}
            </small>
          </div>
          <div>
            <span>Firmware</span>
            <strong>
              {activeFirmware?.release
                ? `FlexMap ${activeFirmware.release.version}`
                : "Unknown"}
            </strong>
            <small>
              {activeFirmware?.disabled_reason ||
                "Firmware identity is not reported by the current protocol."}
            </small>
          </div>
          <div>
            <span>Connection</span>
            <strong>
              {status?.verification === "DATA_STREAM_VERIFIED"
                ? `${status.received_rate_hz.toFixed(1)} Hz · ${status.channel_count} channels`
                : "Not verified"}
            </strong>
            <small>
              {status?.verification === "DATA_STREAM_VERIFIED"
                ? "Data stream verified"
                : "Opening a COM port alone does not count as verification."}
            </small>
          </div>
        </div>
        {!active && (
          <div className="board-picker">
            <label className="check">
              <input
                type="checkbox"
                checked={mock}
                onChange={(event) => setMock(event.target.checked)}
              />{" "}
              Use mock data for engineering tests
            </label>
            {!mock &&
              (devices.length ? (
                <div className="device-choice-list">
                  {devices.map((device) => (
                    <label
                      key={device.port}
                      className={port === device.port ? "selected" : ""}
                    >
                      <input
                        type="radio"
                        name="emg-port"
                        checked={port === device.port}
                        onChange={() => setPort(device.port)}
                      />
                      <span>
                        <strong>{device.port}</strong>
                        {device.description}
                        <small>
                          {device.manufacturer || "Manufacturer unavailable"}
                          {device.vid && device.pid
                            ? ` · VID ${device.vid} / PID ${device.pid}`
                            : ""}
                        </small>
                      </span>
                    </label>
                  ))}
                </div>
              ) : (
                <div className="usb-empty">
                  <strong>No USB EMG board detected</strong>
                  <span>
                    Plug the board directly into this computer, then refresh.
                  </span>
                </div>
              ))}
            {!mock && (
              <details>
                <summary>Advanced serial ports</summary>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={advanced}
                    onChange={(event) => setAdvanced(event.target.checked)}
                  />{" "}
                  Show Bluetooth, virtual, and built-in ports
                </label>
              </details>
            )}
            <details className="serial-settings">
              <summary>Serial settings</summary>
              <div className="field-pair">
                <label>
                  Baud rate
                  <select
                    value={baud}
                    onChange={(event) => setBaud(Number(event.target.value))}
                  >
                    <option value="9600">9600</option>
                    <option value="57600">57600</option>
                    <option value="115200">115200</option>
                    <option value="230400">230400</option>
                    <option value="460800">460800</option>
                    <option value="921600">921600</option>
                  </select>
                </label>
                <label>
                  Protocol
                  <select
                    value={protocol}
                    onChange={(event) =>
                      setProtocol(event.target.value as SerialProtocol)
                    }
                  >
                    <option>VALUE_ONLY</option>
                    <option>TIMESTAMP_VALUE</option>
                    <option>CSV_CHANNELS</option>
                    <option>TIMESTAMP_CSV_CHANNELS</option>
                    <option>SEQUENCE_TIMESTAMP_CSV</option>
                  </select>
                </label>
                <label>
                  Channels
                  <select
                    value={channelCount}
                    onChange={(event) =>
                      setChannelCount(Number(event.target.value))
                    }
                  >
                    <option value="1">1</option>
                    <option value="2">2</option>
                    <option value="3">3</option>
                    <option value="4">4</option>
                  </select>
                </label>
              </div>
            </details>
          </div>
        )}
        <div className="board-actions">
          {active ? (
            <>
              <button className="danger" disabled={busy} onClick={disconnect}>
                Disconnect
              </button>
              <button disabled={busy || !streaming} onClick={runTest}>
                Test board
              </button>
            </>
          ) : (
            <>
              <button onClick={refresh}>Refresh devices</button>
              <button
                className="primary"
                disabled={busy || (!mock && !port)}
                onClick={connect}
              >
                {busy ? "Connecting and verifying…" : "Connect board"}
              </button>
            </>
          )}
          <button
            disabled={!activeFirmware?.flash_enabled}
            title={activeFirmware?.disabled_reason || ""}
          >
            Flash board
          </button>
          {status &&
            ["ERROR", "STALE", "RECONNECTING"].includes(
              status.connection_state,
            ) && (
              <button disabled={busy} onClick={reconnect}>
                Reconnect
              </button>
            )}
        </div>
        {!mock && (
          <details
            className="serial-debug"
            onToggle={(event) => {
              if (event.currentTarget.open) void loadDiagnostics();
            }}
          >
            <summary>Serial debug</summary>
            {diagnostics ? (
              <>
                <div className="test-grid">
                  <div>
                    <span>Port / state</span>
                    <strong>{diagnostics.state}</strong>
                  </div>
                  <div>
                    <span>Bytes / lines</span>
                    <strong>
                      {diagnostics.bytes_received} /{" "}
                      {diagnostics.lines_received}
                    </strong>
                  </div>
                  <div>
                    <span>Valid / invalid</span>
                    <strong>
                      {diagnostics.valid_packets} /{" "}
                      {diagnostics.invalid_packets}
                    </strong>
                  </div>
                  <div>
                    <span>Baud / protocol</span>
                    <strong>
                      {diagnostics.config?.baud_rate} /{" "}
                      {diagnostics.config?.protocol}
                    </strong>
                  </div>
                  <div>
                    <span>Data age</span>
                    <strong>
                      {diagnostics.latest_data_age_ms == null
                        ? "No valid data"
                        : diagnostics.latest_data_age_ms.toFixed(0) + " ms"}
                    </strong>
                  </div>
                  <div>
                    <span>Reader</span>
                    <strong>
                      {diagnostics.reader_alive ? "Running" : "Stopped"}
                    </strong>
                  </div>
                </div>
                <h3>Latest raw serial</h3>
                <pre>
                  {diagnostics.latest_raw_lines.length
                    ? diagnostics.latest_raw_lines.join("\n")
                    : "No serial lines received."}
                </pre>
                <h3>Parser rejections</h3>
                <pre>
                  {JSON.stringify(diagnostics.rejection_categories, null, 2)}
                </pre>
                <button
                  onClick={() =>
                    navigator.clipboard.writeText(
                      JSON.stringify(diagnostics, null, 2),
                    )
                  }
                >
                  Copy serial diagnostics
                </button>
              </>
            ) : (
              <p>Open a physical serial connection to view diagnostics.</p>
            )}
          </details>
        )}
      </article>
      {test && (
        <article className="master-card board-test">
          <div className="master-card-head">
            <h2>Board test</h2>
            <span className={`board-state ${test.passed ? "ready" : ""}`}>
              {test.passed ? "PASSED" : "NEEDS ATTENTION"}
            </span>
          </div>
          <div className="test-grid">
            {Object.entries(test.checks).map(([name, value]) => (
              <div key={name}>
                <span>{name.replaceAll("_", " ")}</span>
                <strong>
                  {typeof value === "object"
                    ? JSON.stringify(value)
                    : String(value)}
                </strong>
              </div>
            ))}
          </div>
          <p>{test.note}</p>
        </article>
      )}
      <article className="master-card emg-live-chart">
          <div className="master-card-head">
            <div>
              <span className="eyebrow">Step 3 · signal</span>
              <h2>Live EMG graph</h2>
              <small>{status?.serial_port || "No port"} · {status?.received_rate_hz ? `${status.received_rate_hz.toFixed(1)} Hz` : "Waiting for samples"} · {displayChannels.length} channel{displayChannels.length === 1 ? "" : "s"}</small>
            </div>
            {streaming && <Link className="button" href="/master/emg">
              Start EMG data collection
            </Link>}
          </div>
          <div className="emg-chart-stage">
            <EmgChart samples={samples} channels={displayChannels} paused={false} />
            {!streaming && <div className="emg-chart-overlay emg-chart-overlay--waiting"><strong>{active ? "Waiting for EMG samples" : "EMG board disconnected"}</strong><span>{active ? `Port ${status?.serial_port || port || "selected"} is open. Check the firmware baud rate, protocol, and sensor output.` : "Connect a physical board or mock source to begin plotting."}</span></div>}
          </div>
          <p className="live-monitor-note">
            The graph stays visible while connecting. This monitor does not
            create a recording, baseline, research session, or Dataset Vault entry.
          </p>
      </article>
    </section>
  );
}
