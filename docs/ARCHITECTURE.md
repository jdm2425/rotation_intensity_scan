# `docs/ARCHITECTURE.md`

```markdown
# Architecture

## Campaign GUI boundary

The `gui/` package defaults to an inert Hardware mode and also provides an
explicit Simulation mode. Qt widgets
run on the main thread; one `HardwareWorker` is moved to a dedicated `QThread`,
where it exclusively owns the backend. Immutable `GuiSnapshot` objects and
completed canonical `Measurement` objects are emitted to the GUI. Cancellation
uses a thread-safe event because a queued Qt slot cannot execute while a
blocking scan operation owns the worker event loop.

The current `SimulatedCampaignBackend` intentionally imports no live hardware
manager or device driver. Synthetic measurements use the normal
`Measurement -> Spectrum` model and `DataWriter`, exercising immediate format-5
persistence without creating a second data path.

`SpectrometerCampaignBackend` currently owns the Ocean SR, two rotation stages,
beam shutter, PI probe stage, and Ophir Juno. It lazily imports drivers after an explicit
operator connection action, so startup and mode selection do not touch
hardware. Connect-all attempts the shutter first, then independently attempts
all remaining configured devices and retains successful handles. Creating a
stage handle performs no motion; motion remains separately shutter-closed
interlocked. Angle-controlled scans use `Acquisition`, canonical `Measurement`
objects, and `DataWriter` directly from that same worker-owned device stack.
Bounded target-power scans and manual Alignment targeting reuse
`TargetPowerController`; calibration execution is available through the guarded
worker workflow. The worker refuses mode changes
while connected or busy.

The continuous alignment stream also runs on the worker thread. Since that loop
temporarily owns the Qt worker event loop, GUI interactions place small commands
(settings, background capture/toggle, and manual save) onto a thread-safe queue;
the worker processes them between acquisitions. Stop is a thread-safe event.
This design keeps thread-affine Ocean/Ophir drivers off the GUI thread.

Real manual power measurement is refused during live view and delegates the
complete sequence to `RetractablePowerProbe`. Raw traces are persisted before
statistics/safety acceptance. Simulation continues to model the same final
shutter-closed, probe-out state.

For a hardware angle scan, one `PowerMeasurementAttempt` and raw `PowerTrace`
are persisted before any spectra in each waveplate block. The trace statistics
and IDs are shared by every sample-angle replicate in that block. Spectrum
illumination passes through an immediate live probe-out guard, and `Acquisition`
closes the shutter in `finally`. Cancellation occurs only at safe boundaries;
completed measurements remain loadable.

Target-power blocks create one persistent `RetractablePowerProbe` session.
The bounded controller moves only inside the operator-entered monotonic branch,
and its callback durably saves every endpoint/candidate attempt and trace. The
session retracts before sample acquisition. An optional compatible Malus-law
file affects only the first candidate; fresh endpoints and measured feedback
remain authoritative.

Manual Alignment targeting receives the same validated branch fields in a
`TargetPowerRequest`, requires GUI confirmation, and creates its own format-5
result directory containing every power attempt and raw trace even though it
does not acquire spectra.

GUI calibration reuses the pure `scan_angles`, monotonic-branch selection,
Malus fitting, CSV, and plotting functions from `tools.waveplate_power_control`.
The backend owns only the worker-thread hardware sequence and incremental trace
persistence; the GUI receives numeric point updates and the final recommended
branch rather than device objects.

The backend publishes the active `DataWriter.experiment_directory` as soon as
the run directory exists. Live Run keeps only an in-memory presentation cache
of emitted canonical measurements: it groups by intensity coordinate and
sample angle to calculate replicate means and sample-SEM display values. This
does not alter or replace incrementally persisted raw measurements.

`ScanRequest` carries a validated `rotation_target` (`sample` or
`polarization_half_waveplate`), explicit driving wavelength, and canonical
`HarmonicWindow` definitions alongside resolved coordinate tuples. Both target
modes route to the existing second PRM1-Z8 through the legacy `sample` stage
key and preserve `sample_angle_deg` for format compatibility. Run config and
measurement metadata record the mounted object and state that the value is a
physical mount angle; no implicit HWP 2x conversion occurs. GUI range
builders are converted to inclusive tuples before the worker receives the
request, so experiment sequencing has only one coordinate representation.
Live harmonic integrals are presentation-only raw-spectrum quick looks.

Pause and stop use independent thread-safe events because the blocking scan
owns the worker event loop. Backends inspect them only at shutter-closed safe
boundaries. A stop clears pause so a paused run cannot prevent safe termination.

GUI connection state is represented per device. The aggregate health indicator
is derived from immutable snapshots rather than button state: green means every
device is connected, amber means an initial partial connection, grey means no
connection has been attempted, and red means a formerly complete connection
was lost or a connection operation failed. Editable serial/identity choices and
window geometry are stored with Qt `QSettings`; connection state itself is not
restored and the application never auto-connects.

Connect-all is a best-effort enumeration pass, ordered with the shutter first.
Each device failure is captured independently and the pass continues, retaining
every successful handle. Connecting a rotation-stage handle performs no motion;
the separate motion interlock still refuses movement without a connected,
verified-closed shutter. The worker returns a connection report containing
successes, existing handles, failures, and any PI-reference requirement. While
the pass runs, the GUI owns an immediate `connection_in_progress` state, shows
connected/required progress in the persistent header, and refuses duplicate or
queued manual actions until the final report arrives.

Operator-adjustable validation/display preferences are also held in
`QSettings` and passed to the active backend through the worker thread. They do
not mutate `hardware/config.py`. Hardware identities, interlock mappings,
travel limits, driver tolerances, and power-meter semantics remain outside this
preference layer. Operator-confirmed probe in/out targets are the deliberate
exception and remain bounded by the locked PI travel envelope.

The future real backend must preserve this boundary. Ophir connection, calls,
and cleanup must remain on the same worker thread, PI calls must retain their
existing locking rules, and GUI widgets must never call device methods directly.

## Architectural goals

The codebase separates:

- Physical device drivers.
- Coordinated hardware ownership.
- Acquisition safety.
- Experiment sequencing.
- Monitoring and plotting.
- Data representation.
- Persistence.
- Offline analysis.
- Standalone laboratory utilities.

A change in one layer should not require unnecessary changes in unrelated layers.

## High-level structure

```text
Entry point or tool
        │
        ▼
