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
- A PI linear stage carrying a retractable incident-power sensor.
- An Ophir Juno power meter and 3A-P-V1 sensor.
- An Ocean Insight Ocean SR spectrometer.
- Spectrum acquisition, live monitoring, persistence, and later harmonic analysis.

The maintained scan is intensity-major: it sets one waveplate angle, measures
incident power once by default, then acquires spectra across every requested
sample angle before advancing the waveplate. Offline analysis isolates and
integrates one or more harmonic regions.

## Hardware safety

This software can move physical hardware and expose the experiment to a laser beam.

Do not perform any of the following unless the user explicitly approves a hardware test:

- Connect to rotation stages.
- Home a stage.
- Move a stage.
- Open or toggle the shutter.
- Connect to the spectrometer.
- Connect to or read from the power meter.
- Connect to or move the PI power-meter insertion stage.
- Run a complete experiment.
- Run any test marked as hardware-dependent.
- Change hardware serial numbers or state mappings.
- Add or change power-meter calibration/statistic semantics without verified
  device information.
- Change stage limits or homing behaviour.

The safe default shutter state is closed.

The known shutter mapping is:

- State `0` = open.
- State `1` = closed.

Do not reverse or reinterpret this mapping without a real hardware verification requested by the user.

The fixed optical order is shutter, then retractable power meter, then sample.
The shutter must be closed and positively verified before every insertion-stage
move. Sample-spectrum acquisition must be refused unless the power meter is at
its configured and live-verified out position.

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
- `python -m tests.test_base`
- `python -m tests.test_round_trip`
- `python -m tests.test_rotation_scan`
- `python -m tests.test_experiment_workflow`
- `python -m tests.test_harmonic_analysis`
- `python -m tests.test_data_products`
- `python -m tests.test_analysis_reporting`
- `python -m tests.test_analysis_cli`
- `python -m tests.test_ophir_power_meter`
- `python -m tests.test_pi_linear_stage`
- `python -m tests.test_power_probe`
- `python -m tests.test_power_trace_round_trip`
- `python -m tests.test_power_experiment_workflow`
- `python -m tests.test_power_safety_policy`
- `python -m tests.test_acquisition_guard`
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
    power_mw=...,                       # achieved mean power
    target_power_mw=...,                # requested setpoint
    power_std_mw=...,                   # population STD of valid samples
    power_rms_mw=...,                   # sqrt(mean(power**2))
    power_measurement_duration_s=...,
    power_measurement_id=...,            # acquisition-attempt ID
    power_trace_id=...,                  # raw-trace ID
    power_measurement_status=...,
    power_measurement_error=...,
    power_valid_sample_count=...,
    power_total_sample_count=...,
    fluence_mj_cm2=...,
    intensity_w_cm2=...,
    spectrum=Spectrum(...),
)
```

Convenience properties on `Measurement`, such as `integration_time_ms`, may forward to the embedded `Spectrum`.

`Measurement.power_mw` remains the canonical achieved mean power for backward
compatibility. `achieved_power_mw` is a read-only alias. Do not use
`target_power_mw` as though it were achieved power. The implemented statistics
use only finite, positive, status-OK raw samples: `power_mw` is their arithmetic
mean, `power_std_mw` is their population standard deviation (denominator `N`),
and `power_rms_mw` is their absolute RMS, `sqrt(mean(power**2))`. The RMS is not
an uncertainty estimate. Zero, negative, missing, non-finite, or status-flagged
samples remain in the raw trace and are never predicted, interpolated, clipped,
or replaced. If no valid samples exist, all three statistics remain `None`.

The Ophir/PI acquisition path and bounded closed-loop target-power scan are
implemented. Targeting is allowed only inside an operator-supplied monotonic
waveplate branch and must preserve requested power, achieved power, final angle,
and every raw feedback trace separately. The probe is inserted once per target
block and retracted before sample spectra. Fluence and intensity remain
optional and must never be invented. Configured PI in/out positions must be
physically verified before hardware use.

When enabled, defaults are one trace per waveplate/intensity block, 10 s
sampling after 3 s sensor settling, physical fundamental wavelength 2000 nm,
returned sensor option `>800`, fixed range `30.0mW`, and a 20 mW raw-sample
ceiling. Unsafe meter-status or non-finite-power flags and any positive raw value above
the ceiling abort before a spectrum, regardless of the mean or continuation
setting.

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

The current experiment persistence format is version `5`. In addition to
`measurements.csv`, it stores power attempts in `power_attempts.json`, unique
trace metadata in `power_measurements.json`, and pickle-free raw traces under
`power_measurements/`. A successful or failed power attempt is flushed before
the corresponding spectrum acquisition. Loaders must continue to accept older
tables and experiments in which these power fields and indexes are absent.

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

1. Keep the complete hardware-free persistence and analysis suite passing,
   especially `tests.test_round_trip`, `tests.test_harmonic_analysis`,
   `tests.test_data_products`, `tests.test_analysis_reporting`, and
   `tests.test_analysis_cli`.
2. Use `tools.test_power_probe_hardware` to verify the configured PI probe
   in/out positions and one persistent-insertion measurement session.
3. Hardware-validate one target power with one sample angle, then inspect the
   saved target, achieved power, final waveplate angle, attempts, and traces.
4. Refine harmonic analysis with optional local baselines, replicate
   uncertainty, and publication-specific plot formatting.
5. Add detector/optical response corrections where calibration exists.

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
