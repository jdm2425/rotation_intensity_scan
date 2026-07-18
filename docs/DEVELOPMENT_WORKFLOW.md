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