ExperimentController or standalone utility
        │
        ├── HardwareManager
        │   ├── Waveplate stage
        │   ├── Sample stage
        │   ├── Beam shutter
        │   └── Spectrometer
        │
        ├── Acquisition
        ├── Experiment or scan runner
        ├── ExperimentMonitor
        ├── PlotManager
        └── DataWriter
````

Offline loading follows:

```text
Saved experiment
        │
        ▼
DataLoader
        │
        ▼
ExperimentDataset
        │
        └── list[Measurement]
                 └── Spectrum
```

The complete hardware branch additionally includes the installed PI
power-meter insertion stage, the optionally enabled Ophir meter, and their
experiment-specific retractable-probe interlock.

## Hardware layer

The `hardware/` package owns device-specific behaviour.

Typical files include:

```text
hardware/
├── config.py
├── hardware_manager.py
└── devices/
    ├── base.py
    ├── shutter.py
    ├── rotation/
    │   ├── base.py
    │   └── rotation_stage.py
    └── spectrometer/
        ├── spectrum.py
        └── ocean_sr.py
```

### Device drivers

Device drivers should:

* Connect and disconnect one physical device.
* Translate between project units and device-library units.
* Expose clear exceptions.
* Be safe to disconnect more than once.
* Avoid implementing experiment-specific loops.
* Avoid saving experiment data.
* Avoid direct plotting.

### `HardwareManager`

`HardwareManager` owns the device instances used in a complete experiment.

It should provide:

* One place to construct configured hardware.
* Coordinated connect and disconnect.
* Hardware status information.
* Safe cleanup after partial connection failures.
* Access to the waveplate, sample stage, shutter, spectrometer, installed PI
  insertion stage, and optionally enabled Ophir meter.

The reusable drivers live in `hardware/devices/linear/pi_stage.py` and
`hardware/devices/power_meter/ophir_juno.py`.
`PIStageConfig` keeps controller identity, axis, application limits, tolerance,
and timeout outside experiment logic; `PILinearStage.from_project_config()` is
only a structural adapter, so the driver can be reused with another project's
configuration. The Ophir driver's `PowerSample`, `PowerStatistics`, and
`PowerTrace` models are vendor-independent, while its COM runtime and clocks can
be injected for hardware-free use.
`hardware/power_probe.py:RetractablePowerProbe` is the experiment-specific
optical interlock around them. One-shot acquisition closes and verifies the
shutter, inserts and verifies the probe, opens and samples, then closes and
retracts. `PowerProbeMeasurementSession` additionally supports one insertion
across several feedback traces: every trace is shutter-gated, waveplate motion
requires a verified closed shutter and in position, and context exit performs
one verified retraction. Insertion-stage motion is never commanded when
upstream shutter closure cannot be verified.

