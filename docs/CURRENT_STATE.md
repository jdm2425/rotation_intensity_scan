# `docs/CURRENT_STATE.md`

```markdown
# Current State

Last reviewed: 19 July 2026

Update this file whenever a feature is verified, abandoned, or materially redesigned.

## Verified working

### Rotation stages

- Two Thorlabs PRM1-Z8 rotation stages have been connected successfully.
- Waveplate stage serial: `27268875`.
- Sample stage serial: `27268870`.
- Basic movement tests have worked.
- Blocking motion behaviour is used by the high-level experiment code.

### Beam shutter

- The Thorlabs shutter has been controlled successfully.
- Shutter serial: `37008491`.
- Verified mapping:
  - State `0` = open.
  - State `1` = closed.
- The driver exposes meaningful open/close behaviour.

### Spectrometer

- Ocean Insight Ocean SR acquisition works.
- Spectrometer serial: `SR600415`.
- seabreeze with the `pyseabreeze` backend is used.
- The spectrometer driver returns a `Spectrum`.

### Hardware manager

- The hardware manager has connected the configured devices successfully.
- It owns:
  - Waveplate stage.
  - Sample stage.
  - Shutter.
  - Spectrometer.

### Experiment execution

- The main experiment has run end-to-end with hardware.
- Stage movement, shutter control, acquisition, monitoring, plotting, and saving have been integrated.
- Live spectrum plotting during an experiment works.

### Persistence

The persistence layer has been refactored to use:

```text
Measurement
└── Spectrum
````

The following files exist or have been implemented:

* `data/data_writer.py`
* `data/data_loader.py`
* `data/experiment_dataset.py`
* `tests/test_round_trip.py`

The writer:

* Saves numeric spectrum arrays.
* Avoids Python object arrays.
* Avoids pickle.
* Writes CSV index rows.
* Saves metadata, configuration, and hardware information.
* Records saved-data format version `4`.
* Persists JSON-compatible per-measurement analysis and correction metadata.
* Saves named raw background spectra separately from signal measurements.
* Persists optional requested power, achieved mean power, meter-reported RMS,
  and power-sampling duration fields.

The loader:

* Uses `allow_pickle=False`.
* Reconstructs `Spectrum`.
* Reconstructs `Measurement`.
* Returns an `ExperimentDataset`.
* Restores per-measurement metadata.
* Loads older CSV indexes without that metadata as an empty dictionary.
* Loads older CSV indexes without the v4 power-meter columns as `None`.
* Reconstructs named `BackgroundSpectrum` records when present.
* Loads older experiments without backgrounds as an empty collection.

The hardware-free round-trip test passes:

```powershell
python -m tests.test_round_trip
```

It now verifies the complete supported spectrum and measurement fields,
experiment/config/hardware metadata, pickle-free numeric archives, provenance
metadata, and backward compatibility with metadata-free and pre-v4 CSV
indexes.

### Results directory separation

Generated experiment directories are intended to live under:

```text
results/
```

The `data/` directory is reserved for Python source code.

## Implemented but requiring hardware validation

### Live spectrometer utility

A standalone utility has been drafted at:

```text
tools/live_spectrometer.py
```

Intended features include:

* Spectrometer-only connection.
* Live spectrum plot.
* Peak display.
* Saturation warning.
* Adjustable integration time.
* Y-axis autoscaling toggle.
* Manual spectrum saving.
* Clean quit handling.

Its final behaviour should be verified against the actual `OceanSR` constructor and driver setter methods.

Do not mark it fully verified until it has been run with the real spectrometer.

## In progress or planned

### Persistent live background

Implemented directly in the live spectrometer utility using:

```text
tools/live_spectrometer_background.npz
```

Desired controls:

* `B`: capture or replace the saved background.
* `G`: toggle subtraction.
* Keep one background between sessions.
* Start with subtraction disabled unless intentionally configured otherwise.
* Scale for integration time where appropriate.
* Preserve negative corrected values.
* Calculate saturation from raw values.
* Save raw and corrected spectra distinctly.

