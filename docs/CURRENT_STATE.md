# `docs/CURRENT_STATE.md`

```markdown
# Current State

## Campaign GUI

A campaign GUI is implemented under `gui/` and launched by `run_gui.py`. It
starts in Hardware mode but performs no automatic connection. Hardware mode owns the Ocean SR, waveplate
and sample stages, and shutter; drivers are imported lazily on an
operator-requested connection. Selecting Hardware mode alone connects nothing.
Connect-all establishes and verifies shutter-closed before connecting stages.
Manual absolute stage moves close and verify the shutter before motion and are
routed through the worker alongside shutter-close. A move is reported complete
only when finite live readback is within the operator-configured tolerance
(default 0.05 degrees); otherwise
the GUI reports requested versus observed position and marks an operation error.
The interface includes a persistent safety/status header and device dashboard.
Open/close shutter controls are duplicated on Devices and Alignment. Open is
normally probe-out interlocked; when stopped, the operator can explicitly
override an unknown/not-out state through a laser-risk confirmation. Overrides
are refused during live acquisition, and live spectra require verified
probe-out. The PI stage is now connectable and supports confirmed arbitrary
absolute moves inside intersected application/live limits, always after
verified shutter closure. Settings persists probe insertion/retraction values.

An unreferenced PI axis is retained as a connected device and logged, after
which the GUI automatically offers an operator-confirmed optical-switch `FRF`
recovery. Approval closes/verifies the shutter, references and verifies the
axis, prepares closed loop, and resumes remaining connections. The sequence
enables the axis, issues and verifies `FRF`, and only then enables/verifies
closed-loop servo state; the C-891 rejects premature `SVO=True` while
unreferenced. The same action is available manually. Devices and Alignment
also provide confirmed waveplate/sample homing with shutter closure and final
near-zero readback.

Hardware GUI incident-power measurement is implemented. Ophir connects as
controller `3144168` with sensor `3141552`, returned wavelength `>800`, and
fixed range `30.0mW`. `RetractablePowerProbe` performs the verified sequence.
Raw traces are saved pickle-free under `results/power_measurements` before
acceptance; invalid/status-flagged samples or a positive raw sample above 20 mW
reject the mean. Duration, settling, and poll interval persist in Settings with
defaults 10 s, 3 s, and 0.1 s. The GUI also includes simulated manual controls,
calibration-workflow mock-up, scan
configuration and preflight, live synthetic views, cancel-at-safe-point
behavior, immediate format-5 saving, and saved-experiment summary loading.

Hardware waveplate-angle scans are implemented in the GUI. Each intensity
block closes the shutter for the verified waveplate move, acquires and persists
one guarded Ophir attempt/raw trace, retracts and verifies the probe, and then
acquires every requested sample-angle replicate through the live probe-out
guard. Backgrounds and completed measurements are saved incrementally in one
format-5 experiment directory. Cancellation is checked before intensity blocks
and spectra; cleanup leaves the shutter closed. Closed-loop target-power scans
remain blocked until the GUI exposes reviewed monotonic-branch and feedback
settings. Hardware-free fake-device coverage verifies endpoint bracketing,
convergence, persistent insertion, final retraction, format-5 trace/attempt
links, and target/achieved power reload.

The Calibration tab now executes the existing bounded waveplate-map analysis
through the GUI. It shows an estimated duration, plots points as they arrive,
uses one persistent probe insertion, saves every trace and the incremental map,
recommends a monotonic branch, writes `malus_calibration.json` plus the annotated
PNG, returns the waveplate to its starting position, and copies the result into
Scan Setup. Simulation and fake-hardware paths cover the complete workflow; no
real laser-on calibration has yet been run.
The complete Calibration workspace is inside a minimum-size-aware vertical
scroll area. Its live plot retains a 420-pixel minimum height, and the scroll
range includes the full canvas and bottom margin under fullscreen/high-DPI
layouts.

Scan Setup now uses a minimum-size-aware outer scroll area for both form and
preflight columns. Long labels and the output-path row retain usable widths,
the preflight report is independently scrollable, and the run action remains
reachable at the bottom under fullscreen/high-DPI layouts. Wheel events over
single-line inputs continue to scroll the containing page without changing
field values.

The Alignment / Live Spectrum tab continuously streams a deterministic
synthetic Ocean SR spectrum. It supports integration time, internal averages,
refresh interval, background capture/subtraction with integration-time scaling,
automatic or explicit axes, pause/resume, saturation display, and manual `.npz`
saving under `results/live_spectrometer` by default. Saved arrays and metadata
remain pickle-free. The existing physical `tools.live_spectrometer` is not
invoked by the GUI.

In Ocean SR Hardware mode, live refresh is acquisition-limited: every completed
spectrum is published immediately without an added timer delay. Integration
time, internal averaging, driver/USB transfer, and plot rendering therefore set
the achievable rate. The refresh-interval field applies only to Simulation.

The Alignment tab also embeds waveplate and sample motion, simulated
target-power setting, and simulated incident-power measurement. These commands
remain available during synthetic streaming and are processed between frames.
Power operations finish with simulated shutter closed and probe out. Button
minimum widths are derived from Qt size hints so action labels remain visible
under Windows display scaling and window resizing.

A full-screen layout audit covers all six tabs at 1920×1080 in the offscreen
widget regression. Long alignment controls are scroll-contained, forms wrap
long rows, plots enforce usable minimum geometry, and buttons/input fields use
their Qt size hints as minimums. F11 toggles full screen. Window geometry,
selected tab, and per-device simulated serial/identity text are remembered.

The Devices tab now has an aggregate connection-health lamp, per-device serial
fields and connect/disconnect buttons, connect-all and safe-disconnect actions,
and a dedicated connection/error log. A loss after complete connection turns
the lamp red; reconnecting every device restores green. These controls remain
simulation-only and do not alter `hardware/config.py`.

The complete Devices tab is contained in one vertical scroll area. The device
table retains its independent row scrolling, while the outer scroll area keeps
the connect controls, safe manual controls, and connection/error log accessible
without overlap at reduced window heights or high Windows display scaling.

A seventh Settings tab persists validated operator preferences separately from
hardware configuration. It currently exposes rotation readback tolerance and
the saturation-warning threshold, with safe-default restoration. Serial/model
assignments, shutter mapping, stage limits/velocity/timeouts/homing, PI
positions/tolerance, and Ophir range/wavelength/status/safety semantics remain
locked in reviewed project configuration.

The backend and persistence path are covered by
`python -m tests.test_gui_simulation`; fake-backed Ocean SR ownership is covered
by `python -m tests.test_gui_spectrometer_backend`. PySide6 is isolated in
`requirements-gui.txt`. Ocean SR live view has been operator-reported working;
the newly added stage/shutter GUI paths have not been hardware-validated. The
The Ophir one-shot workflow has been operator-reported working. Hardware GUI
angle scans are fake-tested but have not yet been physically commissioned;
The newly exposed calibration and target-power GUI paths have not yet been
physically commissioned.

Independent spectral replicates are supported through
`SpectrometerConfig.spectra_per_point` (default `1`). Each replicate is saved
immediately as its own `Measurement`, with its one-based index and requested
count in `measurement.metadata["replicate"]`. Offline harmonic plots retain the
raw result rows and display the arithmetic mean at each coordinate with SEM
error bars (sample standard deviation divided by the square root of the number
of spectra). This path has been verified only with hardware-free tests; no live
spectrometer or scan was run for this change.

Last reviewed: 27 August 2026

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
For `--plot-all`, recorded achieved values supply automatic power centres.
The analysis CLI defaults to achieved `power_mw` whenever every analysed row
contains recorded power; otherwise it defaults to waveplate angle.
Power-selected rotation filenames contain achieved power rather than
waveplate angle, and plot titles show achieved power plus its recorded
population standard deviation. Explicit
`--input-coordinate waveplate_angle_deg` retains angle-based output.
Quick-look figures save PNG and exact CSV data by default; PDF output is
opt-in with `--save-pdf`. Power labels and filenames default to one decimal
place and can be changed with `--power-decimal-places`; quantitative CSV/JSON
values retain full precision.

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
record multiple traces during one insertion and saves CSV/JSON output. It uses
a distinct, longer initial settling period before the first post-connection
trace (default 5 s) and the experiment-standard 3 s settling period thereafter;
all traces remain saved without clipping or substitution.

The standalone `measure` diagnostic now selects the verified Ophir `AUTO`
range by default and has no abort threshold by default. Its optional
`--maximum-power-mw` is warning-only unless paired with
`--abort-above-maximum`. This is intentionally separate from the experiment's
hard raw-sample safety ceiling, which continues to abort before spectrum
acquisition on overshoot, drift, or an unsafe meter sample.

`tools/waveplate_power_control.py` adds two operator-confirmed commissioning
workflows. `scan` moves only through explicitly supplied reviewed angles,
saves the raw traces and angle/power table, returns the waveplate to its
starting angle, and prints the largest contiguous monotonic optical branch.
It also saves `waveplate_power_map.png`, shading the recommended branch and
marking its lower and upper angular endpoints. Multiple local extrema are
supported: candidate contiguous branches are compared by measured power span,
then by point count when spans tie.

Mapping scans also save a linearised half-wave-plate Malus-law calibration.
Target-power scans can load it as an initial-guess model. Fresh endpoint
measurements vertically translate the calibration for current laser output,
and the existing bounded feedback then verifies or corrects that guess. The
calibration never replaces measured power, branch checks, or raw-power aborts.

The sample PRM1-Z8 is configured for a 25 deg/s maximum move velocity, matching
the manufacturer's stated maximum. The waveplate stage retains its controller
velocity. Connection applies and verifies the sample-stage velocity readback;
failure aborts the connection.
It does not search for mechanical end stops. `set-range` reuses the bounded
target-power controller to leave the waveplate at a power inside a requested
range. Both workflows connect only the waveplate, shutter, PI insertion stage,
and Ophir meter, and preserve the shutter/probe motion interlocks.

Hardware-free tests pass. Complete physical target-power operation remains
unverified. Resolve the disagreement between the configured `+1/-1 mm` probe
positions and the earlier documentation stating that those positions were
unset/unverified before a real scan.