Because the configured stage is physically marked `installed=True`,
`HardwareManager` manages and retracts it even when meter sampling is disabled.
Construction fails before any connection while its in/out positions are unset.
After PI connection it applies the configured 1 mm/s maximum startup velocity
(lowering and verifying a faster live value, retaining an already slower one),
then performs reference-gated motor/servo preparation and a verified safe
retraction. It never performs reference/home motion.

It should not own scientific analysis.

## Acquisition layer

The acquisition layer coordinates the actions needed to obtain one spectrum safely.

Its responsibilities may include:

* Ensuring the spectrometer is configured.
* Opening the shutter when required.
* Waiting for optical settling.
* Acquiring a `Spectrum`.
* Closing the shutter in a `finally` block.
* Running a live power-probe-out guard immediately before every sample-beam
  opening.
* Applying close delays where necessary.
* Propagating meaningful errors.

A spectrum acquisition should return a `Spectrum`, not a `Measurement`.

The experiment layer adds stage positions and beam state to form a `Measurement`.

## Canonical spectrum model

The canonical `Spectrum` object lives under:

```text
hardware/devices/spectrometer/spectrum.py
```

It contains detector-specific data:

```python
Spectrum(
    wavelengths=...,
    intensities=...,
    integration_time_ms=...,
    serial=...,
    averages=...,
    dark_corrected=...,
    nonlinearity_corrected=...,
)
```

It may also contain a timestamp or other detector metadata.

Required invariants:

* `wavelengths` is a one-dimensional numeric array.
* `intensities` is a one-dimensional numeric array.
* Both arrays have the same shape.
* Integration time is positive.
* Averages is at least one.
* The object does not own stage angles.

## Canonical measurement model

The canonical `Measurement` object lives under:

```text
analysis/measurement.py
```

It contains experiment state associated with one spectrum:

```python
Measurement(
    timestamp=...,
    waveplate_angle_deg=...,
    sample_angle_deg=...,
    power_mw=...,                       # achieved mean power
    target_power_mw=...,                # requested setpoint
    power_std_mw=...,                   # population STD of valid samples
    power_rms_mw=...,                   # absolute sqrt(mean(power**2))
    power_measurement_duration_s=...,
    power_measurement_id=...,            # attempt ID
    power_trace_id=...,                  # raw trace ID
    power_measurement_status=...,
    power_measurement_error=...,
    power_valid_sample_count=...,
    power_total_sample_count=...,
    fluence_mj_cm2=...,
    intensity_w_cm2=...,
    spectrum=...,
    peak_counts=...,
    integrated_counts=...,
    saturated=...,
    metadata=...,
)
```

The `spectrum` field contains a `Spectrum` object.

Convenience properties may expose:

* `measurement.wavelengths_nm`
* `measurement.intensities`
* `measurement.integration_time_ms`
* `measurement.averages`
* `measurement.achieved_power_mw`

These properties should forward to the embedded `Spectrum`; they should not create a second independent copy of the same state.

`power_mw` is intentionally the canonical achieved mean power and remains the
field used by power-coordinate analysis. `achieved_power_mw` is a read-only
alias. `target_power_mw` is the requested setpoint and must not be substituted
for achieved power. The driver computes `power_mw`, `power_std_mw`, and
`power_rms_mw` from finite, positive, status-OK raw samples only. STD uses the
population denominator `N`; RMS is `sqrt(mean(power**2))` and is not an
uncertainty. Raw invalid values are retained and are never replaced.

`power_measurement_id` identifies an acquisition attempt and
`power_trace_id` identifies its raw trace. Under the default cadence, all
sample-angle spectra at one waveplate setting share both references and the
same in-memory `PowerTrace`. Failed attempts can have an attempt ID and no
trace. Target power, fluence, and intensity remain unset unless supplied by a
future verified control/calibration path.

### Historical incompatibility

Older code treated:

```python
measurement.spectrum
```

as a NumPy intensity array and passed fields such as:

