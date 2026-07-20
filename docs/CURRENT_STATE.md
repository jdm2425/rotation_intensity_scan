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

- The hardware manager has connected the original rotation/shutter/spectrometer
  stack successfully.
- It owns:
  - Waveplate stage.
  - Sample stage.
  - Shutter.
  - Spectrometer.
  - PI power-meter insertion stage whenever it is marked installed.
  - Ophir meter when incident-power acquisition is enabled.
  - Retractable power-probe coordinator.
- The individual PI and Ophir devices are live-verified. Candidate probe
  positions `in=+1.0 mm` and `out=-1.0 mm` are present in configuration, but
  this handoff does not independently verify that they are physically correct.

### Ophir power meter

- Live identity was verified for Juno serial `3144168`, ROM `JN1.53`, with
  3A-P-V1 thermopile sensor serial `3141552` on channel 0.
- `Power` mode and returned wavelength options `<800`/`>800` were verified.
- Returned ranges were `AUTO`, `3.00W`, `300mW`, `30.0mW`, `3.00mW`, and
  `300uW`.
- A 10 s shutter-closed trace using `>800` and `30.0mW` returned 138 valid and
  zero invalid samples: mean 0.0594928 mW, population STD 0.00219435 mW, and
  absolute RMS 0.0595332 mW.
- This trace is a dark/offset observation only. No automatic zero/background
  subtraction was introduced.

### PI insertion stage

- After terminating a hidden PIMikroMove process, PIPython connected to the
  exact C-891.120200 controller, serial `118054611`, firmware `02.012`.
- Axis 1 and live stage assignment V-408.132020 were verified.
- The axis was already referenced (`FRF? = true`); no home/reference command
  was sent.
- Live controller limits were -12.5 to +12.5 mm, intersected with the configured
  -12 to +12 mm application envelope.
- The motor was enabled, the servo initially disabled, and initial live
  velocity was 200 mm/s.
- With the shutter verified closed, the servo was enabled safely and a single
  +0.100 mm move and exact return were completed within 0.01 mm tolerance. The
  shutter began and ended closed.
- Startup now treats the configured 1 mm/s as a maximum: it lowers a faster
  live value and verifies readback, but retains an already slower value.
- `hardware/config.py` currently contains `in_position_mm=+1.0` and
  `out_position_mm=-1.0`. These must be confirmed physically with the standalone
  PI/probe test before relying on automatic insertion or sample-beam clearance.

### Experiment execution

- The main experiment has run end-to-end with hardware.
- Stage movement, shutter control, acquisition, monitoring, plotting, and saving have been integrated.
- Live spectrum plotting during an experiment works.
- The maintained entry point is `run_rotation_intensity.py`;
  `run_rotation_intensity_scan.py` is a compatibility wrapper which delegates
  to it.
- Scan order is now waveplate/intensity outermost and sample angle innermost.
- The implemented default is one incident-power trace per waveplate setting,
  reused across its complete sample-angle block. `per_measurement` and
  `disabled` cadences are also implemented.
- Power acquisition is disabled in the default `ExperimentConfig` pending
  physical in/out-position calibration.

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
* Records saved-data format version `5`.
* Persists JSON-compatible per-measurement analysis and correction metadata.
* Saves named raw background spectra separately from signal measurements.
* Persists requested power, achieved arithmetic mean, population STD, absolute
  RMS, duration, attempt/trace IDs, status/error, and valid/total counts.
* Saves every power attempt immediately in `power_attempts.json`, before its
  associated spectrum acquisition.
* Stores each unique raw trace once under `power_measurements/`, indexed by
  `power_measurements.json`, with no object arrays or pickle.
* Validates saved summary fields against raw trace statistics and enforces
  attempt/trace referential integrity.

The loader:

* Uses `allow_pickle=False`.
* Reconstructs `Spectrum`.
* Reconstructs `Measurement`.
* Returns an `ExperimentDataset`.
* Restores per-measurement metadata.
* Loads older CSV indexes without that metadata as an empty dictionary.
* Loads older CSV indexes without the v4/v5 power-meter columns as `None`.
* Reconstructs named `BackgroundSpectrum` records when present.
* Loads older experiments without backgrounds as an empty collection.
* Loads older experiments without power indexes as empty collections.
* Reconstructs shared `PowerTrace` references and `PowerMeasurementAttempt`
  records for format 5.

