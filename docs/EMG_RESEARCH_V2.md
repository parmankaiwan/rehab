# FlexMap Studies A and B — methodology

All V2 study data is **SYNTHETIC MATHEMATICAL DATA**. Values represent a
dimensionless processed amplitude envelope. They do not model complete EMG
physics, force, neurological recovery or clinical labels.

## Study A: spatial-average error

For physical domain [a,b], u = 2(x−a)/(b−a)−1. The target is
`1/(b−a) integral_a^b A(x,t) dx = 1/2 integral_-1^1 A(u,t) du`.
Gauss–Legendre integral weights are divided by two. Polynomial exactness is
verified through degree 2n−1 for n=2..5 in the existing mathematical tests.

Static functions: constant, linear, quadratic, quartic polynomial, Gaussian,
narrow Gaussian, asymmetric Gaussian, multiple peaks and a smooth
non-polynomial function. Dynamic functions move peaks, expand/contract width,
migrate centers, vary two regions independently, vary asymmetric activation,
and change burst shape. Domains are coordinate units specified by researchers;
electrode positions use those same units and normalized positions are saved.

Analytic averages are used for polynomials. Other references use adaptive
quadrature with absolute/relative tolerance and an independently refined
trapezoid grid. Refinement stops when consecutive grids and adaptive results
agree to tolerance. Invalid references do not produce accuracy metrics.

A1 applies equal and GQ weights to the same observations at nominal Gaussian
nodes. A2 compares Gaussian, uniform, midpoint and optimized positions using
the same sensor budget. Uniform/optimized estimates integrate linear
interpolation with constant extension to the domain boundaries. Thus A2 tests
placement plus a compatible estimator, not weighting alone.

### Measurement error equations

Starting with clean envelope f(x,t): displaced nodes are x+N(0,sigma_x), bounded
to the domain. Timing perturbations are independent per sample plus per-channel
clock offsets (seconds). Crosstalk mixes nearby channels using a normalized
exponential distance kernel. Gain is multiplied by 1+N(0,sigma_g); DC offsets
are fixed independent normal deviations per channel. Additive independent
noise, common-mode noise, and spatially correlated noise are separate terms.
The correlated covariance is exp(−distance/correlation_length). Drift is a
slow sinusoid with independently drawn phase. Optional symmetric saturation
and explicit quantization follow these operations. Quantization step is
range/(2^bits−1); quantization alone does not impose a rail limit.

Measurement-error terms may produce negative observed envelopes; no implicit
rectification is applied. Saturation, if selected, is recorded explicitly.
Sample dropout is interpolated along time within its own channel. A wholly
missing channel invalidates the trajectory estimator; GQ is not renormalized
to hide it. Missing and clipping fractions are saved.

Sweeps are capped at 120 independent test trajectories. Random-search placement
optimization scores training functions, then selects from three finalists on
validation. Held-out families never enter optimization. Test trajectory seeds
use distinct hashed partition namespaces. Independent trajectories supply paired
bootstrap units; intervals are suppressed below five units.

## Study B: two separate objectives

Weights are softmax(logits): nonnegative and summing to one. Equal/GQ fixed
variants freeze logits. Learned variants initialize equally or exactly at GQ.
Regularized weights start at GQ and minimize task_loss + lambda ||w−w_GQ||².
Lambda candidates and best epoch are selected with validation data only.
All neural variants receive the same number of tuning fits. Regularized models
vary lambda at a fixed learning rate; other variants vary learning rate over
the same-sized candidate schedule. Every selected rate, lambda and candidate's
validation loss is saved. Lambda sensitivity therefore holds the rate fixed.

Integration regression minimizes MSE between the weighted envelope curve and
the known spatial-average target. It fits the spatial layer directly. Neural
temporal architectures are deliberately not labelled regression experiments:
a flexible head could hide spatial integration bias.

Classification uses cross-entropy and the existing MLP/CNN/TCN/GRU. Synthetic
labels distinguish forward versus reverse migration, with overlapping random
amplitude, width, location, burst and noise distributions. The generator
reverses one direction's trajectory. Both trials remain grouped by simulated
subject, with no subject or metadata included in model input. This is a narrow
travel-direction benchmark and does not imply human-EMG generalization.

The deterministic partition generator holds out simulated subjects. Optional
family holdout applies to regression. The raw input and GQ plus standard
deviation/maximum features carry more information and are explicitly marked
EXPANDED. Random Forest sees precomputed fixed features and never learns
PyTorch spatial logits. No standardizer is fitted across partitions.

Training sizes, seeds, sensor counts, noise and displacement can be varied.
The optional `training_sizes`, `sensor_counts`, `noise_levels`, and
`position_levels` lists produce bounded learning curves and robustness grids.
Paired repeat differences hold architecture/size/seed constant; learning-curve
sizes never count as independent repeats. Five repeats are required for an
exploratory interval; fewer repeats show descriptive differences only.

## Storage, execution and exports

Both studies reuse `emg_comparison_experiments`, authenticated routes, artifact
directories, cancellation and result lifecycle. A single child process runs
bounded research jobs with at most four queued requests. Scientific work does
not run on FastAPI request threads or the live serial-reader thread. Completed
results have no update route. A backend restart marks unfinished jobs failed;
it preserves configurations and completed results. No live migration is needed.
The existing optional cloud metadata repository can support a later rollout;
this phase stores experiments locally and does not enable cloud writes.

Exports include exact JSON, flattened CSV, 300-dpi PNG, SVG, methodology,
checkpoint files and SHA-256 manifest in a ZIP. Figures identify study, source,
test split, dataset and units. These are research packages, not evidence of
statistical significance or competition approval.

The backend records traced Python peak allocations during execution, input
tensor bytes, model parameter bytes and elapsed runtime. Python tracing excludes
native tensor allocations; it is not presented as total resident/GPU memory.
Source-content hashes are captured when the research module loads, so later
editor changes do not silently rewrite a completed run's code provenance.

The three-channel test device is described in `EMG_PROTOCOL_V2.md`.
