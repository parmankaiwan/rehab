# FlexMap software research verification — 2026-10-20

Branch: `feature/dual-dataset-vaults`. Baseline HEAD: `a4fd378`.
This phase's changes are local and uncommitted. Nothing pushed, merged,
deployed or applied to the live Supabase schema. Existing research recordings
were not changed. All acceptance samples are synthetic and isolated.

**SIMULATION VALIDATED / SOFTWARE VERIFIED / HARDWARE NOT TESTED /
REAL-HUMAN RESEARCH NOT VALIDATED**

## A — Mathematical research: PASS

Implemented sixteen static/dynamic function families, n=2–5, explicit domain
mapping, actual node weights, moving/expanding/contracting peaks, fourteen
separable error mechanisms and dropout diagnostics. A1 isolates weights on the
same observations; A2 compares placement strategies at equal sensor count.
Analytic polynomial averages and adaptive/grid cross-validated references have
explicit tolerances. Invalid references or lost channels suppress accuracy.

Bounded sweeps support independent noise, correlation length, peak width/location,
displacement, channel count, sample dropout and movement. Placement random search
uses TRAIN scenarios, selects finalists using VALIDATION and never consults TEST.
Dependent frames are not counted as independent trajectories.

Files: `backend/emg_research.py`, `backend/emg_research_exports.py`,
`backend/emg_comparison.py`, `web/components/master/EmgResearchStudies.tsx`,
the dashboard integration and proxy SVG-download regression.

Acceptance experiment: `EMGR-70858d338efc4112aecbf1c04c06cec7`.
All sixteen families × three widths × two independent trials = 96 TEST trajectories.
Configuration: 3 sensors, 24 frames, root seed 821, default envelope errors zero,
widths 0.08/0.25/0.5. All references valid. Runtime including allocation tracing:
25.095 seconds; this is not a hardware performance measurement.

| Width | Equal-mean RMSE | GQ RMSE | Independent test trajectories |
|---|---:|---:|---:|
| 0.08 | 0.062778 | 0.076504 | 32 |
| 0.25 | 0.066669 | 0.087426 | 32 |
| 0.50 | 0.038584 | 0.042355 | 32 |

Units: dimensionless processed-envelope spatial average. GQ did not outperform
equal averaging on this aggregate mixture. That is a measured result, not a
universal statement about either estimator.

Placement search used six candidates and excluded NARROW_PEAK from development.
Selected normalized mathematical coordinates:
`[-0.596681, -0.302546, 0.937282]`. Training objective 0.049668 RMSE;
validation objective 0.049692 RMSE. The search is small and does not establish
global optimality or anatomical placement guidance.

| A2 placement/compatible estimator | Mean held-out RMSE across 96 trajectories |
|---|---:|
| Gaussian nodes / GQ | 0.068762 |
| Uniform endpoints / linear interpolation + boundary extension | 0.097050 |
| Uniform midpoints / composite midpoint | 0.045712 |
| Optimized nodes / linear interpolation + boundary extension | 0.070902 |

The optimized candidate did not beat midpoint placement on the unseen mixture.
No results were revised to select the test winner retrospectively.

Visualizations: spatial field heatmap, electrode coordinates/weights, reference
versus estimates, error curve and selectable sweep sensitivity. Plot tooltips,
zoom, legends and units are available. Sensor/noise/displacement sensitivities
use the corresponding saved sweep configuration.

Exports: JSON, summary CSV, signal-curves CSV, placement CSV, sweep CSV, SVG,
300-dpi PNG, methodology and SHA-256 manifest in a reproducibility ZIP.
Local acceptance files are `data/runtime/research-acceptance-b98f8f66694e/study-1.*`.

Limitations: 1-D processed-envelope model, finite simulation families, small
placement search, approximate measurement errors and exploratory trajectory
bootstrap intervals. Synthetic noise does not model complete surface-EMG physics.
No physical sensor result is inferred from these numbers.

## B — Mathematics-informed learning: PASS

Implemented a differentiable softmax spatial layer with nonnegative weights
summing to one. Variants: FIXED_EQUAL, FIXED_GQ, LEARNED_EQUAL, LEARNED_GQ,
GQ_REGULARIZED. Raw multichannel and fixed-GQ-plus-mathematical-features ablations
are marked as expanded information inputs. Random Forest uses fixed features
and never backpropagates through the spatial layer.

Regression uses MSE against the valid spatial-average reference and fits the
layer alone, exposing integration bias. Classification uses cross-entropy with
existing MLP/CNN/TCN/GRU architectures. Classification labels describe synthetic
forward/reverse peak travel with overlapping intensity distributions. Subject
groups contain both trials and remain wholly in one partition.

Every neural variant has a matched tuning-fit budget. GQ regularization varies
lambda at fixed learning rate; other variants tune learning rate over the same
number of fits. Validation chooses hyperparameters and best epoch. Test data is
used only after selection. Regression supports held-out function families.
Classification holds out independent trajectories, not different label families.

Files: `backend/emg_spatial_learning.py`, existing `backend/emg_deep.py` reuse,
existing experiment table/router integration, research exports and dashboard.

Regression experiment: `EMGR-92e15add032f4380835b1e7ba04e8946`.
24 simulated subjects, 3 sensors, 32 frames, seeds 42 and 73, 20 epochs,
lambda candidates 0.01/0.1/1, 14 fitted comparisons including classical baselines.
Six independent held-out subjects per repeat; narrow-peak family held out.
Runtime including allocation tracing: 22.116 seconds.

| Spatial method | Mean test RMSE across two independent repeats |
|---|---:|
| Fixed equal | 0.092865 |
| Fixed GQ | 0.121861 |
| Learned equal initialization | 0.099704 |
| Learned GQ initialization | 0.101155 |
| GQ-regularized | 0.101780 |

