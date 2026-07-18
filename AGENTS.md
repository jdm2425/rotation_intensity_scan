# `AGENTS.md`

````markdown
# Codex Instructions

This repository controls real laboratory hardware. Read this file and the referenced documentation before making substantial changes.

## Required reading

Before editing functional code, read:

- `README.md`
- `docs/PROJECT_CONTEXT.md`
- `docs/ARCHITECTURE.md`
- `docs/HARDWARE.md`
- `docs/CURRENT_STATE.md`
- `docs/DEVELOPMENT_WORKFLOW.md`

Treat the repository implementation as authoritative when it conflicts with documentation, but report the conflict before changing either one.

## Project purpose

This project performs rotation- and intensity-dependent optical spectroscopy.

It coordinates:

- A waveplate rotation stage that controls beam power.
- A sample rotation stage.
- A beam shutter.
- An Ocean Insight Ocean SR spectrometer.
- Spectrum acquisition, live monitoring, persistence, and later harmonic analysis.

The intended experiment rotates the sample and, at each sample angle, varies the waveplate angle or intensity setting, acquires spectra, isolates a harmonic region, and integrates its intensity.

## Hardware safety

This software can move physical hardware and expose the experiment to a laser beam.

Do not perform any of the following unless the user explicitly approves a hardware test:

- Connect to rotation stages.
- Home a stage.
- Move a stage.
- Open or toggle the shutter.
- Connect to the spectrometer.
- Run a complete experiment.
- Run any test marked as hardware-dependent.
- Change hardware serial numbers or state mappings.
- Change stage limits or homing behaviour.

The safe default shutter state is closed.

The known shutter mapping is:

- State `0` = open.
- State `1` = closed.

Do not reverse or reinterpret this mapping without a real hardware verification requested by the user.

Before any approved hardware test:

1. State exactly which devices will connect or move.
2. State the intended stage positions or motion range.
3. Confirm that the shutter will begin and end closed.
4. Prefer the smallest possible test.
5. Ensure cleanup occurs in `finally` blocks or context managers.

## Safe automatic work

The following work is normally safe without hardware:

- Reading and reviewing source code.
- Editing documentation.
- Static analysis.
- Import checks that do not instantiate devices.
- Tests using synthetic `Spectrum` objects.
- Tests using mocks or fakes.
- `python -m tests.test_round_trip`
- Persistence tests that write only to temporary directories.
- Pure analysis, plotting, and configuration validation tests.

Do not assume every file under `tests/` is hardware-free. Inspect it first.

## Canonical data model

The canonical data hierarchy is:

```text
ExperimentDataset
└── Measurement
    └── Spectrum
````

`Measurement` contains experimental state and an embedded `Spectrum`.

`Spectrum` contains detector data and acquisition settings.

Do not regress to the old design in which:

* `measurement.spectrum` was a NumPy array.
* Wavelengths were separately owned by `Measurement`.
* `integration_time_ms` was passed directly to `Measurement.__init__()`.

The current canonical model is approximately:

```python
Measurement(
    timestamp=...,
    waveplate_angle_deg=...,
    sample_angle_deg=...,
    power_mw=...,
    fluence_mj_cm2=...,
    intensity_w_cm2=...,
    spectrum=Spectrum(...),
)
```

Convenience properties on `Measurement`, such as `integration_time_ms`, may forward to the embedded `Spectrum`.

## Persistence requirements

The persistence layer must:

* Save `Spectrum.wavelengths` and `Spectrum.intensities` as numeric NumPy arrays.
* Reconstruct a `Spectrum` before reconstructing a `Measurement`.
* Use `allow_pickle=False` when loading `.npz` files.
* Never save a `Spectrum` object directly into a NumPy archive.
* Never fix object-array errors by enabling pickle.
* Keep generated experiment data under `results/`, not inside the Python `data/` package.
* Preserve completed measurements if a later acquisition fails.
* Flush the measurement index after each successful save.

The hardware-free round-trip test is a core regression test:

```powershell
python -m tests.test_round_trip
```

## Editing rules

Before modifying code:

1. Inspect the current implementation and its callers.
2. Search for all uses of any interface being changed.
3. Identify whether the change affects tests, documentation, saving, loading, plotting, or hardware management.
4. Prefer a small coherent change over isolated patches.
5. Avoid introducing a second representation of the same data.
6. Preserve backwards compatibility only when it is useful and safe.
7. Report obsolete code rather than silently reviving it.

When changing a public data model or constructor, update all affected files in the same task.

Do not provide partial snippets when the user asks for a full file rewrite.

## Code conventions

* Use Python type annotations.
* Use `pathlib.Path` for filesystem paths.
* Use context managers for files and hardware ownership where appropriate.
* Use explicit exceptions with actionable messages.
* Keep hardware-specific code inside `hardware/`.
* Keep analysis independent of live hardware.
* Keep test data deterministic when practical.
* Prefer dependency injection over constructing hardware deep inside experiment logic.
* Do not use mutable default arguments.
* Keep device cleanup idempotent.
* Use logging in reusable library code and concise console output in standalone tools.
* Preserve the existing import layout unless intentionally refactoring it.

## Current priorities

Read `docs/CURRENT_STATE.md` for the live status.

The likely next priorities are:

1. Validate and finish persistent background subtraction in the live spectrometer utility.
2. Add safe utility scripts for hardware status and controlled stage movement.
3. Add a one-spectrum hardware-backed save/load test, only when explicitly approved.
4. Implement harmonic selection and integration.
5. Add transmission correction.
6. Add waveplate-angle-to-power or intensity calibration.

## Git expectations

Before a substantial change, inspect:

```powershell
git status
git diff
```

After changing code:

1. Run the relevant hardware-free tests.
2. Show a concise summary of changed files.
3. Report tests run and their results.
4. Report tests not run, especially hardware tests.
5. Do not commit unless the user asks.
6. Do not discard unrelated user changes.

## Documentation maintenance

Update the documentation when architecture, hardware mappings, verified status, or safe test commands change.

In particular:

* Update `docs/CURRENT_STATE.md` after a feature is verified.
* Update `docs/HARDWARE.md` after a real hardware discovery.
* Update `docs/ARCHITECTURE.md` after a structural change.
* Update `docs/DEVELOPMENT_WORKFLOW.md` after test or command changes.

````