```python
integration_time_ms=...
wavelengths_nm=...
```

directly to `Measurement`.

That design is obsolete.

When old code is encountered, migrate it to construct `Spectrum` first.

## Experiment layer

The experiment layer defines the scan sequence.

`run_rotation_intensity.py` is the single maintained full-experiment entry
point. `run_rotation_intensity_scan.py` is only a compatibility wrapper which
delegates to it; it does not define a second workflow.

Relevant components may include:

* `experiments/rotation_intensity_scan.py`
* `experiments/scan_runner.py`
* `experiments/experiment_controller.py`

### Rotation-intensity experiment

The experiment should:

* Generate or accept the scan points.
* Iterate waveplate settings outside the sample-angle loop.
* Move the waveplate once and, by default, acquire one incident-power trace
  for the complete sample-rotation block.
* Support explicit `per_measurement` or `disabled` power cadences.
* Move stages to each requested position and wait for blocking motion.
* Require the power probe to be out before requesting an illuminated spectrum.
* Construct a `Measurement`.
* Compute basic measurement statistics.
* Return or yield completed measurements.

A power attempt is published to the writer immediately after acquisition and
before the first associated spectrum. Normal status values are `measured`,
`measured_with_invalid_samples`, `invalid`, `failed`, `over_limit`, and
`unsafe_meter_status`. Failed and all-invalid reads abort by default; an
explicit continuation option can preserve missing power and continue only for
those recoverable cases. Over-limit or unsafe-status traces always abort before
sample acquisition.

### Target-power feedback

A target-power scan supplies requested powers instead of fixed waveplate
angles. `TargetPowerController` searches only within one operator-reviewed
monotonic waveplate interval.

For each requested power, `RotationIntensityExperiment` opens one
`PowerProbeMeasurementSession`. The session:

* closes and verifies the shutter before insertion;
* inserts and verifies the PI probe once;
* keeps the probe inserted while all feedback traces are acquired;
* begins and ends every trace with the shutter closed;
* requires a closed shutter and verified in position before each waveplate move;
* closes the shutter and retracts/verifies the probe once on context exit,
  including exceptions.

After the target is reached and the session exits, sample spectra are acquired
only through the existing live probe-out guard. Requested power, achieved mean
power, final waveplate angle, and every intermediate raw trace remain distinct
persisted quantities.

It should not know the internal `.npz` file format.

### Scan runner

The scan runner should:

* Iterate through the experiment.
* Yield completed measurements.
* Allow monitors or controllers to respond.
* Avoid owning physical device implementations.

### Experiment controller

The controller coordinates:

* Experiment execution.
* Monitoring.
* Plotting.
* Persistence.
* Safe shutdown.

It should save each completed measurement as soon as practical.
It also saves each power attempt immediately so a later spectrum failure does
not erase the power record.

## Monitoring and plotting

Monitoring and plotting consume measurements but should not own hardware.

### Monitor

The monitor may track:

* Total scan points.
* Completed points.
* Current sample angle.
* Current waveplate angle.
* Elapsed time.
* Estimated remaining time.
* Peak counts.
* Saturation warnings.
* Errors.

### Plotting

Live plots should:

* Update from `Spectrum` or `Measurement`.
* Remain responsive during the scan.
* Avoid changing acquisition data.
* Distinguish raw and corrected data clearly.
* Avoid being the only place where a correction is recorded.

Wheel input over a Matplotlib canvas inside a GUI scroll area belongs to the
page scroll area. Plot canvases must not create a wheel-input dead zone unless
an explicit plot-navigation mode is added in the future.

The GUI separates measurement receipt from dashboard rendering. Measurement
signals update the in-memory groups and progress immediately, but expensive
Matplotlib redraws are coalesced to a four-hertz maximum and the newest pending
state is rendered at scan completion. This display policy must not discard or
delay persistence of measurements. Device status badges and table rows remain
live during a scan. The table updates only changed item text/colour and enabled
states, retaining its existing editors and buttons instead of reconstructing
the widget tree.

The hardware scan checks required-device connectivity at operation boundaries.
Connection loss raises through the scan worker after incremental persistence,
then cleanup closes/verifies the shutter when possible and attempts to stop
connected motion devices. The GUI also turns a loss visible in a worker
snapshot into an immediate thread-safe cancellation request. Hardware APIs may
only reveal a cable/device failure on the next driver call; the software must
never claim a verified safe state when the shutter connection itself is lost.

