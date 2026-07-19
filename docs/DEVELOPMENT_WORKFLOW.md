# `docs/DEVELOPMENT_WORKFLOW.md`

```markdown
# Development Workflow

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
python -m tests.test_round_trip
python -m tests.test_experiment_workflow
python -m tests.test_harmonic_analysis
python -m tests.test_data_products
python -m tests.test_analysis_reporting
python -m tests.test_analysis_cli
```

The experiment-workflow test uses fake devices; it does not connect hardware.
The harmonic-analysis, data-product, reporting, and analysis-CLI tests use
deterministic synthetic results and temporary directories.

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
* `analysis_recipe.json`: machine-readable version-2 recipe.
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
* `power_mw` is the achieved mean and the field used for power-coordinate
  selection.
* `power_rms_mw` is the RMS statistic reported by the meter over
  `power_measurement_duration_s`; do not call it standard deviation unless a
  verified future meter API explicitly defines that statistic.

The current acquisition path does not populate these fields because no power
meter or waveplate-power calibration is integrated.

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
* Home command.
* Position scan.

Before running, report:

* Device serial.
* Start position where known.
* Target position.
* Maximum movement.
* Expected final state.
* Shutter behaviour.

### Level 4: full experiment

Requires explicit approval and operator supervision.

A full experiment may:

* Connect all hardware.
* Move both stages.
* Open the shutter.
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

### Gate before power-meter integration

The data model is ready for power samples, but adding a meter is a hardware
change. Before implementing or testing it:

1. Run `tests.test_round_trip`, `tests.test_harmonic_analysis`,
   `tests.test_data_products`, `tests.test_analysis_reporting`, and
   `tests.test_analysis_cli`; all must pass.
2. Identify the real meter model, serial, supported Python interface, units,
   sampling behaviour, and definition of its RMS output.
3. Keep `power_mw` as achieved mean and `target_power_mw` as the setpoint.
4. Do not reinterpret meter-reported RMS as standard deviation without an
   authoritative device/API definition.
5. Add driver and experiment integration through the normal hardware ownership
   layers; do not construct a meter inside analysis or persistence code.
6. Request explicit operator approval before connecting to or reading the real
   device, and begin with the smallest read-only identity/sample test.
7. Re-run persistence and analysis regressions before attempting a coordinated
   experiment.

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

The current experiment format is version 4. Its additive optional power columns
are `target_power_mw`, `power_mw`, `power_rms_mw`, and
`power_measurement_duration_s`; older tables without the new context columns
must continue to load with `None` values.

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

A change to pylablib, seabreeze, NumPy, Python, or Kinesis components may affect:

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
