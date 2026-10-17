'use client';
import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { useEmgStream } from '@/hooks/useEmgStream';
import type { EmgModule, EmgStatus, HardwareProfile } from '@/types/emg';
import type { EmgSerialDevice } from '@/types/emgDevice';
import { EmgChart } from './EmgChart';
import { EmgRecent } from './EmgRecent';
import { EmgProcessingPanel } from './EmgProcessingPanel';
type RecordState = {
  state: string;
  recording_id?: string;
  review?: {
    metadata: {
      sample_count: number;
      measured_sample_rate_hz: number;
      technical_quality: string;
    };
  };
};
const api = '/api/master/data/emg';
export function EmgDashboard({ slug }: { slug: string }) {
  const [module, setModule] = useState<EmgModule | null>(),
    [devices, setDevices] = useState<EmgSerialDevice[]>([]),
    [profiles, setProfiles] = useState<HardwareProfile[]>([]),
    [hardwareProfile, setHardwareProfile] = useState(''),
    [status, setStatus] = useState<EmgStatus | null>(null),
    [mock, setMock] = useState(true),
    [mockScenario, setMockScenario] = useState('CLEAN_EMG_LIKE'),
    [port, setPort] = useState(''),
    [advancedPorts, setAdvancedPorts] = useState(false),
    [baud, setBaud] = useState(115200),
    [protocol, setProtocol] = useState('CSV_CHANNELS'),
    [channelCount, setChannelCount] = useState(2),
    [channels, setChannels] = useState([
      {
        internal_id: 'channel_1',
        display_name: 'Triceps',
        muscle_label: 'TRICEPS_BRACHII',
        body_side: 'RIGHT',
      },
      {
        internal_id: 'channel_2',
        display_name: 'Biceps',
        muscle_label: 'BICEPS_BRACHII',
        body_side: 'RIGHT',
      },
    ]),
    [paused, setPaused] = useState(false),
    [subject, setSubject] = useState(''),
    [label, setLabel] = useState(''),
    [side, setSide] = useState('UNKNOWN'),
    [duration, setDuration] = useState(10),
    [session, setSession] = useState(''),
    [notes, setNotes] = useState(''),
    [consent, setConsent] = useState(false),
    [record, setRecord] = useState<RecordState>({ state: 'IDLE' }),
    [error, setError] = useState('');
  const stream = useEmgStream(true);
  const refresh = useCallback(async () => {
    const [a, b] = await Promise.all([
      fetch(`${api}/devices${advancedPorts ? '?include_non_usb=true' : ''}`),
      fetch(`${api}/status`),
    ]);
    if (a.ok) {
      const x = await a.json();
      setDevices(x);
      setPort((current) => x.some((device: EmgSerialDevice) => device.port === current) ? current : '');
    }
    if (b.ok) setStatus(await b.json());
  }, [advancedPorts]);
  useEffect(() => {
    fetch(`${api}/rehab-modules`)
      .then((r) => r.json())
      .then((x: EmgModule[]) => {
        const m = x.find((v) => v.slug === slug) || null;
        setModule(m);
        fetch(`${api}/hardware-profiles`)
          .then((r) => (r.ok ? r.json() : []))
          .then((p: HardwareProfile[]) => {
            const list = Array.isArray(p) ? p : [];
            setProfiles(list);
            setHardwareProfile(list[0]?.hardware_profile_id || '');
          })
          .catch(() => setProfiles([]));
        if (m) {
          setLabel(m.emg_labels[0] || '');
          const q = new URLSearchParams(window.location.search);
          setSubject(q.get('subject_id') || '');
          setSession(q.get('session_id') || '');
          setSide(q.get('affected_side') || 'UNKNOWN');
        }
      });
    refresh();
  }, [slug, refresh]);
  useEffect(() => {
    if (stream.status) setStatus(stream.status);
  }, [stream.status]);
  useEffect(() => {
    const t = setInterval(
      () =>
        fetch(`${api}/recordings/status`)
          .then((r) => r.json())
          .then(setRecord),
      500,
    );
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    if (mock || status?.connection_state === 'STREAMING') return;
    const timer = setInterval(() => void refresh(), 2500);
    return () => clearInterval(timer);
  }, [mock, status?.connection_state, refresh]);
  useEffect(() => {
    if (port) return;
    const profile = profiles.find((item) => item.hardware_profile_id === hardwareProfile);
    if (!profile) return;
    if (!profile.device_serial_number && !(profile.usb_vid && profile.usb_pid)) return;
    const matches = devices.filter((device) =>
      (!profile.device_serial_number || profile.device_serial_number === device.serial_number) &&
      (!profile.usb_vid || profile.usb_vid.toUpperCase() === device.usb_vid?.toUpperCase()) &&
      (!profile.usb_pid || profile.usb_pid.toUpperCase() === device.usb_pid?.toUpperCase()),
    );
    if (matches.length === 1) setPort(matches[0].port);
  }, [devices, hardwareProfile, profiles, port]);
  function activeChannels() {
    return Array.from(
      { length: channelCount },
      (_, i) =>
        channels[i] || {
          internal_id: `channel_${i + 1}`,
          display_name: `Channel ${i + 1}`,
          muscle_label: '',
          body_side: side,
        },
    );
  }
  async function connect() {
    setError('');
    const r = await fetch(`${api}/connect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        transport_type: mock ? 'MOCK' : 'USB_SERIAL',
        mock_scenario: mockScenario,
        serial_port: mock ? null : port,
        baud_rate: baud,
        protocol,
        expected_sample_rate_hz: 1000,
        channels: activeChannels(),
      }),
    });
    if (!r.ok) setError((await r.json()).detail);
    else setStatus(await r.json());
  }
  async function disconnect() {
    await fetch(`${api}/disconnect`, { method: 'POST' });
    await refresh();
  }
  async function start() {
    setError('');
    const r = await fetch(`${api}/recordings/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        rehab_type: module?.id,
        subject_id: subject,
        research_label: label,
        duration_seconds: duration,
        affected_side: side,
        session_id: session || null,
        notes,
        consent_recorded: consent,
        hardware_profile_id: hardwareProfile || null,
      }),
    });
    const x = await r.json();
    if (r.ok) setRecord(x);
    else setError(x.detail);
  }
  async function reviewAction(action: 'save' | 'discard') {
    const r = await fetch(
      action === 'save'
        ? `${api}/recordings/${record.recording_id}/save`
        : `${api}/recordings/${record.recording_id}/review`,
      { method: action === 'save' ? 'POST' : 'DELETE' },
    );
    if (r.ok) setRecord({ state: action === 'save' ? 'SAVED' : 'DISCARDED' });
  }
  if (module === undefined) return <p>Loading EMG module...</p>;
  if (!module) return <p>Unknown EMG module.</p>;
  const connected = status?.connection_state === 'STREAMING',
    liveChannels = status?.channels?.length
      ? status.channels
      : activeChannels(),
    selectedHardware = profiles.find(
      (p) => p.hardware_profile_id === hardwareProfile,
    ),
    selectedDevice = devices.find((d) => d.port === port),
    identityConfigured = Boolean(
      selectedHardware?.device_serial_number ||
        (selectedHardware?.usb_vid && selectedHardware?.usb_pid),
    ),
    identityMatches = Boolean(
      selectedHardware &&
        selectedDevice &&
        (!selectedHardware.device_serial_number ||
          selectedHardware.device_serial_number ===
            selectedDevice.serial_number) &&
        (!selectedHardware.usb_vid ||
          selectedHardware.usb_vid === selectedDevice.usb_vid) &&
        (!selectedHardware.usb_pid ||
          selectedHardware.usb_pid === selectedDevice.usb_pid),
    );
  return (
    <section>
      <nav className='breadcrumbs'>
        <Link href='/master/emg'>EMG Data</Link>
        <span>›</span>
        <strong>{module.name}</strong>
      </nav>
      <span className='eyebrow'>{module.id} · Raw observation only</span>
      <h1>EMG Data Collection</h1>
      <p className='master-lead'>
        FlexMap EMG is a research signal-acquisition prototype. Raw amplitude is
        not a direct measure of muscle strength. Clinical interpretation
        requires qualified supervision and appropriate electrical isolation.
      </p>
      <article className='master-card'>
        <div className='master-card-head'>
          <strong>Live EMG</strong>
          <span>
            {status?.is_mock
              ? 'MOCK DATA'
              : connected
                ? '● LIVE'
                : 'DISCONNECTED'}
          </span>
        </div>
        <EmgChart
          samples={stream.samples}
          channels={liveChannels}
          paused={paused}
        />
        <div className='review-actions horizontal'>
          <button onClick={() => setPaused((x) => !x)}>
            {paused ? 'Resume view' : 'Pause view'}
          </button>
          <button onClick={stream.clear}>Clear graph</button>
        </div>
      </article>
      <div className='emg-layout'>
        <article className='master-card setup'>
          <h2>Device connection</h2>
          <label>
            Hardware profile
            <select
              value={hardwareProfile}
              onChange={(e) => setHardwareProfile(e.target.value)}
            >
              <option value=''>LEGACY / UNSPECIFIED</option>
              {profiles.map((p) => (
                <option
                  key={p.hardware_profile_id}
                  value={p.hardware_profile_id}
                >
                  {p.display_name} v{p.profile_version}
                </option>
              ))}
            </select>
          </label>
          <label className='check'>
            <input
              type='checkbox'
              checked={mock}
              onChange={(e) => setMock(e.target.checked)}
            />{' '}
            EMG Mock Mode
          </label>
          {mock && (
            <label>
              Mock signal scenario
              <select
                value={mockScenario}
                onChange={(e) => setMockScenario(e.target.value)}
              >
                <option>CLEAN_EMG_LIKE</option>
                <option>POWERLINE_50HZ</option>
                <option>POWERLINE_60HZ</option>
                <option>FLATLINE</option>
                <option>CLIPPING</option>
                <option>PERFECT_CLOCK</option>
                <option>JITTER</option>
                <option>SEQUENCE_GAPS</option>
                <option>DUPLICATES</option>
                <option>CLOCK_DRIFT</option>
                <option>BURST_DELIVERY</option>
                <option>10_BIT_NORMAL</option>
                <option>12_BIT_NORMAL</option>
                <option>SIGNED_16_BIT</option>
                <option>OUT_OF_RANGE</option>
                <option>LOW_DYNAMIC_RANGE</option>
                <option>STABLE</option>
                <option>VARIABLE</option>
                <option>DRIFT</option>
              </select>
            </label>
          )}
          {devices.length ? <label>
            {advancedPorts ? 'Advanced serial port' : 'USB EMG device'}
            <select
              disabled={mock}
              value={port}
              onChange={(e) => setPort(e.target.value)}
            >
              <option value=''>No device selected</option>
              {devices.map((d) => (
                <option value={d.port} key={d.port}>
                  {d.port} — {d.description}
                </option>
              ))}
            </select>
          </label> : !mock && <div className='usb-empty'><strong>No USB device detected</strong><span>Plug in your EMG device using USB.</span></div>}
          {!mock && <details><summary>Advanced serial ports</summary><label className='check'><input type='checkbox' checked={advancedPorts} disabled={connected} onChange={(e)=>setAdvancedPorts(e.target.checked)}/> Show all serial ports</label></details>}
          {!mock && selectedDevice && <details className='device-details'><summary>Device details</summary><div className='preflight-grid'><span>Port: {selectedDevice.port}</span><span>Type: {selectedDevice.is_usb?'USB Serial':selectedDevice.port_type.replaceAll('_',' ')}</span>{selectedDevice.manufacturer&&<span>Manufacturer: {selectedDevice.manufacturer}</span>}{selectedDevice.vid&&<span>VID: {selectedDevice.vid}</span>}{selectedDevice.pid&&<span>PID: {selectedDevice.pid}</span>}{selectedDevice.serial_number&&<span>Serial: {selectedDevice.serial_number}</span>}</div></details>}
          {!mock && selectedHardware && (
            <p className={identityMatches ? '' : 'master-alert'}>
              {identityConfigured
                ? identityMatches
                  ? 'Expected device found — explicit connection required'
                  : 'Expected identity not found; do not assume this COM port is the profiled device.'
                : 'Possible device found — profile has no VID/PID/serial identity; verify manually.'}
            </p>
          )}
          <div className='field-pair'>
            <label>
              Baud
              <select value={baud} onChange={(e) => setBaud(+e.target.value)}>
                <option>9600</option>
                <option>57600</option>
                <option>115200</option>
                <option>230400</option>
              </select>
            </label>
            <label>
              Protocol
              <select
                value={protocol}
                onChange={(e) => setProtocol(e.target.value)}
              >
                <option>VALUE_ONLY</option>
                <option>TIMESTAMP_VALUE</option>
                <option>CSV_CHANNELS</option>
                <option>TIMESTAMP_CSV_CHANNELS</option>
                <option>SEQUENCE_TIMESTAMP_CSV</option>
              </select>
            </label>
          </div>
          <label>
            Channels
            <select
              value={channelCount}
              onChange={(e) => setChannelCount(+e.target.value)}
            >
              {[1, 2, 3, 4].map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
          </label>
          {activeChannels().map((ch, i) => (
            <div className='field-pair' key={ch.internal_id}>
              <label>
                Channel {i + 1} name
                <input
                  value={ch.display_name}
                  onChange={(e) =>
                    setChannels((v) => {
                      const n = [...v];
                      n[i] = { ...ch, display_name: e.target.value };
                      return n;
                    })
                  }
                />
              </label>
              <label>
                Muscle label
                <input
                  value={ch.muscle_label}
                  onChange={(e) =>
                    setChannels((v) => {
                      const n = [...v];
                      n[i] = { ...ch, muscle_label: e.target.value };
                      return n;
                    })
                  }
                />
              </label>
            </div>
          ))}
          <div className='review-actions horizontal'>
            <button onClick={refresh}>Refresh devices</button>
            {connected ? (
              <button className='danger' onClick={disconnect}>
                Disconnect
              </button>
            ) : (
              <button className='primary' disabled={!mock && !port} onClick={connect}>
                Connect
              </button>
            )}
          </div>
        </article>
        <article className='master-card setup'>
          <h2>Recording configuration</h2>
          <label>
            Rehab dataset
            <input value={module.name} disabled />
          </label>
          <label>
            Subject ID
            <input
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder='TEST-EMG-001'
            />
          </label>
          <label>
            Research label
            <select value={label} onChange={(e) => setLabel(e.target.value)}>
              {module.emg_label_options.map((x) => (
                <option value={x.id} key={x.id}>
                  {x.display_name}
                </option>
              ))}
            </select>
          </label>
          <div className='field-pair'>
            <label>
              Affected side
              <select value={side} onChange={(e) => setSide(e.target.value)}>
                <option>LEFT</option>
                <option>RIGHT</option>
                <option>UNKNOWN</option>
                <option>N/A</option>
              </select>
            </label>
            <label>
              Duration
              <select
                value={duration}
                onChange={(e) => setDuration(+e.target.value)}
              >
                {[5, 10, 30, 60].map((x) => (
                  <option key={x}>{x}</option>
                ))}
              </select>
            </label>
          </div>
          <label>
            Session ID
            <input
              value={session}
              onChange={(e) => setSession(e.target.value)}
            />
          </label>
          <label>
            Notes
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </label>
          <label className='check'>
            <input
              type='checkbox'
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
            />{' '}
            Research recording consent documented
          </label>
          {error && <p className='master-alert'>{error}</p>}
          <button
            className='primary'
            disabled={
              !connected ||
              !subject ||
              !consent ||
              ['COUNTDOWN', 'RECORDING', 'FINALIZING'].includes(record.state)
            }
            onClick={start}
          >
            {record.state === 'COUNTDOWN'
              ? 'Countdown 3 → 2 → 1'
              : record.state === 'RECORDING'
                ? 'Recording...'
                : 'Start recording'}
          </button>
          <div className='preflight-grid'>
            <span>State: {status?.connection_state || 'DISCONNECTED'}</span>
            <span>Rate: {status?.received_rate_hz?.toFixed(0) || 0} Hz</span>
            <span>
              Data age: {status?.latest_data_age_ms?.toFixed(1) || '—'} ms
            </span>
            <span>Valid: {status?.valid_samples || 0}</span>
            <span>Invalid: {status?.invalid_packets || 0}</span>
            <span>Drops: {status?.recorder_drops || 0}</span>
          </div>
        </article>
      </div>
      {record.state === 'REVIEW' && record.review && (
        <article className='master-card'>
          <span className='eyebrow'>Recording complete</span>
          <h2>{record.recording_id}</h2>
          <p>
            {record.review.metadata.sample_count} raw samples ·{' '}
            {record.review.metadata.measured_sample_rate_hz.toFixed(1)} Hz ·{' '}
            {record.review.metadata.technical_quality}
          </p>
          <div className='review-actions horizontal'>
            <button onClick={() => reviewAction('discard')}>Discard</button>
            <button className='primary' onClick={() => reviewAction('save')}>
              Save sample
            </button>
          </div>
        </article>
      )}
      <EmgRecent slug={slug} />
      <EmgProcessingPanel
        rehabType={module.id}
        subjectId={subject}
        connected={connected}
      />
    </section>
  );
}
