# FlexMap EMG signal processing (Phase 3)

Phase 3 is integrated into the Master-only EMG subsystem on ports 3000/8000. `emg_raw.csv` remains the canonical immutable research artifact. DSP failures disable derived output and do not stop serial acquisition or raw recording.

## Pipeline

```text
raw ADC counts -> causal DC/high-pass or SOS band-pass -> optional SOS notch
               -> full-wave rectification -> rolling RMS -> optional envelope
```

Defaults (20–450 Hz band-pass, fourth order, notch off, 100 ms RMS, envelope off) are **development/engineering defaults, not clinical thresholds**. Processing requires an explicit stable sample rate; current live configuration uses the configured device rate (`DEVICE_CONFIGURED`). Cutoffs are validated against Nyquist. Filter state persists across worker batches and resets only on explicit reset or configuration application. RMS startup uses all samples currently available in the partial window; it never invents zero samples.

Derived filtered, rectified, and RMS values retain ADC-count-derived units. No voltage or microvolt conversion is made without complete hardware calibration. Signal quality is separate from acquisition timing quality and estimates clipping (only with known ADC range), flatline/near-constant channels, baseline drift, transients, and 50/60 Hz contamination. These are technical warnings, not physiological or clinical conclusions.

## Raw-priority execution

Raw acquisition and the raw recording buffer are updated before DSP work is placed on a bounded 5,000-sample processing queue. DSP runs in 256-sample state-preserving batches. If it cannot keep up, processed display work is dropped and counted; raw recording is not dropped. The processed display buffer retains 10,000 samples.

## Rest baseline

The Master workflow counts down for three seconds, records five seconds by default, and writes:

```text
rehab/<slug>/emg/baselines/BASE-.../
  emg_raw.csv
  baseline_summary.json
  signal_quality_report.json
```

The summary stores channel raw mean, RMS mean/variation, the processing configuration/hash, and raw SHA-256. A baseline may be referenced by later recording metadata. It does not generate an activation threshold, MVC normalization, or clinical interpretation.

## Reprocessing and provenance

`PROCESS RECORDING` reads an existing `emg_raw.csv` without modifying it and creates a unique run:

```text
rehab/<slug>/emg/recordings/EMG-.../
  emg_raw.csv
  metadata.json
  processing/
    PROC-.../
      emg_processed_PROC-....csv
      processing_run.json
      signal_quality_report.json
```

Each run records the source recording ID, source raw SHA-256, processing configuration/hash, pipeline version, creation time, causal method, and preferred-review flag. Multiple runs coexist. The raw hash is checked before and after processing. Existing Dataset Vault audit logging records configuration changes, baseline creation, and reprocessing.

## Real hardware procedure

1. Connect appropriate, electrically isolated EMG acquisition hardware.
2. Start backend on 127.0.0.1:8000 and frontend on localhost:3000.
3. Sign in as Master and open the intended EMG rehab module.
4. Select the COM port, channel mapping, known ADC rate, and ADC bits if known.
5. Confirm the raw signal and actual receive rate first.
6. Enable processing and choose cutoffs valid for Nyquist.
7. Confirm Raw, Filtered, Rectified, and RMS views; optionally enable one notch frequency.
8. Record a five-second Rest Baseline and inspect its raw file, summary, and quality report.
9. Save a short raw recording and create two processing runs with different RMS windows.
10. Confirm both runs exist and their `source_raw_sha256` values match the unchanged raw artifact.
11. Review technical signal warnings. Do not interpret them as strength, recovery, or diagnosis.

No activation detection, MVC, co-activation, fatigue analysis, ML, CV fusion, clinical scoring, or FES exists in this phase.