The hardware-free round-trip test passes:

```powershell
python -m tests.test_round_trip
```

It now verifies the complete supported spectrum and measurement fields,
experiment/config/hardware metadata, pickle-free numeric archives, provenance
metadata, and backward compatibility with metadata-free and pre-v4 CSV
indexes. `tests.test_power_trace_round_trip` separately verifies format-5 raw
power attempts/traces and their shared references.

### Results directory separation

Generated experiment directories are intended to live under:

```text
results/
```

The `data/` directory is reserved for Python source code.

## Standalone live utility

### Live spectrometer utility

A standalone utility is implemented at:

```text
tools/live_spectrometer.py
```

Verified/implemented features include:

* Spectrometer-only connection.
* Live spectrum plot.
* Peak display.
* Saturation warning.
* Adjustable integration time.
* Y-axis autoscaling toggle.
* Editable x/y plot limits inside the Matplotlib window; restricted-range
  autoscaling uses only the active x range.
* Manual spectrum saving.
* Clean quit handling.
* Real connection to Ocean SR serial `SR600415` has been demonstrated.
* A previously saved persistent background was loaded successfully with
  subtraction initially off.

Capture/replace (`B`) and subtraction-toggle (`G`) behaviour are implemented
and hardware-free logic is tested; recapture a background whenever detector or
optical conditions change.

## Implemented features and remaining commissioning

### Persistent live background

Implemented directly in the live spectrometer utility using:

```text
tools/live_spectrometer_background.npz
```

Controls and behaviour:

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

The experiment controller acquires one shutter-closed pre-scan background in a
normal data-saving run, using configurable averaging and settling time. Defaults
are name `pre_scan_dark`, five averages, and 0.05 s settling. It saves the raw
background before any scan-point motion. Unsaved test mode skips acquisition
because there is no dataset in which to retain it.

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

The hardware-free power and interlock regressions include:

```powershell
python -m tests.test_ophir_power_meter
python -m tests.test_pi_linear_stage
python -m tests.test_power_probe
python -m tests.test_power_trace_round_trip
python -m tests.test_power_experiment_workflow
python -m tests.test_power_safety_policy
python -m tests.test_acquisition_guard
```

`python -m tests.test_rotation_scan` is also hardware-free and verifies the
current intensity-major `ScanRunner` ordering with a fake experiment.

The complete listed hardware-free persistence, analysis, fake-driver,
interlock, scan-order, and failure-path suite passes as of this review.

The reporting regression exercises human- and machine-readable provenance.
The CLI regression creates a complete synthetic saved experiment in a
temporary directory and checks its master table, explicit/unspecified
correction modes, warnings, correction pipeline, recipe checksum, summary,
software/checksum records, figure manifest, and same-stem PNG/PDF/CSV products
without connecting hardware.

### Retractable power-meter integration

The canonical measurement and persistence models distinguish:

* `target_power_mw`: requested setpoint.
* `power_mw`: arithmetic mean of finite, positive, status-OK samples and the
  canonical power-analysis coordinate.
* `power_std_mw`: population standard deviation of those valid samples.
* `power_rms_mw`: absolute RMS, `sqrt(mean(power**2))`, of those valid samples.
* `power_measurement_duration_s`: duration of the meter sampling interval.
* Attempt/trace IDs, status/error, and valid/total raw sample counts.

`Measurement.achieved_power_mw` is a read-only alias for `power_mw`. These
fields propagate through analysis-format-3 `HarmonicResult`, the master
harmonic CSV, and figure CSVs. Analysis warnings count shared power problems by
attempt ID rather than repeating them for every sample angle. Quick analysis
also includes `ExperimentDataset.power_attempts`, so abort-only attempts and
their statuses appear in quality counts and a dedicated no-spectrum warning.