When the backend is idle, a `QTimer` owned by the hardware worker thread runs a
one-second health poll. The poll uses read-only live driver queries and is never
run concurrently with a busy operation. Only changed immutable snapshots cross
to the GUI thread. A failed probe clears the stale backend handle without stage
motion or automatic reconnection; the operator log records the failure and the
normal connection-loss presentation handles the resulting snapshot.
Ocean SR presence is checked by USB re-enumeration without acquiring a frame;
Ophir Juno presence is checked with `ScanUSB` before querying the live identity.
Every `snapshot_changed` emission also updates the worker's comparison cache;
otherwise a newly disconnected snapshot could be incorrectly suppressed when
it happened to equal an older pre-connection state.

The Ocean driver imports python-seabreeze only inside an explicit connection
request. `SpectrometerConfig.backend` selects `pyseabreeze`, `cseabreeze`, or
`auto`; the `seabreeze` spelling is normalized to `cseabreeze`. Automatic mode
tries the pure-Python implementation first and the native implementation
second, recording backend-specific errors. The selected backend is retained
for read-only USB health checks and reported by `OceanSR.info()`.

Scan launch sets the GUI-owned active flag and visible activity state before
emitting work to the hardware thread. This both provides immediate operator
feedback during slow preparation and makes duplicate-start refusal independent
of delayed worker snapshots or button painting.

Standalone utilities may use their own lightweight plot loop, but reusable plotting logic should remain separable.

## Persistence layer

The `data/` package contains persistence source code:

```text
data/
├── __init__.py
├── data_writer.py
├── data_loader.py
└── experiment_dataset.py
```

Generated experimental files belong in `results/`.

### Saved experiment layout

```text
results/
└── ExperimentName_YYYYMMDD_HHMMSS/
    ├── metadata.json
    ├── config.json
    ├── hardware.json
    ├── backgrounds.json
    ├── backgrounds/
    │   └── background_000001.npz
    ├── measurements.csv
    └── spectra/
        ├── spectrum_000001.npz
        └── ...
```

Format-5 experiments with incident-power attempts additionally contain:

```text
power_attempts.json
power_measurements.json
power_measurements/
    power_000001.npz
```

The current format version is `5`, recorded as `format_version` in
`metadata.json`. The CSV index includes a `measurement_metadata` field holding
a JSON object for per-measurement analysis and correction provenance. Loaders
treat the absent field in older datasets as an empty dictionary.

Version 5 adds `power_std_mw`, attempt/trace IDs, status/error, and valid/total
sample counts while retaining the existing optional target, achieved, RMS, and
duration columns. `power_attempts.json` records each attempt independently of a
spectrum. `power_measurements.json` indexes each unique `PowerTrace`, whose raw
values, timestamps, statuses, parsed numeric fields, validity flags, invalid
reasons, and batch structure are stored as non-object arrays. A default
intensity block stores one trace once and references it from every associated
measurement.

The loader accepts older datasets with no new columns or power indexes and
restores their values as `None`/empty collections. For format 5 it validates
attempt-to-trace and measurement-to-attempt referential integrity and restores
the shared in-memory trace reference.

Named raw background spectra are stored separately under `backgrounds/` and
indexed by `backgrounds.json`. `ExperimentDataset.backgrounds` exposes them as
`BackgroundSpectrum` objects. An absent background index in an older dataset is
interpreted as an empty background collection.

### `DataWriter`

`DataWriter` should:

* Create one unique experiment directory.
* Write metadata, configuration, and hardware information.
* Save each spectrum as numerical arrays.
* Append one CSV row per completed measurement.
* Flush after each row.
* Reject measurements without a spectrum.
* Validate array dimensions and matching shapes.
* Avoid pickle and Python object arrays.
* Persist `Measurement.metadata` as JSON-compatible data.
* Persist a power attempt before any corresponding spectrum.
* Validate each measurement's summary fields against its raw trace statistics.
* Save each unique raw power trace only once and reject ID collisions.

A spectrum archive should use fields such as:

```text
wavelengths
intensities
integration_time_ms
serial
averages
dark_corrected
nonlinearity_corrected
timestamp
```

### `DataLoader`

`DataLoader` should:

1. Read experiment metadata.
2. Read each CSV row.
3. Load the referenced `.npz` file using `allow_pickle=False`.
4. Reconstruct a `Spectrum`.
5. Reconstruct a `Measurement` containing that `Spectrum`.
6. Return an `ExperimentDataset`.

