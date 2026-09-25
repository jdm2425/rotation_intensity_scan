# `docs/DEVELOPMENT_WORKFLOW.md`

```markdown
# Development Workflow

## Campaign GUI regression

The GUI backend has a hardware-free regression test:

```powershell
python -m tests.test_gui_simulation
python -m tests.test_gui_spectrometer_backend
python -m tests.test_gui_widgets
python -m tests.test_pi_reference_workflow
python -m tests.test_ocean_sr_health
```

The first test uses synthetic spectra and temporary-directory persistence. The
spectrometer-backend test injects a fake Ocean SR and verifies single-threaded
ownership, live acquisition, saving, and capability rejection. The widget test
uses the offscreen Qt platform and requires `requirements-gui.txt`. No test
connects hardware. Launching starts in Simulation mode; selecting Hardware is
also inert, but pressing `Connect alignment devices` attempts physical shutter,
rotation-stage, and Ocean SR connections.

The Ocean SR test injects fake implementations of the SeaBreeze API and covers
`pyseabreeze`, `cseabreeze`/`seabreeze`, and `auto` fallback. Importing the
driver and running this test do not import a vendor backend or enumerate USB.

`tests.test_gui_widgets` also iterates across all tabs at 1920×1080 and calls
the window's layout audit. It rejects clipped button labels, undersized visible
text fields, hidden connection-health indication, and unusably small plot
canvases. Persistent settings are disabled during this test so it does not read
or overwrite an operator's remembered serial choices or window geometry.
It additionally reduces the Devices tab to a 1280×650 viewport, verifies that
the outer scrollbar activates, scrolls to the bottom, and confirms the device
log becomes visible.

## Purpose

This workflow is designed for a software project that controls real laboratory hardware.

It aims to make changes:

- Reviewable.
- Reversible.
- Hardware-safe.
- Testable without devices where possible.
- Consistent across data models, persistence, and experiment code.

## Working environment

The project is currently developed on Windows.

From PowerShell in the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
````

Confirm the interpreter:

```powershell
python --version
python -c "import sys; print(sys.executable)"
```

The interpreter should resolve to the project's `.venv`.

## Git checkpoint before migration

Before allowing Codex to modify code:

```powershell
git status
git add .
git commit -m "Checkpoint before Codex migration"
```

Do not commit generated results, the virtual environment, caches, or machine-specific calibration files.

Recommended `.gitignore` entries include:

```gitignore
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/

results/
tools/live_spectrometer_background.npz

