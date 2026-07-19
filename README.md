# `README.md`

```markdown
# Rotation Intensity Scan

A Python control and acquisition system for rotation- and intensity-dependent optical spectroscopy.

The project coordinates two Thorlabs rotation stages, a Thorlabs beam shutter, and an Ocean Insight Ocean SR spectrometer. It acquires and saves spectra while varying sample angle and beam intensity.

## Safety warning

This software controls physical laboratory equipment and may expose the optical setup to a laser beam.

Do not run hardware tests or complete experiments unless:

- The correct devices are connected.
- The optical setup is safe.
- Stage motion ranges have been checked.
- The shutter is known to begin and end closed.
- The operator understands which hardware will move.

The shutter mapping currently verified for this setup is:

- State `0` = open.
- State `1` = closed.

## Experiment concept

The intended experiment is:

1. Move the sample rotation stage to a selected angle.
2. At that sample angle, move the waveplate through one or more intensity settings.
3. Control the shutter around acquisition.
4. Acquire an Ocean SR spectrum.
5. Save the spectrum and the corresponding experimental state.
6. Repeat across the scan grid.
7. Later isolate a selected harmonic region and integrate its intensity.
8. Apply optional background and transmission corrections.
9. Relate waveplate angle to beam power, fluence, or intensity.

## Current architecture

The core data hierarchy is:

```text
ExperimentDataset
└── Measurement
    └── Spectrum
````

A `Measurement` stores the experimental state, including stage angles and optional beam quantities.

A `Spectrum` stores:

* Wavelengths.
* Detector intensities.
* Integration time.
* Number of averages.
* Spectrometer serial number.
* Correction flags.
* Acquisition timestamp where supported.

The persistence layer saves numeric arrays only and reloads them with NumPy pickle disabled.

## Repository layout

```text
rotation_intensity_scan/
├── AGENTS.md
├── README.md
├── acquisition/
├── analysis/
│   └── measurement.py
├── data/
│   ├── __init__.py
│   ├── data_loader.py
│   ├── data_writer.py
│   └── experiment_dataset.py
├── docs/
│   ├── PROJECT_CONTEXT.md
│   ├── ARCHITECTURE.md
│   ├── HARDWARE.md
│   ├── CURRENT_STATE.md
│   └── DEVELOPMENT_WORKFLOW.md
├── experiments/
├── hardware/
│   ├── config.py
│   ├── hardware_manager.py
│   └── devices/
├── monitor/
├── plotting/
├── results/
├── tests/
├── tools/
│   ├── __init__.py
│   └── live_spectrometer.py
└── run_rotation_intensity.py
```

Generated experimental data belong in `results/`.

The `data/` directory is a Python package and should contain source code only.

## Environment

The project is currently developed on Windows using PowerShell and a local virtual environment.

Activate the existing environment from the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
```

Use the dependency versions already installed in the working environment unless intentionally performing a dependency upgrade.

Important libraries include:

* NumPy.
* Matplotlib.
* pylablib.
* seabreeze using the `pyseabreeze` backend.
* Thorlabs Kinesis components where required by existing device code.

## Hardware-free regression test

The save/load round-trip test uses synthetic spectra and does not require laboratory hardware:

```powershell
python -m tests.test_round_trip
```

It verifies:

* A `Measurement` containing a `Spectrum` can be saved.
* The spectrum arrays are stored without Python object arrays.
* The data can be loaded with `allow_pickle=False`.
* The loader reconstructs `Spectrum` and then `Measurement`.
* Important scalar values and arrays survive the round trip.

## Live spectrometer utility

The standalone live viewer is started with:

```powershell
python -m tools.live_spectrometer
```

It is intended to connect only to the Ocean SR spectrometer, not the stages or shutter.

Planned or implemented controls include:

* `Q` or `Escape`: quit.
* `S`: save the current spectrum.
* `+` or `=`: increase integration time.
* `-`: decrease integration time.
* `A`: toggle y-axis autoscaling.
* `R`: reset plot limits.
* `B`: capture and replace the persistent background.
* `T`: toggle background subtraction.

Saved standalone spectra belong under:

```text
results/live_spectrometer/
```

A persistent background file may be stored as:

```text
tools/live_spectrometer_background.npz
```

That file is machine- and detector-specific and should normally be excluded from Git.

## Running the full experiment

The full experiment entry point is:

```powershell
python run_rotation_intensity.py
```

Do not run it as an ordinary software test. It may connect to and move real hardware.

Before running:

1. Inspect `hardware/config.py`.
2. Confirm all serial numbers.
3. Confirm stage motion ranges.
4. Confirm the shutter starts closed.
5. Confirm the spectrometer is available.
6. Confirm the output directory is `results/`.
7. Keep an operator present.

## Saved experiment format

A typical saved experiment is:

```text
results/
└── ExperimentName_YYYYMMDD_HHMMSS/
    ├── metadata.json
    ├── config.json
    ├── hardware.json
    ├── measurements.csv
    └── spectra/
        ├── spectrum_000001.npz
        ├── spectrum_000002.npz
        └── ...
```

`measurements.csv` provides a human-readable index.

Each `.npz` file contains numerical spectrum arrays and scalar acquisition metadata.

The current saved-data format is version 2. `metadata.json` records the
format version, and `measurements.csv` stores each measurement's JSON metadata.
This metadata can record analysis bounds, filtering choices, background use,
and other correction provenance without changing the core data model. Older
CSV files without per-measurement metadata continue to load with an empty
metadata dictionary.

## Documentation

Read these files before making architectural changes:

* `docs/PROJECT_CONTEXT.md`: scientific purpose and scope.
* `docs/ARCHITECTURE.md`: software structure and canonical interfaces.
* `docs/HARDWARE.md`: verified hardware details and safety notes.
* `docs/CURRENT_STATE.md`: working, incomplete, and planned features.
* `docs/DEVELOPMENT_WORKFLOW.md`: testing and change-management process.
* `AGENTS.md`: instructions for Codex and other coding agents.

## Development principle

The project should remain usable at three levels:

1. Hardware-independent data and analysis code.
2. Standalone laboratory utilities for individual devices.
3. A coordinated experiment controller for complete scans.

Hardware-specific details should not leak into analysis or persistence code.

````
