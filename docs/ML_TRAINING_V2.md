# FlexMap ML Training V2

## Scope

The training system creates research baselines from frozen, reviewed CV or EMG
vault recordings. Modalities are never mixed in a dataset version. Saving data
does not start training, and registered models remain experimental; this phase
does not perform clinical decisions or automatic deployment.

## Dataset admission and provenance

A recording must have a research label, pseudonymous subject ID, approved
review state, acceptable technical quality, training eligibility, non-trash
state, and readable source artifacts. Supabase recordings must also be in the
`STORED` persistence state. Synthetic/mock recordings are excluded unless a
user explicitly enables development data. A frozen manifest stores exact
membership, source/schema versions, related-trial groups, and SHA-256 artifact
hashes.

## CV Pose Kinematics V2

The pipeline reads the saved MediaPipe observations. Coordinates are normalized
image coordinates: x increases right, y increases down, and z is relative—not a
metric depth. Elbow angle is the 2-D included shoulder-elbow-wrist angle. ROM,
absolute angular velocity, bounded descriptive smoothness, trunk displacement,
shoulder-line asymmetry, landmark visibility, and usable-frame ratio are
recording-level features.

These are camera-plane estimates affected by perspective, camera placement,
occlusion, clothing, and landmark-model uncertainty. Tracking failure is a
technical-quality problem and must not be interpreted as patient impairment.

## EMG Signal Features V2

The pipeline reads saved raw ADC samples and processes each channel separately.
It applies per-channel mean removal, then computes RMS, mean absolute value,
waveform length, integrated absolute amplitude, peak-to-peak amplitude, and a
clipping indicator. Channel descriptors are aggregated only after their
identity-preserving calculation. No undocumented band-pass is applied.

Median frequency is calculated only when a positive measured sampling rate,
at least 32 samples, and non-constant signal are available. EMG amplitude is
not treated as muscle strength, stroke recovery, or clinical improvement.

## Leakage and evaluation

Splits group both subject IDs and related trials. Duplicate IDs, subject overlap,
and related-trial overlap fail split creation. Preprocessing is fitted only on
training rows. Validation and held-out test metrics are stored separately. With
insufficient subjects, an explicitly selected `DEVELOPMENT_ONLY` run reports
training-set diagnostics and labels them as such; it never calls them test
accuracy.

## Reproducibility and lifecycle

Each run records the dataset manifest hash, feature-pipeline version, model and
hyperparameters, split configuration, random seed, and Python/scikit-learn/
NumPy/platform versions. Artifacts receive SHA-256 hashes. Runs support queued,
running, completed, failed, cancelled, and interrupted states. Runs left active
by a backend restart are marked `INTERRUPTED`/failed rather than silently
reported as running forever.

## Durable hosted storage

Migration `202610190001_ml_training_v2.sql` creates additive service-role-only
metadata tables and private-bucket object policies. Provision the private
`flexmap-ml-vault` bucket through the Supabase Storage API or Dashboard before
applying the migration; current Supabase guidance treats Storage metadata as
read-only. The migration does not modify or delete CV/EMG vault data and has
intentionally not been applied.

After review and authorized migration application, configure the API service:

```text
FLEXMAP_ML_DURABLE_STORAGE_ENABLED=true
```

The existing `FLEXMAP_SUPABASE_URL` and server-only
`FLEXMAP_SUPABASE_SECRET_KEY` are reused. Never expose either server key to the
browser. Until enabled, local SQLite and local artifacts continue unchanged.
