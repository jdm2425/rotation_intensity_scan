# Rotation Intensity Scan

Python control and acquisition software for rotation- and intensity-dependent
optical spectroscopy.

The project coordinates:

- A Thorlabs PRM1-Z8 waveplate rotation stage.
- A Thorlabs PRM1-Z8 sample rotation stage.
- A Thorlabs MFF beam shutter.
- A PI C-891 / V-408 translation stage carrying an Ophir power sensor.
- An Ophir Juno power meter.
- An Ocean Insight Ocean SR spectrometer.

## Safety

This repository controls physical laboratory hardware.

The verified shutter mapping is:

```text
state 0 = beam open
state 1 = beam closed
```

The optical order documented for this setup is:

```text
laser -> waveplate -> polariser -> shutter -> power meter -> sample
```

The shutter is upstream of the retractable power probe. Probe motion is allowed
only after shutter closure has been commanded and verified. Sample spectra are
refused unless the PI stage reports the configured probe-out position.

Before a hardware run:

1. Confirm all serial numbers in `hardware/config.py`.
2. Close StarLab and PIMikroMove so Python can own the devices.
3. Confirm rotation-stage and PI-stage travel is mechanically unobstructed.
4. Verify the configured PI probe in/out positions physically.
5. Use a reviewed monotonic waveplate interval for target-power feedback.
6. Keep an operator present.

## Experiment modes

### Fixed waveplate-angle scan

The maintained angle-controlled entry point is:

```powershell
python run_rotation_intensity.py
```

The scan is intensity-major: one waveplate setting is prepared, its incident
power can be measured, then all requested sample angles are scanned.

### Closed-loop target-power scan

The target-power entry point is:

```powershell
python run_target_power_scan.py --help
```

You supply sample angles, requested powers in mW, and one physically reviewed
monotonic waveplate branch. For each requested power the software:

1. Closes the shutter.
2. Inserts the PI-mounted power sensor once.
3. Measures fresh powers at the two branch endpoints.
4. Uses bounded interpolation/bisection to adjust the waveplate.
5. Keeps the probe inserted during all feedback traces.
6. Closes the shutter during every waveplate move.
7. Retracts and verifies the probe once when the target is reached.
8. Acquires all sample-angle spectra at the final waveplate position.

Requested and achieved power are saved separately as `target_power_mw` and
`power_mw`. The final waveplate position and every intermediate raw power trace
are also retained.

Example syntax, using placeholder physical values:

```powershell
python run_target_power_scan.py `
    --sample-angles -30 -20 -10 0 10 20 30 `
    --target-powers-mw 2 5 10 `
    --waveplate-min-deg 0 `
    --waveplate-max-deg 10 `
    --direction increasing `
    --tolerance-mw 0.2 `
    --maximum-power-mw 20 `
    --experiment-name sample_power_rotation_scan
```

Do not use the example branch until it has been measured and verified on the
real apparatus. See `docs/TARGET_POWER_SCAN.md`.

## Standalone PI/Ophir hardware test

The following utility connects only the beam shutter, PI insertion stage, and
Ophir meter. It does not connect either rotation stage or the spectrometer.

```powershell
python -m tools.test_power_probe_hardware --help
```

Inspect identities and current PI state without movement:

```powershell
python -m tools.test_power_probe_hardware inspect
```

Move to a reviewed absolute position and return automatically:

```powershell
python -m tools.test_power_probe_hardware move --position-mm 0.5
```

Acquire three traces while keeping the probe inserted, then retract once:

```powershell
python -m tools.test_power_probe_hardware measure `
    --traces 3 `
    --duration-s 3 `
    --settle-s 1
```

The tool prints its exact actions and requires `RUN` before connecting.
Standalone trace CSV and JSON files are saved under
`results/power_probe_hardware_tests/`.

## Environment

The project is developed on Windows with PowerShell.

```powershell
.\.venv\Scripts\Activate.ps1
python -c "import sys; print(sys.executable)"
```

Hardware-facing Python packages are listed in `requirements-hardware.txt`.
Vendor runtimes are still required:

- Thorlabs Kinesis.
- Ocean Insight SeaBreeze.
- PI Software Suite / GCS DLL.
- Ophir StarLab with the registered `OphirLMMeasurement` COM server.

## Hardware-free tests

Core regression commands:

```powershell
python -m tests.test_round_trip
python -m tests.test_power_trace_round_trip
python -m tests.test_power_probe
python -m tests.test_power_experiment_workflow
python -m tests.test_target_power_experiment_workflow
python -m tests.test_power_safety_policy
python -m tests.test_acquisition_guard
```

The PI and Ophir driver tests use injected fake vendor APIs and are also
hardware-free:

```powershell
python -m tests.test_pi_linear_stage
python -m tests.test_ophir_power_meter
```

Do not assume every file under `tests/` is hardware-free. In particular,
`tests.test_hardware_manager`, stage tests, shutter tests, and spectrometer tests
may operate real equipment.

## Data model

The canonical hierarchy is:

```text
ExperimentDataset
└── Measurement
    └── Spectrum
```

`Measurement.spectrum` is a `Spectrum` object, not a NumPy intensity array.
Power data are represented by durable `PowerMeasurementAttempt` and
`PowerTrace` records.

The persistence layer:

- Saves numeric arrays and primitive scalar metadata.
- Loads NumPy archives with `allow_pickle=False`.
- Reconstructs `Spectrum` before `Measurement`.
- Saves each completed power attempt before associated spectrum acquisition.

## Saved experiment layout

```text
results/
└── ExperimentName_YYYYMMDD_HHMMSS/
    ├── metadata.json
    ├── config.json
    ├── hardware.json
    ├── backgrounds.json
    ├── backgrounds/
    ├── measurements.csv
    ├── spectra/
    ├── power_attempts.json
    ├── power_measurements.json
    └── power_measurements/
```

Each spectrum row may include:

- `target_power_mw`
- achieved `power_mw`
- `waveplate_angle_deg`
- `sample_angle_deg`
- power standard deviation and RMS
- trace and attempt identifiers
- raw-status provenance

## Live spectrometer

```powershell
python -m tools.live_spectrometer
```

This utility connects only to the Ocean SR. It supports manual saving, live
integration-time changes, axis controls, and persistent background capture.

## Offline analysis

```powershell
python -m tools.analyse_experiment `
    results\ExperimentName_YYYYMMDD_HHMMSS `
    --harmonic H5:390:410 `
    --use-background `
    --no-transmission-correction `
    --plot-all
```

Analysis is separate from acquisition and does not overwrite raw detector data.

## Repository guide

- `AGENTS.md`: coding-agent and hardware-safety instructions.
- `docs/PROJECT_CONTEXT.md`: scientific purpose and scope.
- `docs/ARCHITECTURE.md`: data flow and interfaces.
- `docs/HARDWARE.md`: verified device identities and hardware notes.
- `docs/CURRENT_STATE.md`: implementation and verification status.
- `docs/DEVELOPMENT_WORKFLOW.md`: testing and change workflow.
- `docs/TARGET_POWER_SCAN.md`: target-power operation and commissioning.
- `docs/TODAY_RUN_CHECKLIST.md`: staged commands for immediate commissioning.

Generated data belong in `results/`. The `data/` directory is Python source
code only.