The background calibration file should normally be excluded from Git.

### Experiment background and offline harmonic analysis

The experiment controller now acquires one shutter-closed pre-scan background
using configurable averaging and settling time. It saves the raw background in
the experiment directory before any scan-point motion.

Hardware-independent analysis now supports:

* One or multiple named harmonic wavelength windows.
* Strict optional saved-background subtraction.
* Explicit scalar or wavelength-dependent filter-transmission correction.
* Trapezoidal integration with exact requested bounds.
* Harmonic signal versus waveplate angle, measured power, fluence, or
  intensity.
* Cartesian and polar rotation dependence at a fixed value of any of those four
  input coordinates.
* Reusable `AnalysedRun`, `excitation_scan_data()`, `rotation_scan_data()`,
  `save_figure_data_csv()`, and `plot_figure_data()` APIs.
* Multi-run overlays with separate run/harmonic series.
* One complete `harmonic_signals.csv` plus exact same-stem CSV data for each
  requested PNG/PDF figure.
* A figure manifest in `analysis_recipe.json` linking every PNG, PDF, and CSV.
* An `analysis_recipe.sha256` checksum and human-readable
  `analysis_summary.md`.
* A recorded correction pipeline, software versions, source/data checksums,
  quality counts, and actionable warnings.
* Default correction annotations on quick-look figures, with
  `--no-annotate-corrections` available for clean visual output.
* CSV, recipe, summary, PNG and PDF outputs without modifying source spectra.

The data-product layer preserves repeated measurements without averaging them.
It rejects same-named harmonics with different integration windows by default.
Requesting `power_mw`, `fluence_mj_cm2`, or `intensity_w_cm2` requires real
values in the saved measurements; analysis does not infer them or silently use
waveplate angle instead.

`--no-background` and `--no-transmission-correction` now record deliberate
no-correction choices. Omitting both sides of either choice leaves its mode as
`not_specified`; saved background availability or installed-filter metadata
then produces a warning rather than silently applying a correction.

Fixed-value rotation selection records an absolute tolerance. When
`power_mw` is selected, matching uses achieved mean power, not target power.
The tolerance is present in every figure CSV and manifest record; the manifest
and summary also show the minimum and maximum achieved values that matched.
For `--plot-all`, complete target-power coverage supplies nominal automatic
centres, but the selector still matches achieved power; otherwise achieved
values supply the centres. The recipe records that automatic source.

The hardware-free analysis regressions include:

```powershell
python -m tests.test_harmonic_analysis
python -m tests.test_data_products
python -m tests.test_analysis_reporting
python -m tests.test_analysis_cli
```

The reporting regression exercises human- and machine-readable provenance.
The CLI regression creates a complete synthetic saved experiment in a
temporary directory and checks its master table, explicit/unspecified
correction modes, warnings, correction pipeline, recipe checksum, summary,
software/checksum records, figure manifest, and same-stem PNG/PDF/CSV products
without connecting hardware.

### Power-meter-ready model

The canonical measurement and persistence models now distinguish:

* `target_power_mw`: requested setpoint.
* `power_mw`: achieved mean and canonical power-analysis coordinate.
* `power_rms_mw`: RMS statistic reported by the meter over the sampling
  interval; this is not a standard deviation unless the future verified meter
  implementation defines it that way.
* `power_measurement_duration_s`: duration of the meter sampling interval.

`Measurement.achieved_power_mw` is a read-only alias for `power_mw`. These
fields propagate through `HarmonicResult`, the master harmonic CSV, and figure
CSVs.

No power-meter hardware is configured or integrated. There is no power-meter
driver, serial, hardware-manager member, experiment sampling step, or verified
waveplate-to-power calibration. Normal experiments therefore leave these fields
unset. Synthetic tests populate them only to verify persistence and analysis.

### Laboratory utilities

Planned tools include:

* Hardware status utility.
* Waveplate movement utility.
* Sample-stage movement utility.
* Safe shutter control utility.
* Saved-spectrum inspection utility.