Classification experiment: `EMGR-c944ed61980e42569a3521b6967eb332`.
Same subject count/channels/seeds, 32 frames, 8 epochs, lambda 0.1.
44 compatible comparisons trained, predicted and exported. Runtime including
allocation tracing: 17.913 seconds.

| Architecture | Fixed equal F1 | Fixed GQ F1 | Learned equal F1 | Learned GQ F1 | Regularized F1 |
|---|---:|---:|---:|---:|---:|
| MLP | 0.456876 | 0.490476 | 0.496503 | 0.490476 | 0.490476 |
| CNN | 0.540793 | 0.580952 | 0.394958 | 0.333333 | 0.333333 |
| TCN | 0.333333 | 0.333333 | 0.333333 | 0.333333 | 0.333333 |
| GRU | 0.409524 | 0.409524 | 0.409524 | 0.409524 | 0.409524 |

These are averages of two synthetic test macro-F1 values, not clinical accuracy.
Two repeats are insufficient for the configured repeat-level intervals; intervals
are suppressed. Some architectures produce weak/constant predictions at this
small training budget. No consistent advantage of GQ-informed learning is claimed.

Real PyTorch gradient updates, weight constraints, regularization, paired splits,
validation-only tuning, exact checkpoint prediction reload and fixed-feature
Random Forest checkpoint reload were verified. Training-size curves and bounded
noise/sensor-count/displacement grids are supported and covered by regressions.

Dashboard: loss curves, weight evolution, spatial bars/points, differences from
GQ, validation regularization sensitivity, data-efficiency/robustness view,
separate validation/test metrics and exact saved configuration.

Exports: model files, parameter counts/bytes, weights CSV, prediction CSV,
training-history CSV, validation-tuning CSV, scenario manifest, JSON, SVG,
300-dpi PNG and reproducibility ZIP. Local files: same acceptance directory,
`study-2.*` (regression) and `study-3.*` (classification).

Limitations: synthetic labels, small training runs, global fixed-position weights,
one-dimensional geometry. Weight magnitude is not physiological importance.
Classification scores do not establish integration accuracy. Python allocation
tracing excludes native tensor memory and is explicitly labelled as such.

## C — Multichannel software readiness: PASS; hardware: NOT TESTED

Implemented a versioned JSON-lines contract and isolated TEST_DEVICE generator
for 1/2/3/4 channels. Channel identity, calibration configuration, ADC resolution,
reference voltage, units, physical/normalized coordinates, firmware, sequence
counter, device timestamps, missing flags and synchronization metadata are typed.
Existing serial protocol support is preserved.

Fault coverage: dropped/reordered/duplicate packets, mismatch, timestamp drift,
jitter, saturation, invalid numbers and disconnect/reconnect. Reports include
accepted samples, sequence gaps, rejected packets, delivered/clock rates and
timing residuals. Unknown physical skew stays null.

Files: `backend/emg/research_protocol.py`, authenticated test-device routes,
dashboard waveform and `docs/EMG_PROTOCOL_V2.md`.

Acceptance: 3 channels × 200 samples; saved metadata matched; all 200 samples
were retrieved after actual backend restart; SHA-256 remained identical. Test
recordings are stored only under `data/ml/emg-comparisons/TEST-*`, outside real
participant Vaults. The test harness never opens USB or starts human acquisition.

Physical connection, firmware flash, timing simultaneity, interchannel skew,
electrical isolation, gain/offset calibration, real noise, reference agreement
and all human studies remain **NOT TESTED — PHYSICAL HARDWARE REQUIRED**.
The JSON V2 harness is prepared for future integration; an enabled physical V2
serial driver is intentionally not claimed.

## Final acceptance evidence

| Check | Status | Evidence |
|---|---|---|
| Full backend pytest | PASS | 244 passed; 3 existing deprecation warnings |
| Full frontend tests | PASS | 89 passed across 31 files |
| TypeScript | PASS | `tsc --noEmit` |
| Lint | PASS | zero errors; 3 existing image-optimization warnings |
| Production build | PASS | isolated `.next-research-build`; development `.next` untouched |
| Mathematical reference/sweeps/holdout | PASS | unit and real process-worker HTTP acceptance |
| Four neural architectures / five weight variants | PASS | actual training, predictions, model artifacts |
| Expanded-input and robustness grids | PASS | matched-condition tests, independent grouping |
| Authenticated browser | PASS | real Chromium; A curves/heatmap, B weights/loss, C waveform |
| SVG/PNG downloads | PASS | authenticated proxy HTTP 200 |
| Restart recovery | PASS | three completed results reopened byte-for-byte equivalent |
| Unauthorized access | PASS | protected endpoints returned 403 |
| Physical / human validation | NOT TESTED | software-only scope |
| Live deployment / cloud migration | NOT TESTED | neither requested nor performed |

The isolated production build directory was removed after verification. Generated
TypeScript references were restored. Test-owned servers are stopped at handoff.
Real hardware agents and real participant data were not used.

Raw final evidence: `data/runtime/research-acceptance-b98f8f66694e/acceptance.json`.
Browser evidence: `data/runtime/browser-research/browser-report.json` and
`research-dashboard.png`. All these generated test artifacts remain ignored by Git.

Reproduce with the project Python environment:

```powershell
& '..\CV part\.venv\Scripts\python.exe' -m pytest -q -p no:cacheprovider
& '..\CV part\.venv\Scripts\python.exe' scripts/verify_emg_research_v2.py
cd web
npm test -- --run
npm run typecheck
npm run lint
```

The acceptance command requires unused localhost port 8001 and stops only its
own spawned backend tree. Browser acceptance uses an installed Playwright Core
module and Chromium, the local Master credential and localhost port 3000.
