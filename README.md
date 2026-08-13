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
    --settle-s 3 `
    --initial-settle-s 5
```

This standalone diagnostic uses the Ophir `AUTO` range by default and has no
power abort threshold by default, so all requested traces are saved. To print
a warning above 20 mW while continuing:

```powershell
python -m tools.test_power_probe_hardware measure `
    --traces 3 `
    --maximum-power-mw 20
```

Add `--abort-above-maximum` only when an aborting diagnostic threshold is
deliberately wanted. This diagnostic behavior does not weaken experiment
safety: experiment and target-power scans still abort before a spectrum when
any positive raw sample exceeds their `--maximum-power-mw` ceiling.

The tool prints its exact actions and requires `RUN` before connecting.
Standalone trace CSV and JSON files are saved under
`results/power_probe_hardware_tests/`.

The longer initial settling period is deliberate: it separates first-exposure
and first-stream startup from the normal per-trace settling period. All traces
are still saved; no low or otherwise inconvenient reading is discarded.

## Waveplate power-control commissioning

Map power over an operator-reviewed angular interval and print the largest
contiguous monotonic optical branch:

```powershell
python -m tools.waveplate_power_control scan `
    --scan-start-deg 60 `
    --scan-stop-deg 85 `
    --step-deg 1
```

This identifies optical control limits for `waveplate_min_deg`,
`waveplate_max_deg`, and `monotonic_direction`. It does not discover mechanical
stage end stops and will not move outside the supplied interval. The waveplate
returns to its starting angle after a successful mapping scan. The output
directory contains `waveplate_power_map.png`, with the selected monotonic
branch shaded and its minimum/maximum waveplate angles marked. If the scan
contains multiple local minima and maxima, the tool evaluates the intervening
contiguous branches and recommends the one with the largest measured power
span (using point count as the tie-breaker).

After reviewing that saved mapping, set power inside a requested range:

```powershell
python -m tools.waveplate_power_control set-range `
    --minimum-power-mw 4.8 `
    --maximum-power-mw 5.2 `
    --waveplate-min-deg 66 `
    --waveplate-max-deg 83 `
    --direction increasing
```

Both commands close and verify the shutter before every waveplate or probe
move, enforce the raw-sample power ceiling, save every feedback trace, retract
the probe, and finish with the shutter closed.

Power-meter range and power safety ceiling are separate. The standalone
diagnostic, waveplate-control tool, and experiment configuration default to
the verified Ophir `AUTO` range. Target-power experiments still reject targets
above `--maximum-power-mw` and abort before spectra if any positive raw sample
exceeds it; this catches overshoot and drift rather than trusting only the
requested target.

Each successful mapping scan now also saves `malus_calibration.json`. The fit
uses the half-wave-plate form `c0 + c1*cos(4*angle) + c2*sin(4*angle)` on the
recommended monotonic branch. To use it for a target-power scan:

```powershell
python run_target_power_scan.py `
    ... `
    --power-calibration `
    results\waveplate_power_control\scan_20260729_160756\malus_calibration.json
```

The calibration supplies only the first candidate angle. At the start of each
target block, the controller still measures both reviewed branch endpoints.
The higher-power endpoint provides a fresh vertical-offset correction, similar
to translating the empirical calibration curve in Morse et al. (2023), before
the calibrated angle is calculated. Measured feedback and configured bounds
remain authoritative.

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

Independent repeat spectra can be collected at every sample/intensity point by
setting `config.spectrometer.spectra_per_point` (or using
`--spectra-per-point` with the target-power command). Every spectrum is saved
as a separate measurement. Harmonic plots group repeats at the same coordinate
and show their arithmetic mean with standard-error-of-the-mean (SEM) error
bars; the underlying per-spectrum harmonic rows remain in
`harmonic_signals.csv` and the per-figure CSV.

```powershell
python -m tools.analyse_experiment `
    results\ExperimentName_YYYYMMDD_HHMMSS `
    --harmonic H5:390:410 `
    --use-background `
    --no-transmission-correction `
    --plot-all
```

Analysis is separate from acquisition and does not overwrite raw detector data.
When `--input-coordinate` is omitted, analysis now uses achieved `power_mw`
automatically if it is present for every result; otherwise it retains
waveplate-angle plots. Power-selected rotation figure filenames contain the
recorded achieved power, and their titles report achieved power ± the recorded
population standard deviation. Use
`--input-coordinate waveplate_angle_deg` to request the older angle-based
naming and selection explicitly.

Figures are saved as PNG plus their exact CSV data by default. Add `--save-pdf`
to also create PDF copies. Displayed power values and power-based filenames use
one decimal place by default; change this with, for example,
`--power-decimal-places 2`. CSV and JSON values always retain full precision.

## Repository guide

- `AGENTS.md`: coding-agent and hardware-safety instructions.
- `docs/COMMAND_REFERENCE.md`: central operator command and option reference.
- `docs/PROJECT_CONTEXT.md`: scientific purpose and scope.
- `docs/ARCHITECTURE.md`: data flow and interfaces.
- `docs/HARDWARE.md`: verified device identities and hardware notes.
- `docs/CURRENT_STATE.md`: implementation and verification status.
- `docs/DEVELOPMENT_WORKFLOW.md`: testing and change workflow.
- `docs/TARGET_POWER_SCAN.md`: target-power operation and commissioning.
- `docs/TODAY_RUN_CHECKLIST.md`: staged commands for immediate commissioning.

Generated data belong in `results/`. The `data/` directory is Python source
code only.