Each tool should connect only to the device or devices it requires.

### Hardware-backed persistence test

A future test should:

1. Connect to the Ocean SR.
2. Acquire one real spectrum.
3. Save it.
4. Reload it.
5. Compare arrays and metadata.
6. Disconnect cleanly.

This test is hardware-dependent and must not run automatically.

### Further analysis extensions

The first stable harmonic-integration and plotting layer is implemented.
Remaining extensions include:

* Optional local sideband/baseline estimation.
* Replicate aggregation and uncertainty estimates.
* Publication-specific polar formatting.
* Explicit policies for invalid or saturated measurements.
* Detector-response and broader optical-system corrections.

Scalar and wavelength-dependent filter-transmission corrections are available
offline. They reject invalid/zero transmission and out-of-range curves, record
their source in the analysis recipe, and preserve raw data.

### Beam model

Not yet implemented.

Future model inputs may include:

* Waveplate angle.
* Measured power.
* Repetition rate.
* Pulse duration.
* Beam waist or spot dimensions.
* Optical transmission.

Do not populate power, fluence, or intensity with invented values.

## Known architectural rule

The canonical constructor pattern is:

```python
spectrum = Spectrum(
    wavelengths=...,
    intensities=...,
    integration_time_ms=...,
    serial=...,
    averages=...,
    dark_corrected=...,
    nonlinearity_corrected=...,
)

measurement = Measurement(
    timestamp=...,
    waveplate_angle_deg=...,
    sample_angle_deg=...,
    power_mw=...,                       # optional achieved mean
    target_power_mw=...,                # optional requested setpoint
    power_rms_mw=...,                   # optional meter-reported RMS
    power_measurement_duration_s=...,
    spectrum=spectrum,
)
```

Do not pass `integration_time_ms` directly to `Measurement`.

Do not treat `measurement.spectrum` as an array.

## Known risks

* Hardware tests can cause physical motion.
* An incorrect shutter mapping can expose the setup.
* Old saved `.npz` files may contain object arrays from the obsolete writer.
* Live background subtraction can become invalid when acquisition conditions change.
* Stage model or scale mismatches can produce incorrect units.
* OneDrive-synchronised project paths may introduce filesystem timing or locking issues.
* Standalone tools may need adjustment to match the exact current driver APIs.
* Absolute optical intensity is not yet calibrated.
* The power-ready data fields could be mistaken for an implemented power-meter
  acquisition path; no such hardware integration exists yet.

## Immediate recommended sequence

1. Run and keep green the complete hardware-free persistence/analysis suite:
   `tests.test_round_trip`, `tests.test_harmonic_analysis`,
   `tests.test_data_products`, `tests.test_analysis_reporting`, and
   `tests.test_analysis_cli`.
2. Review the v4 power-field semantics, achieved-power tolerance selection,
   correction reports, and saved checksums before introducing another data
   representation.
3. Only after those tests pass, identify and verify the actual laboratory power
   meter, interface, units, sampling/RMS semantics, and serial.
4. Design the final power-meter driver and acquisition integration without
   changing shutter or motion safety. Any connection test requires explicit
   operator approval and should begin with the smallest read-only device test.
5. Populate target/achieved/RMS/duration fields from that verified acquisition
   path, then repeat persistence and offline-analysis regressions before a full
   experiment.
6. Continue local-baseline, uncertainty, and publication-format work after the
   measurement provenance is stable.

## Codex onboarding prompt

Use this as the first prompt after opening the repository in Codex:

```text
Read AGENTS.md and every document it references.

Inspect the repository and compare the implementation with the documented
architecture and current state.

Do not modify anything yet.

Report:
1. The architecture you found.
2. Differences between documentation and code.
3. Incomplete or inconsistent files.
4. Tests that are safe without hardware.
5. Tests that could move hardware or open the shutter.
6. A proposed next-task plan.

This project controls real laboratory hardware. Do not connect to or move
hardware unless I explicitly approve it.
```

````
