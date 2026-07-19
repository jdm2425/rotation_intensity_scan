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
    power_mw=...,
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

These properties should forward to the embedded `Spectrum`; they should not create a second independent copy of the same state.

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
    ├── measurements.csv
    └── spectra/
        ├── spectrum_000001.npz
        └── ...
```

The current format version is `2`, recorded as `format_version` in
`metadata.json`. The CSV index includes a `measurement_metadata` field holding
a JSON object for per-measurement analysis and correction provenance. Loaders
treat the absent field in older datasets as an empty dictionary.

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

It should support iteration, indexing, length, and useful convenience summaries.

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

The live viewer may use a persistent background manager such as:

```text
tools/spectrum_background.py
```

with a fixed file:

```text
tools/live_spectrometer_background.npz
```

The background manager should:

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