The following are implemented and covered by fake-device tests:

* Lazy, same-thread Ophir StarLab COM driver with strict controller/head serial
  checks, named setting selection, and readback verification.
* Lazy PIPython C-891 driver with identity/axis/stage checks, read-only state
  snapshots, reference-gated motor/servo enable, intersection of application
  and live limits, blocking absolute motion, final-position verification, and
  best-effort smooth halt on motion failure.
* Shutter-upstream probe sequencing, verified retraction, sample-beam guard,
  and cleanup handling.
* Immediate attempt/trace persistence before spectrum acquisition.
* Default `per_intensity` cadence with a 10 s trace after 3 s settling;
  `per_measurement` and `disabled` alternatives.
* Physical wavelength 2000 nm, returned Ophir option `>800`, fixed `30.0mW`
  range, and a 20 mW raw-sample interlock.
* Explicit `measured`, `measured_with_invalid_samples`, `invalid`, `failed`,
  `over_limit`, and `unsafe_meter_status` provenance.

Zero, negative, missing, non-finite, and status-flagged samples remain in the
raw trace and are never predicted. Failed or all-invalid reads abort by default
and otherwise continue only under an explicit missing-power opt-in. Over-limit
and unsafe-status cases always abort before acquiring a sample spectrum.

A bounded closed-loop target-power controller is implemented. It searches
only inside an operator-supplied monotonic waveplate branch and stores requested
and achieved power separately. It does not invent fluence or intensity.
Complete real integration still requires physical verification of the probe
in/out positions and a staged hardware validation of the feedback loop.

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
    power_std_mw=...,                   # optional population STD
    power_rms_mw=...,                   # optional absolute RMS
    power_measurement_duration_s=...,
    power_measurement_id=...,
    power_trace_id=...,
    power_measurement_status=...,
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
* PIMikroMove or StarLab can retain exclusive device ownership after their UI
  is closed; verify the processes have exited before Python connects.
* The supplied PI manual targets C-891.130300 rather than the exact configured
  C-891.120200 controller.
* Unset or guessed probe in/out positions can block operation or obstruct the
  sample beam. The manager refuses to start when unset, but cannot determine
  whether configured numerical positions are mechanically correct.
* A valid-looking mean must not hide one unsafe raw status or over-limit sample;
  the implemented interlocks inspect the raw trace.

## Immediate recommended sequence

1. Keep the complete hardware-free persistence, analysis, power-driver,
   interlock, and workflow suite green.
2. Use `tools.test_power_probe_hardware` to verify the configured distinct
   power-meter in/out positions, retraction, and sample-beam guard before a full
   incident-power scan.
3. Run one small power-measured intensity block, reload format-5 data, and audit
   the raw trace, attempt record, shared measurement links, background, and
   analysis-format-3 warnings.
4. Continue local-baseline, uncertainty, and publication-format work after the
   complete hardware path is verified.

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

## Target-power scan software addition (20 July 2026)

A bounded closed-loop target-power scan path has been added in software:

- `experiments/power_targeting.py`
- `run_target_power_scan.py`
- target-power support in the controller, runner, experiment, and monitor
- `tests/test_target_power_experiment_workflow.py`
- `docs/TARGET_POWER_SCAN.md`

The controller searches only inside an explicit monotonic waveplate branch,
records requested and achieved powers separately, and aborts on unbracketed
targets, invalid power, over-limit readings, or failed convergence. For each
requested power it now opens one persistent probe session: the PI stage inserts
once, every feedback trace is shutter-gated while the probe remains in place,
and the probe retracts once before any sample spectrum.

`tools/test_power_probe_hardware.py` provides separate `inspect`, `move`, and
`measure` workflows for the shutter, PI stage, and Ophir meter without
connecting the rotation stages or spectrometer. The `measure` workflow can
record multiple traces during one insertion and saves CSV/JSON output.

Hardware-free tests pass. Complete physical target-power operation remains
unverified. Resolve the disagreement between the configured `+1/-1 mm` probe
positions and the earlier documentation stating that those positions were
unset/unverified before a real scan.
