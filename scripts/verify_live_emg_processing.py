"""Read-only physical stream/DSP verification; never saves waveform samples."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import numpy as np
from dotenv import dotenv_values
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.emg.signal_processing import ChannelProcessor, EmgProcessingConfig


def main() -> None:
    token = dotenv_values(ROOT / 'web' / '.env.local').get('MASTER_INTERNAL_TOKEN')
    if not token:
        raise RuntimeError('Local Master token is missing')
    with httpx.Client(base_url='http://127.0.0.1:8000', headers={'x-flexmap-master-token': token}, timeout=10) as client:
        status = client.get('/api/master/emg/status').json()
        assert status['connection_state'] == 'STREAMING' and status['is_mock'] is False
        ticket = client.post('/api/master/emg/ws-ticket').json()['ticket']
    rows = []
    with connect(f'ws://127.0.0.1:8000/ws/emg?ticket={ticket}', open_timeout=10) as socket:
        for _ in range(100):
            value = json.loads(socket.recv(timeout=5))
            if value.get('type') == 'emg.samples':
                rows.extend(value['samples'])
            if len(rows) >= 1000:
                break
    assert len(rows) >= 1000
    config = EmgProcessingConfig(enabled=True, bandpass_enabled=False, dc_removal_enabled=False, rms_window_ms=100)
    for channel in status['channels']:
        raw = np.asarray([row['channels'][channel['internal_id']] for row in rows], dtype=float)
        assert np.isfinite(raw).all()
        output = ChannelProcessor(config).process_batch(raw.tolist())
        assert np.array_equal([item['raw'] for item in output], raw)
        assert np.array_equal([item['rectified'] for item in output], np.abs(raw))
        window = round(config.processing_sample_rate_hz * config.rms_window_ms / 1000)
        expected = [float(np.sqrt(np.mean(raw[max(0, i-window+1):i+1]**2))) for i in range(len(raw))]
        assert np.allclose([item['rms'] for item in output], expected)
    report = {'result': 'PASS', 'source': 'PHYSICAL_USB_SERIAL', 'is_mock': False,
              'channel_count': status['channel_count'], 'checked_sample_count': len(rows),
              'raw_preserved': True, 'rectification_verified': True, 'rms_verified': True,
              'saved_waveform_samples': False, 'physical_voltage_calibration': 'NOT_VERIFIED',
              'sensor_output_representation': 'NOT_VERIFIED', 'filters_applied': False}
    target = ROOT / 'data/runtime/live-emg-processing/verification.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