Per-measurement metadata is decoded from the CSV JSON field. Missing metadata
in an older dataset is reconstructed as `{}`.

Do not enable pickle to support obsolete archives.

If an old archive contains object arrays, report that it was produced by an incompatible writer.

### `ExperimentDataset`

`ExperimentDataset` contains:

* Experiment root path.
* Experiment name.
* Creation timestamp.
* Configuration.
* Hardware information.
* General metadata.
* A list of `Measurement` objects.
* A list of named `BackgroundSpectrum` objects.
* A list of unique raw `PowerTrace` objects.
* A list of `PowerMeasurementAttempt` records, including failed attempts with
  no trace.

It should support iteration, indexing, length, and useful convenience summaries.

## Offline harmonic analysis

`analysis/harmonic_analysis.py` consumes a loaded `ExperimentDataset` and one
or more named `HarmonicWindow` definitions. It can explicitly apply a compatible
saved background and either a scalar transmission fraction or wavelength-
dependent transmission curve before trapezoidal integration.

Acquisition always preserves the full raw detector spectrum, even when a
physical filter isolates one harmonic. Selecting a single window limits only
the derived analysis output. Corrections never overwrite source measurements.

The quantitative result flow is:

```text
ExperimentDataset
        |
        v
analyse_dataset(...)
        |
        +-- harmonic_signals.csv     complete derived result table
        |
        v
AnalysedRun
        |
        +-- excitation_scan_data(...)
        +-- rotation_scan_data(...)
        |
        v
FigureData
        +-- save_figure_data_csv(...)
        `-- plot_figure_data(...)
