# EMG hardware validation

FlexMap Phase 4 characterizes an EMG acquisition chain for research engineering. It does not validate electrical safety, diagnose a patient, classify muscle activation, or establish clinical suitability.

## Hardware profiles and identity

Profiles are append-only versions under `dataset_vault/emg_hardware/profiles`. A profile records configured sample rate, channel count, protocol, raw representation, optional ADC/conversion facts, optional mains environment, and optional USB VID, PID, and device serial number. Unknown values remain null. COM is a transport endpoint and may change; it is not device identity. A likely VID/PID/serial match still requires explicit user connection.

New recordings may reference `hardware_profile_id`. `metadata.json` then stores the version and a complete snapshot, so later profile versions cannot reinterpret old data. Legacy recordings remain `LEGACY / UNSPECIFIED` unless a Master explicitly assigns a profile; assignment is audited and never changes `emg_raw.csv`.

## Timing clocks

The timing chain is: ADC/device clock → optional device timestamp and sequence → serial transport → host monotonic timestamp. These clocks are never merged. Reports name `sampling_clock_source`, preserve configured, device-estimated, and host-received rates separately, and calculate p50/p95/p99/max intervals. Device timestamps are checked for duplicates, non-monotonic values, and large jumps. Sequence IDs are checked for gaps, duplicates, out-of-order packets, and configured rollover. Host sequence only identifies successfully parsed samples and cannot prove pre-ingestion continuity. Drift is null if units are unknown or a capture is shorter than 30 seconds.

## ADC and physical units

Profiles support unsigned counts, signed counts, device-reported millivolts/microvolts, and custom representations. Range validation reports observed min/max, mean, median, standard deviation, clipping ratio, unique values, and range use. Out-of-range values are flagged and never clamped.

Derived input voltage requires ADC reference voltage, bit depth, confirmed zero code, and frontend gain. The stored formula and configuration are provenance. ADC voltage is never mislabeled as electrode voltage. Missing configuration leaves conversion unavailable; FlexMap does not fabricate microvolts.

## Validation lab

The Master-only `/master/emg/validation` lab provides timing, ADC/range, channel, powerline, theoretical filter-response, quick-check, and report operations. Baseline repeatability compares researcher-selected Rest Baselines using mean RMS, between-trial SD, descriptive CV (null near zero), and raw-offset variability. Channel states are `SIGNAL PRESENT`, `POSSIBLE FLATLINE`, `CLIPPING`, `HIGH INTERFERENCE`, or `UNKNOWN`; waveform analysis cannot verify electrode anatomy.

Powerline validation compares raw energy with a 50/60 Hz notch result without changing raw data. Filter response uses SciPy coefficients, reports Nyquist status, and does not claim a single constant IIR delay. Host pipeline latency starts at Python ingestion and excludes ADC/device/USB buffering.

Reports are historical JSON artifacts under `dataset_vault/emg_hardware/validations`. A report records the exact profile version, timing, range, unit provenance, channels, powerline, DSP metadata, host latency, warnings, limitations, and a technical—not clinical—conclusion. A newer profile version makes older reports non-current but does not delete them.

## Real hardware procedure

1. Create a profile using only confirmed hardware facts.
2. Connect appropriately designed, isolated, supervised human-connected hardware; software cannot provide electrical isolation.
3. Verify COM plus available VID/PID/serial identity and explicitly connect.
4. Run a 60-second timing validation, then a 5-minute continuity validation.
5. Run ADC/range validation without deliberately exceeding safe hardware inputs.
6. Capture three Rest Baselines with the same setup and compare them.
7. Run every configured channel check and inspect powerline behavior.
8. Review the theoretical filter response and Nyquist status.
9. Generate and retain a hardware validation report.
10. Perform a short supervised research recording and review its profile snapshot and raw hash.

Battery power, Bluetooth, or USB transport alone does not establish medical electrical safety. Do not connect an uncertified prototype to a person based on software results.

## Known limitations

Host timestamps include operating-system and transport scheduling. Live validation uses the bounded display buffers; long formal captures should be recorded and analyzed offline. Engineering thresholds require deliberate researcher review and are not automatically optimized. Phase 4 contains no activation, MVC, co-activation, fatigue, AI, CV fusion, clinical scoring, or stimulation control.
