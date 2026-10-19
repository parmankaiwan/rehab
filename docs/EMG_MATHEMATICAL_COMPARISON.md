# EMG Mathematical Comparison

The Master route `/master/ml/emg-comparison` is a development-only research workspace for inspecting spatial EMG aggregation and running controlled model comparisons.

## Mathematical contract

- Arithmetic mean uses equal channel weights.
- Gauss-Legendre quadrature supports orders 2–5. The primary three-channel average uses nodes `−sqrt(3/5), 0, +sqrt(3/5)` and normalized weights `5/18, 4/9, 5/18`.
- Learned weights use a nonnegative simplex grid selected with an inner holdout containing only outer-training subjects.
- Raw multichannel concatenates per-channel features. It has a larger information budget and is disclosed as a baseline, not a matched aggregation comparison.
- Accuracy metrics appear only when a dense synthetic reference exists. Real recordings without reference truth must not claim integration accuracy.

Real spatial quadrature is blocked unless a recording contains at least three simultaneous synchronized channels and validated physical positions matching the chosen nodes. The commissioned one-channel ESP32 system is therefore not eligible for real spatial GQ.

## Models and evaluation

Logistic regression, random forest, SVM, and scikit-learn MLP run in the current worker. PyTorch definitions exist for 1D CNN, TCN, GRU, and CNN-GRU, but cards remain disabled when PyTorch, an eligible temporal dataset, or the deep-training worker is unavailable. Transformer stays disabled until data volume and compute justify it.

All enabled models in an experiment share generated samples, a subject split, seed, and method-specific representation. Ranking uses validation macro F1. The held-out test set is reported separately and is not used to select the winner. Synthetic results are always `DEVELOPMENT_ONLY` and make no clinical claim.

## Persistence and export

Local metadata is stored in the existing FlexMap SQLite database and artifacts under `data/ml/emg-comparisons/<experiment-id>`.

The additive, unapplied migration `202610190001_ml_training_v2.sql` adds the private comparison table and uses the private `flexmap-ml-vault` bucket. Cloud mirroring remains gated by `FLEXMAP_ML_DURABLE_STORAGE_ENABLED=true`; do not enable it before reviewing and applying the migration.

Exports include JSON, CSV, and an ISEF-style ZIP summary. Private participant media is excluded.