```

`analysis/data_products.py` is the reusable selection and data-product layer.
`AnalysedRun` keeps one run's result rows together with its label, source
experiment, analysis directory, and recipe. `load_analysed_run()` reconstructs
one from a quick-analysis directory. Multiple `AnalysedRun` objects can be
passed to `excitation_scan_data()` or `rotation_scan_data()`; series are keyed
by run and harmonic so points from separate experiments are never joined into
one line.

`FigureData` is presentation-independent and contains exactly the long-form
records that will be plotted. `save_figure_data_csv()` writes those records,
including unnormalised signal, plotted value, units, correction provenance,
any normalisation factor, and the fixed-value absolute tolerance.
`plotting/harmonic_plots.py:plot_figure_data()`
renders the same object as a Cartesian or, for rotation data, polar figure.
Rendering does not aggregate replicates, discard saturated rows, or change
negative corrected signals.

Excitation selection accepts four explicit fields already present in the
canonical measurement/result model: `waveplate_angle_deg`, `power_mw`,
`fluence_mj_cm2`, and `intensity_w_cm2`. Missing power, fluence, or intensity
values cause an actionable error; there is no implicit calibration or fallback
to waveplate angle. Repeated coordinates remain separate records. Same-named
harmonics with different wavelength windows across selected runs are rejected
by default.

For `rotation_scan_data(..., fixed_field="power_mw")`, matching is against
achieved `HarmonicResult.power_mw`, not the requested target. `value_tolerance`
is an explicit non-negative absolute tolerance in mW. The requested value and
tolerance are stored in `FigureData` and every figure CSV row. Quick-analysis
manifest records additionally store the minimum and maximum achieved values
actually matched, making the selected range auditable.

When the quick CLI uses `--plot-all` with `power_mw`, complete
`target_power_mw` coverage supplies nominal automatic rotation centres. The
selector nevertheless matches each row's achieved `power_mw` using the
configured tolerance. If target coverage is incomplete, unique achieved-power
values supply the automatic centres. `analysis_recipe.json` records the centre
source separately from the selection field.

`tools/analyse_experiment.py` remains the single-run quick-analysis entry point.
Its `--input-coordinate`, `--input-value`, `--input-tolerance`, and `--signal`
flags control figure selection without changing the master calculation table.
It writes:

* `harmonic_signals.csv`, containing every derived measurement/harmonic row.
* `analysis_recipe.json`, containing correction provenance and a figure
  manifest.
* `analysis_recipe.sha256`, containing the SHA-256 of the final recipe.
* `analysis_summary.md`, containing the durable human-readable report.
* Same-stem PNG, PDF, and CSV files for every requested figure.

Each manifest entry records the PNG, PDF, and figure-data CSV paths together
with the coordinate, signal, fixed selection, absolute tolerance, actual
matched minimum/maximum, correction annotation, figure-data SHA-256, series
IDs, and row count. Analysis and plotting remain hardware-independent.

Background and transmission correction modes are explicit provenance states:
`used`, `explicitly_not_used`, or `not_specified`. `--no-background` and
`--no-transmission-correction` distinguish a deliberate no-correction analysis
from an omitted choice. If a background is available or an installed filter is
recorded while the corresponding choice is unspecified, analysis proceeds
without that correction and records an actionable warning. Metadata never
turns corrections on implicitly.

The analysis recipe format is version 3. It records the ordered correction
pipeline:

1. Raw detector data.
2. Optional saved-background subtraction.
3. Optional scalar or wavelength-dependent filter-transmission correction.
4. Harmonic-window integration with `numpy.trapezoid`.

It also records quality counts, warnings, Python/NumPy/Matplotlib versions, the
master harmonic-table checksum, source background/calibration checksums where
applicable, and the figure manifest. Each figure-data CSV has its own checksum
in that manifest. `analysis/analysis_reporting.py` builds those warnings,
correction annotations, console summary, and `analysis_summary.md`.

Analysis version 3 propagates the attempt/trace IDs, exact population STD and
absolute-RMS fields, status/error, and sample counts into every harmonic row.
Power-quality warnings are grouped by attempt ID, avoiding duplicate warning
counts when one default-cadence trace is shared across multiple sample angles.
Quick analysis also supplies `ExperimentDataset.power_attempts` to reporting,
so abort-only attempts without harmonic rows are counted, their statuses are
included, and a dedicated warning points to `power_attempts.json`. Missing or
invalid achieved power remains missing; analysis never estimates it.

`plot_figure_data()` accepts a correction annotation. The CLI supplies one by
default so quick-look figures state the displayed signal and correction
choices. `--no-annotate-corrections` disables only this visual footer; it does
not alter numerical processing or provenance outputs.

`integrated_signal` is the final window integral after all explicitly selected
corrections. `raw_integrated_signal` is the uncorrected integral, and
`background_corrected_integral` is the intermediate value before optional
transmission correction. Keeping all three in every result makes correction
choices inspectable without modifying the raw experiment.

## Standalone tools

Standalone tools live under `tools/`.

Examples include:

* Live spectrometer viewer.
* Hardware status viewer.
* Controlled stage movement utility.
* Shutter test utility.
* Saved-spectrum inspection utility.

A standalone tool should connect only to the hardware it needs.

For example, `tools/live_spectrometer.py` should not connect to either rotation stage or the beam shutter.

## Background correction architecture

The live viewer implements persistent display-background handling directly in
`tools/live_spectrometer.py`, using the fixed file:

```text
tools/live_spectrometer_background.npz
```

The live background handling should:

* Load one saved background.
* Capture and overwrite it.
* Toggle use without deleting it.
* Apply subtraction to a current spectrum.
* Scale the background for a changed integration time where appropriate.
* Validate wavelength compatibility.
* Avoid clipping negative values silently.

Saturation should be evaluated from raw detector counts, not background-subtracted values.

A saved standalone spectrum should distinguish:

* Raw intensities.
* Corrected intensities.
* Whether background subtraction was active.
* Which background file was used.

## Dependency direction

Preferred dependency direction:

```text
hardware device models
        ↓
acquisition
        ↓
experiment
        ↓
controller
        ↓
monitor / plotting / persistence
        ↓
offline loading and analysis
```

Analysis and persistence should not import the full hardware manager.

Device drivers should not import experiment controllers.

Avoid circular imports.

## Error handling

Errors should be raised at the layer that understands them and handled at the layer that can recover safely.

Examples:

* Device driver: connection or movement error.
* Acquisition: shutter or detector acquisition failure.
* Writer: invalid measurement or filesystem error.
* Loader: corrupt or missing saved data.
* Controller: coordinated cleanup and user-facing failure report.

Cleanup must not hide the original exception.

## Extension points

Planned extensions should fit into existing layers:

* Harmonic integration: analysis package.
* Transmission correction: analysis or calibration package.
* Beam power calibration: calibration or beam-model package.
* Additional scan types: experiments package.
* GUI: a new presentation layer using the same controller and data models.
* Additional spectrometers: new hardware driver returning the same `Spectrum` model.

````
