# FlexMap multichannel protocol V2 — software specification

Status: SOFTWARE VERIFIED / HARDWARE NOT TESTED / REAL-HUMAN RESEARCH NOT VALIDATED.
The existing VALUE_ONLY, TIMESTAMP_VALUE, CSV_CHANNELS,
TIMESTAMP_CSV_CHANNELS and SEQUENCE_TIMESTAMP_CSV protocols remain supported.
V2 is an additional JSON-lines test harness, not an enabled serial firmware driver.

## Packet contract

One UTF-8 JSON object per newline, maximum four independent channels:

```json
{"protocol_version":"FLEXMAP_EMG_V2","source_type":"TEST_DEVICE","device_id":"TEST-DEVICE","firmware_version":"SIMULATOR-2.0","sequence":120,"timestamp_us":120000,"channel_ids":["channel_1","channel_2","channel_3"],"values":[2048,2050,2052],"missing":[false,false,false],"clock":"SHARED_SAMPLE_COUNTER","interchannel_skew_us":null}
```

`sequence` is a nonnegative sample counter; `timestamp_us` is a monotonic device
clock in microseconds. Samples with repeated or decreasing sequence numbers are
counted and rejected. Forward gaps are counted. Do not reorder late samples and
claim their host arrival order is acquisition order. The harness has no counter
wrap support: a real driver must declare counter width and reboot/session ID.

Channel metadata declares unique ID, ADC bit depth, voltage reference, gain,
offset, units, physical coordinate in millimetres and normalized coordinate.
Missing samples have a Boolean indicator. Present values must be finite numbers.
Calibration metadata is a configuration, not proof of physical calibration.

Conversion, when calibrated: voltage = count/(2^bits−1) × reference_voltage;
corrected_voltage = (voltage − offset)/gain. For raw electrical recordings,
rectification/RMS/envelope processing must precede the envelope spatial study.
Do not integrate arbitrary unsigned ADC offsets as physiological activity.

## Timing and diagnostics

The delivered sample rate is accepted rows per elapsed device-clock duration.
The clock rate uses sequence-span per device-clock duration, so packet loss and
clock drift can be distinguished. Jitter is standard deviation of
`delta_timestamp_us − delta_sequence × expected_period_us`.
Host receive times alone do not establish simultaneous sampling. Interchannel
skew stays null until measured. A multiplexed ESP32 ADC requires a measured scan
schedule or external simultaneous ADC; no hardware guarantee is assumed here.

## Isolation and fault harness

Master-authenticated `POST /api/master/ml/emg-comparison/research/test-device`
accepts 1–4 channels. Faults: dropped, out-of-order, duplicate sequence,
channel mismatch, 2% clock drift, timing jitter, saturation, invalid numeric
values and disconnect/reconnect. All observations are TEST_DEVICE. Files are
written only under `data/ml/emg-comparisons/TEST-*`, never participant Vaults.
The authenticated GET by test-recording ID verifies the saved checksum and
reopens the saved waveform. The harness never opens USB or posts to the real
engine-ingestion endpoint.

## Future commissioning requirements

Every physical item below remains **NOT TESTED — PHYSICAL HARDWARE REQUIRED**:

1. Device/firmware identity and physical channel count.
2. ADC input limits, isolated electrical design and approved power topology.
3. Shared-clock timing, effective rate, drift and measured interchannel skew.
4. Sequence continuity, packet loss and physical disconnect/reconnect.
5. Per-channel gain/offset against a calibrated bench reference.
6. Baseline noise, channel dropout, saturation and crosstalk.
7. Electrode coordinate and channel-map verification.
8. Bench recording, checksum verification and restart retrieval.
9. Higher-density reference agreement where available.
10. Electrical-safety review and research authorization before human connection.

The harness accepts declared TEST identities only. A production V2 driver must
be implemented and commissioned separately before accepting physical devices.
