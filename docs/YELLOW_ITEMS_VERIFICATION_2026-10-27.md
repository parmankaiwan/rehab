# FlexMap yellow-item verification — 27 October 2026

Branch: `feature/dual-dataset-vaults`. Existing uncommitted work preserved.
No Git push, deployment, schema migration, firmware flash, or source-recording
overwrite performed. The existing inactive `flexmapv` project was resumed.

## Current results

| Previously yellow item | Evidence and result | Remaining limit |
|---|---|---|
| EMG processing | PASS for signed-value, rectification, analytical RMS, unit-scaling and nonfinite-input software tests. PASS against 1,004 real USB samples in memory; raw preserved, rectification and RMS match independent NumPy calculations. | Exact sensor model, raw/envelope output type, gain, voltage conversion and calibration NOT VERIFIED. No raw-EMG bandpass suitability claim. |
| EMG recording and review | PASS for automated local recorder/reprocessing tests and real Supabase synthetic save/retrieve/relabel/reject/approve/trash/restore. | A newly saved physical-board bench recording has NOT been made: awaiting confirmation of disconnected electrodes and bench-test authorization. No fabricated consent. |
| Browser CV | PASS for real integrated-camera capture at 1280×720, MediaPipe GPU initialization and actual pose inference; zero browser page errors. | Observed tracking was POOR in the test view, not a calibrated/clinical posture validation or steady-state performance benchmark. |
| Independent Dataset Vaults | PASS against actual Supabase: separate datasets/labels/artifacts, review state, audit rows, training eligibility, trash/restore and cross-modality lookup denial. Actual browser opened the synthetic CV image and rendered the saved three-point EMG waveform. | Synthetic fixtures are not human research or a physical-board recording. |
| Supabase connection/persistence | PASS: ACTIVE_HEALTHY, READY, CURRENT schema, CV_PRIVATE_EMG_PRIVATE. Two independently initialized API processes with empty local vaults retrieved identical artifact/waveform hashes; unauthenticated requests blocked. | Availability still depends on the hosted project remaining active. |

## Fixes made during verification

- Reject nonfinite DSP configuration/sample inputs before contaminating filter
  state. Avoid repeatedly constructing unused channel processors.
- Release camera tracks/model resources on model-start failure and after
  initialization finishes following unmount. Regression tests cover both.
- Distinguish a functioning camera awaiting a person from an unavailable camera.
  Display actual model delegate and inference-result count.
- Provide actionable permission, contention and missing-device diagnostics.
- Stop only verified orphaned FlexMap CV processes that were retaining camera
  ownership. Preserve the running frontend/backend and physical EMG stream.
- Restart the verified idle API with existing private authentication and working
  cloud network access; no credentials printed or modified.
- Strengthen real-cloud acceptance with project guard, explicit rejection and
  relabeling, separate API processes, Windows cleanup, and fixture exclusion.

## Test outcomes

- Backend: **259 passed**, three existing deprecation warnings.
- Frontend: **99 passed** across 35 files.
- TypeScript: PASS.
- ESLint: zero errors; three existing Next.js image warnings.
- Isolated Next.js production build: PASS. Only its generated build directory
  was removed afterward; automatic type-config changes were restored.
- Live EMG browser: PASS, physical COM9, one channel, approximately 1,000 Hz,
  zero invalid packets; actual WebSocket samples and painted canvas verified.
- Live processing: PASS, read-only numeric verification; no waveform saved.
- Real-cloud fixture acceptance and saved-vault browser checks: PASS.
- Real browser camera/MediaPipe: PASS; no fake media or saved frames.
- Seventeen authenticated Master pages: HTTP 200, no page errors or failed
  Master API requests (`data/runtime/master-pages/verification.json`).

Follow-up fixes: capability discovery returns a normal unavailable capability
instead of repeated HTTP 409s in independent mode; rejected shutdown requests
cannot interrupt recordings; independent-mode status shows actual EMG streaming;
cloud readiness is no longer inferred from free local disk space. Serial and
remote-agent ingestion reject nonfinite values/timestamps and mismatched channel
counts without clamping valid signed samples. Regression tests cover these cases.

## Evidence (local, ignored runtime files)

- `data/runtime/real-vault-verification/0ea524edb5.json`
- `data/runtime/real-vault-verification/0ea524edb5.ui.json`
- `data/runtime/live-emg-display/verification.json`
- `data/runtime/live-emg-processing/verification.json`
- `data/runtime/browser-cv-live/verification.json`

Final synthetic fixture IDs:
CV `SMP-455dc1cc4442422b9986055adb727266`;
EMG `EMG-SYNTHETIC-0ea524edb5`.
Each has six persisted review audit entries. Test fixtures are excluded from
human-research training; one fixture left eligible by an interrupted test was
explicitly removed from eligibility. Existing research records were untouched.

CV artifact SHA-256:
`431ced6916a2a21a156e38701afe55bbd7f88969fbbfc56d7fe099d47f265460`.
Saved waveform response SHA-256:
`16693085660e090c64c7e7697cb33725e5589079afb989a7d0bb7baf98ff921c`.

## Completion boundary

Do not mark the full yellow-item objective complete until the physical sensor
specification/calibration and authorized physical-board save/reopen checks are
resolved. Software and synthetic-cloud verification do not substitute for these.