*.log
.DS_Store
Thumbs.db
```

Review whether any existing result files are already tracked before relying on `.gitignore`.

## Start every task with inspection

Before editing:

1. Read `AGENTS.md`.
2. Read relevant files under `docs/`.
3. Run `git status`.
4. Inspect the target file.
5. Search for all imports and callers.
6. Inspect related tests.
7. Identify hardware implications.
8. State which tests are safe to run.

For an interface change, search for every use of:

* Constructor calls.
* Attribute access.
* Type imports.
* Save/load logic.
* Test fixtures.
* Plotting code.
* Monitoring code.

## Task sizing

Prefer one coherent task at a time.

Good task examples:

* Update `DataLoader` and its tests for a new `Spectrum` field.
* Add background capture and toggle support to the live spectrometer.
* Add a hardware-free analysis function and tests.
* Add one standalone stage utility.

Avoid combining unrelated changes such as:

* Stage driver refactoring.
* GUI development.
* Data-format migration.
* Harmonic analysis.

unless they are required to keep one interface consistent.

## Test classification

### Level 0: static and read-only

Normally safe:

```powershell
python -m compileall .
```

Use care because importing every file can still trigger side effects in poorly structured modules.

Static inspection is preferred before broad imports.

### Level 1: hardware-free unit and integration tests

Safe when the files have been inspected:

```powershell
python -m tests.test_round_trip
```

Other safe tests should use:

* Synthetic arrays.
* Synthetic `Spectrum` objects.
* Temporary directories.
* Mocked hardware.
* Deterministic random seeds where randomness is needed.

Current hardware-free workflow regressions are:

```powershell
python -m tests.test_base
python -m tests.test_round_trip
python -m tests.test_rotation_scan
python -m tests.test_experiment_workflow
python -m tests.test_harmonic_analysis
python -m tests.test_data_products
python -m tests.test_analysis_reporting
python -m tests.test_analysis_cli
python -m tests.test_ophir_power_meter
python -m tests.test_pi_linear_stage
python -m tests.test_power_probe
python -m tests.test_power_trace_round_trip
python -m tests.test_power_experiment_workflow
python -m tests.test_power_safety_policy
python -m tests.test_acquisition_guard
```

The experiment-workflow test uses fake devices; it does not connect hardware.
The harmonic-analysis, data-product, reporting, and analysis-CLI tests use
deterministic synthetic results and temporary directories. The Ophir, PI,
power-probe, power-policy, and acquisition-guard tests inject fake devices;
their method names such as `ConnectUSB`, `MOV`, and `ScanUSB` are fake calls and
do not access vendor runtimes or laboratory hardware.

### Offline analysis workflow

Running analysis on an existing experiment is hardware-free. The quick tool
loads saved files only; it does not connect devices or modify source spectra:

```powershell
python -m tools.analyse_experiment results\Experiment_YYYYMMDD_HHMMSS --harmonic H5:390:410 --use-background --no-transmission-correction --plot-all --polar
```

Always make correction intent explicit for a final analysis:

* Use either `--use-background [NAME]` or `--no-background`.
* Use one of `--transmission-fraction`, `--transmission-curve`, or
  `--no-transmission-correction`.

If neither choice is supplied, the numerical analysis still runs without that
correction. When saved backgrounds or installed-filter metadata make the
omission relevant, the CLI emits an actionable warning and records the
`not_specified` mode in both machine- and human-readable reports. An explicit
no-correction choice is recorded as `explicitly_not_used` and is distinct from
an omission. Metadata never enables a correction automatically.

Use `--input-coordinate` to choose one of `waveplate_angle_deg`, `power_mw`,
`fluence_mj_cm2`, or `intensity_w_cm2`. Repeat `--input-value` to request
rotation plots at fixed values of that coordinate, use `--input-tolerance` to
set their absolute matching tolerance, and use `--signal` to select the derived
signal field. Calibrated coordinates must already exist in the measurements;
missing values are reported rather than inferred from waveplate angle.

For achieved-power selection, use `power_mw` and choose the tolerance in mW:

```powershell
python -m tools.analyse_experiment results\Experiment_YYYYMMDD_HHMMSS --harmonic H5:390:410 --use-background --no-transmission-correction --input-coordinate power_mw --input-value 10 --input-tolerance 0.5 --signal integrated_signal --polar
```

This matches actual achieved mean powers from 9.5 through 10.5 mW, subject to
floating-point comparison, rather than matching `target_power_mw`. The selected
tolerance is written to every figure CSV row and its manifest entry. The
manifest and `analysis_summary.md` report the actual matched minimum/maximum.
The default tolerance is `1e-6` in the selected coordinate's units; measured
power normally requires a deliberate, experimentally justified value.
With `--plot-all`, complete target-power values define the nominal automatic
centres, while the fixed-value selector still compares achieved `power_mw`
using the tolerance. If target-power coverage is incomplete, achieved values
define the centres. The recipe records the automatic source and the achieved
matched range.

Every quick-analysis directory contains:

* `harmonic_signals.csv`: complete derived result table.
* `analysis_recipe.json`: machine-readable version-3 recipe.
* `analysis_recipe.sha256`: SHA-256 of the final recipe.
* `analysis_summary.md`: durable human-readable analysis report.
* Same-stem PNG, PDF, and CSV files for each requested figure.

The recipe records the explicit correction pipeline, warnings, quality counts,
input tolerance, Python/NumPy/Matplotlib versions, the master-table checksum,
source background/calibration checksums where used, and the figure manifest.
Each manifest entry links its images to the exact long-form CSV, stores that
CSV's SHA-256, and records its tolerance and actual matched range.

Quick-look figures show a correction annotation by default. The footer states
the displayed signal plus background and transmission choices. Use
`--no-annotate-corrections` when a clean figure is needed; this changes only the
visual annotation and leaves calculations, warnings, recipe, and summary
unchanged.

For custom or publication analysis, use:

```python
from analysis.data_products import (
    excitation_scan_data,
    load_analysed_run,
    rotation_scan_data,
    save_figure_data_csv,
)
from plotting.harmonic_plots import plot_figure_data
```

Load each analysis directory with `load_analysed_run()`, combine runs with
`excitation_scan_data()` or `rotation_scan_data()`, render the returned
`FigureData` with `plot_figure_data()`, and save its exact values with
`save_figure_data_csv()`. Replicates are preserved and are not averaged
automatically. Same-name harmonics using different wavelength windows are
rejected by default.

Power-field meaning is fixed across persistence and analysis:

* `target_power_mw` is the requested setpoint.
* `power_mw` is the arithmetic mean of finite, positive, status-OK raw samples
  and the field used for power-coordinate selection.
* `power_std_mw` is their population standard deviation (denominator `N`).
* `power_rms_mw` is their absolute RMS, `sqrt(mean(power**2))`; it is not the
  uncertainty.
* `power_measurement_duration_s` is actual elapsed streaming duration.

Raw zero, negative, missing, non-finite, or status-flagged values are preserved
and excluded from statistics. Missing or invalid power is never inferred from
waveplate angle. Analysis format 3 propagates power IDs/status/counts and groups
quality warnings by attempt ID when one trace is shared across sample angles.
Reporting also consumes `ExperimentDataset.power_attempts`, counts aborting
attempts with no spectra, includes their statuses, and emits a dedicated warning
which points to `power_attempts.json`.

### Level 2: spectrometer-only

Requires explicit approval:

```powershell
python -m tools.live_spectrometer
```

This connects to the Ocean SR.

It should not move stages or open the shutter, but it is still a hardware operation.

### Level 3: shutter or stage tests

Requires explicit approval and operator supervision.

Examples:

* Open/close shutter test.
* Waveplate move.
* Sample stage move.
* PI insertion-stage connection, state query, or move.
* Ophir connection or power stream.
* Home command.
* Position scan.

Before running, report:

* Device serial.
* Start position where known.
* Target position.
* Maximum movement.
* Expected final state.
* Shutter behaviour.

Current operator-only scripts include:

```powershell
python -m tests.test_rotation_stage   # waveplate +2 deg and exact return
python -m tests.test_sample_stage     # sample +2 deg and exact return
python -m tests.test_shutter          # opens once, verifies final close
python -m tests.test_mff_api          # low-level Kinesis close diagnostic
python -m tests.test_ocean_sr         # connects and acquires one spectrum
python -m tests.test_hardware_manager # coordinated stack, motion, beam open
```

Inspect each file immediately before use. In particular,
`tests.test_hardware_manager` now includes the installed PI probe and currently
refuses to start while its in/out positions are unset. It must not be treated
as a generic regression test.

### Level 4: full experiment

Requires explicit approval and operator supervision.

Use `python run_rotation_intensity.py`. The similarly named
`run_rotation_intensity_scan.py` exists only as a compatibility wrapper and
delegates to the same maintained entry point.

A full experiment may:

* Connect all hardware.
* Move both rotation stages and the PI insertion stage.
* Open the shutter.
* Stream incident power.
* Acquire many spectra.
* Save experimental data.

Do not run a full experiment as a generic regression test.

## Hardware test protocol

For an approved hardware test:

1. Use the smallest useful motion or acquisition.
2. Confirm serial numbers.
3. Confirm stage limits.
4. Confirm the shutter begins closed.
5. Connect only required devices.
6. Print device identity after connection.
7. Perform one controlled action.
8. Return to a defined state.
9. Close the shutter.
10. Disconnect in `finally`.
11. Report exactly what happened.

Do not repeatedly retry motion automatically after an unexplained failure.

### Gate for remaining power-probe commissioning

The driver, interlock, experiment cadence, persistence, and analysis propagation
are implemented. The exact PI identity/state, reference status, live limits,
closed-loop enable, guarded 1 mm/s startup velocity, and a +0.100 mm reversible
move have been verified with the shutter closed. The remaining commissioning
still requires explicit operator approval and this order:

1. Run the complete hardware-free suite, including the fake Ophir/PI/probe and
   format-5 round-trip tests.
2. Confirm the laser is off, the shutter will begin and end closed, StarLab is
   closed, and PIMikroMove has fully exited.
3. Physically establish distinct probe in/out positions and enter them in
   `hardware/config.py`; do not infer them from the nominal travel range.
4. Verify shutter-closed insertion/retraction and the live sample-beam out guard.
5. Run one short coordinated intensity block and reload its power attempt, raw
   trace, spectra, and background before expanding the scan.

For any future PI controller revalidation, begin with read-only identity/axis/
stage, `FRF?`, `EAX?`, `SVO?`, `POS?`, `MOV?`, `ONT?`, `TMN?`, `TMX?`, and
`VEL?` queries. Do not home/reference, phase-find, load a stage database,
redefine position, or write persistent parameters. The maintained 1 mm/s
startup setting is a maximum: it lowers and verifies faster values, retains an
already slower live value, and never speeds the axis up automatically.

The supplied MS251E manual explicitly targets C-891.130300, not the configured
C-891.120200. Treat it as general GCS guidance only and rely on the correct
manual plus live readback for model-specific behaviour.

## Data-model change protocol

The central model is:

```text
Measurement
└── Spectrum
```

Before changing either class:

1. Search every constructor call.
2. Search persistence code.
3. Search plotting and monitor code.
4. Search tests.
5. Search tools.
6. Search experiment construction.

A complete model change should update all affected callers in one coherent change.

Avoid temporary compatibility fields that create two sources of truth.

## Persistence change protocol

Any persistence change must consider:

* New saves.
* Existing saves.
* Loader behaviour.
* Failure messages.
* Round-trip tests.
* Human-readable CSV.
* Metadata JSON.
* Array dtypes.
* Pickle safety.

The current experiment format is version 5. Its power columns include target,
achieved arithmetic mean, population STD, absolute RMS, elapsed duration,
attempt/trace IDs, status/error, and valid/total counts. Raw traces are stored
once under `power_measurements/`, indexed by `power_measurements.json`, while
attempts (including failures without traces) are indexed by
`power_attempts.json`. Older tables and experiments without these columns or
indexes must continue to load with `None` values and empty collections.

A persistence change must preserve these additional rules:

* Save an attempt before any associated spectrum.
* Preserve raw values, timestamps, status values, invalid reasons, and batch
  structure.
* Store strings as non-object NumPy arrays; never enable pickle.
* Reject ID collisions and broken attempt/trace/measurement references.
* Reconstruct one shared `PowerTrace` for all measurements which reference it.

Required safety rule:

```python
np.load(path, allow_pickle=False)
```

Never solve an object-array error by switching this to `True`.

The correct fix is to save numeric arrays and primitive scalar values.

After a persistence change, run:

```powershell
python -m tests.test_round_trip
```

## Filesystem rules

Use `pathlib.Path`.

Generated experiment output belongs in:

```text
results/
```

Python persistence code belongs in:

```text
data/
```

Tests should use `tempfile` or another temporary directory unless deliberately testing `results/`.

Temporary test output should be cleaned in `finally`.

Do not write tests that silently pollute the repository.

## Coding style

### General

* Use type annotations.
* Use `from __future__ import annotations` where already used.
* Prefer clear names over abbreviations.
* Keep functions focused.
* Use docstrings for public classes and methods.
* Avoid overly broad exception handling.
* Include the failed path or device in error messages.
* Use `Path` rather than manual path strings.
* Avoid hidden global hardware instances.

### Hardware

* Keep hardware calls in device or acquisition layers.
* Make disconnect and close idempotent.
* Use context managers where practical.
* Use blocking stage motion at the experiment layer unless deliberately redesigned.
* Keep safe cleanup in `finally`.
* Keep numeric shutter states inside the shutter driver.

### Data

* Convert arrays explicitly with `np.asarray`.
* Validate dimensionality.
* Validate matching shapes.
* Preserve raw data.
* Record corrections rather than overwriting history.
* Avoid silent clipping.
* Avoid implicit unit conversions.

### Console tools

Standalone tools may print concise status information.

Reusable packages should prefer logging.

Do not flood the console on every plot frame.

## Import discipline

Use project-root imports consistently, for example:

```python
from analysis.measurement import Measurement
from hardware.devices.spectrometer.spectrum import Spectrum
```

Do not alternate between obsolete paths such as:

```python
from measurement.measurement import Measurement
```

unless the repository has deliberately moved the module there.

Before changing imports, inspect the actual package structure.

## Dependency upgrades

Do not upgrade hardware libraries casually.

A change to pylablib, seabreeze, PIPython, pywin32, NumPy, Python, Kinesis,
PI Software Suite, or StarLab components may affect:

* Device discovery.
* Units.
* Supported methods.
* Driver loading.
* Array behaviour.
* USB access.

Before upgrading:

1. Record the current working versions.
2. Create a Git checkpoint.
3. Review relevant release notes.
4. Test hardware-free code first.
5. Test one device at a time with approval.
6. Keep a rollback path.

Pinned hardware-facing Python versions are in `requirements-hardware.txt`.
They still require the matching vendor installations: Kinesis, SeaBreeze, the
64-bit PI GCS2 DLL, and the registered Ophir StarLab COM server. Close StarLab
and PIMikroMove before Python hardware tests so ownership failures are not
mistaken for driver or configuration faults.

## Codex workflow

### First session

Ask Codex to inspect without editing:

```text
Read AGENTS.md and the referenced documentation.
Inspect the repository.
Do not modify files.
Report architecture differences, incomplete files, safe tests, and
hardware-dependent tests.
```

### First edit

Choose a hardware-free, bounded task.

A suitable first task is:

```text
Review tools/live_spectrometer.py and the proposed background manager.
Make the implementation internally consistent without connecting to hardware.
Add hardware-free tests for background capture, load, toggle, wavelength
validation, and integration-time scaling.
Do not run the live spectrometer.
```

### Review every Codex change

After Codex edits:

```powershell
git status
git diff --stat
git diff
```

Check for:

* Unexpected files.
* Deleted safety handling.
* Changed serial numbers.
* Changed shutter mapping.
* Enabled pickle.
* New hardware side effects during import.
* Duplicate data representations.
* Generated output committed accidentally.

### Run tests

Run only inspected hardware-free tests.

Record:

* Commands run.
* Pass/fail results.
* Tests not run.
* Reason hardware tests were not run.

### Commit coherent checkpoints

After review:

```powershell
git add <reviewed files>
git commit -m "Describe the completed change"
```

Prefer one commit per coherent feature or fix.

## Change completion checklist

A task is complete when:

* The implementation is internally consistent.
* All known callers are updated.
* Hardware-free tests pass.
* Hardware tests are either approved and run, or explicitly not run.
* Safety behaviour is preserved.
* Data formats are documented.
* Relevant documentation is updated.
* `git diff` contains no unrelated edits.
* No generated files are accidentally tracked.
* The user receives a concise summary of changes and test results.

## Failure handling

When a test fails:

1. Preserve the full traceback.
2. Identify the first project-owned frame.
3. Determine whether the test or implementation is stale.
4. Fix the underlying interface rather than patching symptoms.
5. Re-run the narrowest failing test.
6. Run related regressions.
7. Document any compatibility break.

When hardware fails:

1. Stop repeated actions.
2. Close the shutter where safely possible.
3. Disconnect.
4. Record the exact action and error.
5. Do not guess the device state.
6. Ask for operator observations where needed.

```
