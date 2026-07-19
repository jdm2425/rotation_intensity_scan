# `docs/ARCHITECTURE.md`

```markdown
# Architecture

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
* Access to the waveplate, sample stage, shutter, and spectrometer.

It should not own scientific analysis.

## Acquisition layer

The acquisition layer coordinates the actions needed to obtain one spectrum safely.

Its responsibilities may include:

* Ensuring the spectrometer is configured.
* Opening the shutter when required.
* Waiting for optical settling.
* Acquiring a `Spectrum`.
* Closing the shutter in a `finally` block.
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
    power_rms_mw=...,                   # meter-reported RMS
    power_measurement_duration_s=...,
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
for achieved power. `power_rms_mw` stores the RMS statistic reported by the
meter over `power_measurement_duration_s`; it is not defined as standard
deviation unless a future verified hardware integration explicitly establishes
that convention.

These optional fields make the model ready for a power meter, but the current
hardware and experiment layers do not construct, connect, sample, or calibrate
one. `RotationIntensityExperiment` currently leaves all power fields unset.

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

Relevant components may include:

* `experiments/rotation_intensity_scan.py`
* `experiments/scan_runner.py`
* `experiments/experiment_controller.py`

### Rotation-intensity experiment

The experiment should:

* Generate or accept the scan points.
* Move stages to each requested position.
* Wait for blocking motion to complete.
* Request a spectrum through the acquisition layer.
* Construct a `Measurement`.
* Compute basic measurement statistics.
* Return or yield completed measurements.

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

The current format version is `4`, recorded as `format_version` in
`metadata.json`. The CSV index includes a `measurement_metadata` field holding
a JSON object for per-measurement analysis and correction provenance. Loaders
treat the absent field in older datasets as an empty dictionary.

Version 4 adds optional `target_power_mw`, `power_rms_mw`, and
`power_measurement_duration_s` columns while retaining `power_mw` as achieved
mean power. The loader treats any of these columns as absent/`None` for older
datasets. This is a persistence schema capability, not evidence that a power
meter was connected during acquisition.

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

The analysis recipe format is version 2. It records the ordered correction
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
