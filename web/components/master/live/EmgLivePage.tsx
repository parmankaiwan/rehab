'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { DEFAULT_EMG_GRAPH_SETTINGS, EmgChart } from '../emg/EmgChart';
import { EmgGraphSetupDrawer } from '../emg/EmgGraphSetupDrawer';
import { useEmgStream } from '@/hooks/useEmgStream';
import type { EmgGraphSettings, EmgStatus, SignalRepresentation } from '@/types/emg';
import type { EmgSerialDevice } from '@/types/emgDevice';
import { LiveStatusBadge, LiveState } from './LiveStatusBadge';
const api = '/api/master/data/emg';
const defaultChannels = [
  {
    internal_id: 'channel_1',
    display_name: 'Channel 1',
    body_side: 'UNKNOWN',
  },
];
export function emgErrorMessage(value: unknown) {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) {
    const messages = value
      .map((item) =>
        item && typeof item === 'object' && 'msg' in item
          ? String(item.msg)
          : '',
      )
      .filter(Boolean);
    if (messages.length) return messages.join(' - ');
  }
  if (value && typeof value === 'object' && 'detail' in value)
    return emgErrorMessage((value as { detail: unknown }).detail);
  return 'Connection failed';
}
export function EmgLivePage() {
  const stream = useEmgStream(true),
    [status, setStatus] = useState<EmgStatus | null>(null),
    [devices, setDevices] = useState<EmgSerialDevice[]>([]),
    [port, setPort] = useState(''),
    [mock, setMock] = useState(false),
    [scenario, setScenario] = useState('CLEAN_EMG_LIKE'),
    [paused, setPaused] = useState(false),
    [settings, setSettings] = useState<EmgGraphSettings>(DEFAULT_EMG_GRAPH_SETTINGS),
    [setupOpen, setSetupOpen] = useState(false),
    [advanced, setAdvanced] = useState(false),
    [error, setError] = useState('');
  async function refresh() {
    try {
      const [a, b] = await Promise.all([
        fetch(api + '/devices' + (advanced ? '?include_non_usb=true' : '')),
        fetch(api + '/status'),
      ]);
      if (!a.ok || !b.ok) throw new Error('Backend connection lost');
      const list = await a.json();
      setDevices(list);
      setPort((p) => (list.some((device: EmgSerialDevice) => device.port === p) ? p : ''));
      setStatus(await b.json());
      setError('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Backend connection lost');
    }
  }
  useEffect(() => {
    void refresh();
    const timer = setInterval(() => {
      if (status?.connection_state !== 'STREAMING') void refresh();
    }, 2500);
    return () => clearInterval(timer);
  }, [advanced, status?.connection_state]);
  useEffect(() => {
    if (stream.status) setStatus(stream.status);
  }, [stream.status]);
  useEffect(() => {
    try { const saved = localStorage.getItem('flexmap-emg-graph-settings'); if (saved) setSettings({ ...DEFAULT_EMG_GRAPH_SETTINGS, ...JSON.parse(saved) }); } catch { /* use safe defaults */ }
  }, []);
  useEffect(() => {
    void fetch(api + '/processing/display', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify([settings.signalType, ...(settings.compareSignalType === 'off' ? [] : [settings.compareSignalType])]) });
  }, [settings.signalType, settings.compareSignalType]);
  const recent =
      status?.latest_data_age_ms != null && status.latest_data_age_ms < 2500,
    connected = status?.connection_state === 'STREAMING',
    state: LiveState =
      status?.is_mock && connected && recent
        ? 'MOCK'
        : connected && recent
          ? 'STREAMING'
          : connected
            ? 'STALE'
            : error
              ? 'ERROR'
              : status
                ? 'DISCONNECTED'
                : 'CONNECTING';
  const channels = status?.channels?.length ? status.channels : defaultChannels;
  async function connect() {
    setError('');
    const payload = {
      transport_type: mock ? 'MOCK' : 'USB_SERIAL',
      ...(mock ? { mock_scenario: scenario } : {}),
      serial_port: mock ? null : (port || status?.serial_port),
      baud_rate: 115200,
      protocol: 'CSV_CHANNELS',
      expected_sample_rate_hz: 1000,
      channels: defaultChannels,
    };
    const response = await fetch(api + '/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const body: unknown = await response.json();
    if (response.ok) setStatus(body as EmgStatus);
    else setError(emgErrorMessage(body));
  }
  async function disconnect() {
    await fetch(api + '/disconnect', { method: 'POST' });
    await refresh();
  }
  function updateSettings(next: EmgGraphSettings) {
    setSettings(next);
    localStorage.setItem('flexmap-emg-graph-settings', JSON.stringify(next));
  }
  function choose(next: SignalRepresentation) {
    updateSettings({ ...settings, signalType: next });
  }
  function clearGraph() { setPaused(false); stream.clear(); }
  return (
    <section>
      <div className='live-page-title'>
        <div>
          <nav className='breadcrumbs'>
            <Link href='/master/live'>Live Sensors</Link>
            <span>›</span>
            <strong>EMG Live</strong>
          </nav>
          <span className='eyebrow'>Live monitoring only · no recording</span>
          <h1>EMG Live</h1>
        </div>
        <LiveStatusBadge state={state} />
      </div>
      {error && (
        <div className='live-warning'>
          <strong>Backend connection lost</strong>
          <span>{error}. Trying to reconnect.</span>
          <button onClick={refresh}>Retry</button>
        </div>
      )}
      <article className='master-card emg-live-chart'>
        <div className='master-card-head'>
          <div><strong>Live waveform</strong><small>{status?.serial_port || 'No port'} � {status?.received_rate_hz ? status.received_rate_hz.toFixed(1) + ' Hz' : 'Waiting'} � {channels.length} channel{channels.length === 1 ? '' : 's'}</small></div>
          <div className='emg-live-badges'><span>{status?.is_mock ? 'MOCK DATA' : 'REAL DEVICE'}</span><LiveStatusBadge state={state} /></div>
        </div>
        <div className='emg-toolbar'>
          <label>Signal<select value={settings.signalType} onChange={event => choose(event.target.value as SignalRepresentation)}>{(['raw','filtered','rectified','rms','envelope'] as SignalRepresentation[]).map(value => <option key={value}>{value}</option>)}</select></label>
          <label>Window<select value={settings.timeWindowSec} onChange={event => updateSettings({ ...settings, timeWindowSec: Number(event.target.value) as EmgGraphSettings['timeWindowSec'] })}>{[1,2,5,10,20,30].map(value => <option key={value} value={value}>{value} s</option>)}</select></label>
          <button className='emg-setup-button' onClick={() => setSetupOpen(true)}>Graph setup</button>
        </div>
        <div className='emg-chart-stage'>
          <EmgChart samples={stream.samples} channels={channels} paused={paused} settings={settings} hardwareRange={status?.adc_bits ? [0, 2 ** status.adc_bits - 1] : undefined} />
          {!connected && <div className='emg-chart-overlay'><strong>EMG device disconnected</strong><span>{status?.latest_data_age_ms != null ? `Last data ${Math.round(status.latest_data_age_ms / 1000)} s ago` : 'Waiting for a device'}</span><button onClick={connect}>Reconnect</button></div>}
          {state === 'STALE' && <div className='emg-chart-overlay'><strong>Signal stale</strong><span>No recent valid samples</span></div>}
          {paused && <span className='emg-paused-flag'>View paused � acquisition continues</span>}
        </div>
        <div className='live-controls' aria-label='Waveform controls'>
          <button onClick={() => setPaused((value) => !value)}>
            {paused ? 'Resume view' : 'Pause view'}
          </button>
          <button onClick={clearGraph}>Clear graph</button>
          <span>Live acquisition continues when the view is paused or cleared.</span>
        </div>
      </article>
      <EmgGraphSetupDrawer open={setupOpen} settings={settings} channels={channels} onChange={updateSettings} onClose={() => setSetupOpen(false)} />
      <div className='emg-live-grid'>
        <DevicePanel
          status={status}
          devices={devices}
          port={port}
          setPort={setPort}
          mock={mock}
          setMock={setMock}
          scenario={scenario}
          setScenario={setScenario}
          connected={connected}
          connect={connect}
          disconnect={disconnect}
          refresh={refresh}
          advanced={advanced}
          setAdvanced={setAdvanced}
        />
        <EmgMetrics status={status} state={state} />
      </div>
      <p className='live-monitor-note'>
        Opening this viewer does not start EMG recording, baseline capture, a
        research session, or Dataset writes.
      </p>
    </section>
  );
}
export function DevicePanel(p: {
  status: EmgStatus | null;
  devices: EmgSerialDevice[];
  port: string;
  setPort: (x: string) => void;
  mock: boolean;
  setMock: (x: boolean) => void;
  scenario: string;
  setScenario: (x: string) => void;
  connected: boolean;
  connect: () => void;
  disconnect: () => void;
  refresh: () => void;
  advanced: boolean;
  setAdvanced: (x: boolean) => void;
}) {
  const selected = p.devices.find((device) => device.port === p.port);
  return (
    <article className='master-card setup'>
      <h2>Device</h2>
      <label className='check'>
        <input
          type='checkbox'
          checked={p.mock}
          disabled={p.connected}
          onChange={(e) => p.setMock(e.target.checked)}
        />{' '}
        Use mock data
      </label>
      {p.mock ? (
        <label>
          Mock scenario
          <select
            value={p.scenario}
            onChange={(e) => p.setScenario(e.target.value)}
          >
            <option>CLEAN_EMG_LIKE</option>
            <option>POWERLINE_50HZ</option>
            <option>FLATLINE</option>
            <option>CLIPPING</option>
          </select>
        </label>
      ) : p.devices.length ? (
        <label>
          {p.advanced ? 'Advanced serial port' : 'USB EMG device'}
          <select
            value={p.port}
            disabled={p.connected}
            onChange={(e) => p.setPort(e.target.value)}
          >
            <option value=''>No device selected</option>
            {p.devices.map((device) => (
              <option value={device.port} key={device.port}>
                {device.port} - {device.description}
                {!device.is_usb ? ' (Advanced)' : ''}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <div className='usb-empty'><strong>No USB device detected</strong><span>Plug in your EMG device using USB.</span></div>
      )}
      {!p.mock && <details><summary>Advanced serial ports</summary><label className='check'><input type='checkbox' checked={p.advanced} disabled={p.connected} onChange={(e)=>p.setAdvanced(e.target.checked)}/> Show all serial ports</label></details>}
      {selected && <details className='device-details'><summary>Device details</summary><dl className='live-metric-list'><div><dt>Port</dt><dd>{selected.port}</dd></div><div><dt>Type</dt><dd>{selected.is_usb?'USB Serial':selected.port_type.replaceAll('_',' ')}</dd></div>{selected.manufacturer&&<div><dt>Manufacturer</dt><dd>{selected.manufacturer}</dd></div>}{selected.product&&<div><dt>Product</dt><dd>{selected.product}</dd></div>}{selected.vid&&<div><dt>VID</dt><dd>{selected.vid}</dd></div>}{selected.pid&&<div><dt>PID</dt><dd>{selected.pid}</dd></div>}{selected.serial_number&&<div><dt>Serial</dt><dd>{selected.serial_number}</dd></div>}<div><dt>Status</dt><dd>{selected.is_present?'Connected to '+(selected.is_usb?'USB':'Windows'):'Unavailable'}</dd></div></dl></details>}
      <div className='review-actions horizontal'>
        <button onClick={p.refresh}>Refresh devices</button>
        {p.connected ? (
          <button className='danger' onClick={p.disconnect}>
            Disconnect
          </button>
        ) : (
          <button
            className='primary'
            disabled={!p.mock && !p.port}
            onClick={p.connect}
          >
            Connect
          </button>
        )}
      </div>
    </article>
  );
}
function EmgMetrics({
  status,
  state,
}: {
  status: EmgStatus | null;
  state: LiveState;
}) {
  return (
    <article className='master-card'>
      <div className='master-card-head'>
        <strong>Acquisition</strong>
        <LiveStatusBadge state={state} />
      </div>
      <dl className='live-metric-list'>
        <div>
          <dt>Source</dt>
          <dd>
            {status?.is_mock
              ? 'MOCK DATA'
              : status?.serial_port || 'Not connected'}
          </dd>
        </div>
        <div>
          <dt>Sample rate</dt>
          <dd>
            {status?.received_rate_hz
              ? status.received_rate_hz.toFixed(1) + ' Hz'
              : 'Waiting'}
          </dd>
        </div>
        <div>
          <dt>Channels</dt>
          <dd>{status?.channel_count ?? '--'}</dd>
        </div>
        <div>
          <dt>Latest data age</dt>
          <dd>
            {status?.latest_data_age_ms != null
              ? status.latest_data_age_ms.toFixed(1) + ' ms'
              : 'Waiting'}
          </dd>
        </div>
        <div>
          <dt>Valid samples</dt>
          <dd>{status?.valid_samples ?? '--'}</dd>
        </div>
        <div>
          <dt>Invalid packets</dt>
          <dd>{status?.invalid_packets ?? '--'}</dd>
        </div>
        <div>
          <dt>Recorder drops</dt>
          <dd>{status?.recorder_drops ?? '--'}</dd>
        </div>
        <div>
          <dt>Processing</dt>
          <dd>{status?.processing?.enabled ? 'ENABLED' : 'RAW ONLY'}</dd>
        </div>
      </dl>
    </article>
  );
}
