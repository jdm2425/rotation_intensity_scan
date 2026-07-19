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
│   ├── analysis_reporting.py
│   ├── data_products.py
│   ├── harmonic_analysis.py
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
│   ├── analyse_experiment.py
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

Additional hardware-free workflow and analysis regressions are:

```powershell
python -m tests.test_experiment_workflow
python -m tests.test_harmonic_analysis
python -m tests.test_data_products
python -m tests.test_analysis_reporting
python -m tests.test_analysis_cli
```

These use fake devices or deterministic synthetic data and temporary
directories; they do not connect to laboratory hardware.

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
* `G`: toggle background subtraction.

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
    ├── backgrounds.json
    ├── backgrounds/
    │   └── background_000001.npz
    ├── measurements.csv
    └── spectra/
        ├── spectrum_000001.npz
        ├── spectrum_000002.npz
        └── ...
```

`measurements.csv` provides a human-readable index.

Each `.npz` file contains numerical spectrum arrays and scalar acquisition metadata.

The current saved-data format is version 4. `metadata.json` records the
format version, `measurements.csv` stores each measurement's JSON metadata,
and named raw background spectra are indexed by `backgrounds.json`.
This metadata can record analysis bounds, filtering choices, background use,
and other correction provenance without changing the core data model. Older
CSV files without per-measurement metadata continue to load with an empty
metadata dictionary.

Version 4 adds optional power-meter context to each measurement:

* `target_power_mw`: requested power setpoint.
* `power_mw`: achieved mean power and the canonical power coordinate.
* `power_rms_mw`: RMS statistic reported by the power meter over the sampling
  interval. It is not a standard deviation unless the eventual verified meter
  integration defines it that way.
* `power_measurement_duration_s`: duration of that power-meter sampling
  interval.

Older measurement tables without these additional columns still load, with the
new values set to `None`. The current experiment does not yet connect to a
power meter or populate these fields; there is also no implemented
waveplate-to-power calibration. Do not infer or invent them.

Before a normal scan, the controller acquires a named shutter-closed background
and saves it with the experiment. Signal spectra remain raw; background and
filter-transmission corrections are selected explicitly during offline analysis.

## Offline harmonic analysis

Analysis is deliberately separate from acquisition. Define one harmonic for a
filtered scan or repeat `--harmonic` for a broadband, multi-harmonic scan:

```powershell
python -m tools.analyse_experiment `
    results\rotation_intensity_scan_YYYYMMDD_HHMMSS `
    --harmonic H5:390:410 `
    --use-background `
    --no-transmission-correction `
    --plot-all `
    --polar
```

The source detector spectra are never cropped or overwritten. The tool writes a
master derived table named `harmonic_signals.csv`, an `analysis_recipe.json`,
an `analysis_recipe.sha256`, an `analysis_summary.md`, and requested figure
products under the experiment's `analysis/` directory.
Filter transmission correction is optional and must be requested explicitly
using either a fraction or a CSV curve with
`wavelength_nm,transmission_fraction` columns.

Background and transmission choices have three distinct states: used,
explicitly not used, and not specified. Prefer an explicit choice in every
quick analysis:

* `--use-background [NAME]` applies a saved background; without a name it uses
  `pre_scan_dark`.
* `--no-background` explicitly records that background subtraction was not
  used.
* `--transmission-fraction` or `--transmission-curve` applies the requested
  correction.
* `--no-transmission-correction` explicitly records that no transmission
  correction was used.

If neither background option is supplied while saved backgrounds exist, the
analysis runs without subtraction and records an unspecified-choice warning.
Likewise, installed-filter metadata without an explicit transmission choice
produces a warning. These warnings are written to the recipe and summary and
printed in the console; corrections are never enabled automatically from
metadata.

The master `harmonic_signals.csv` contains one row for every analysed
measurement and harmonic window. Each requested figure additionally has
same-stem PNG, PDF, and CSV files. The figure CSV contains the exact selected
and optionally normalised values passed to Matplotlib, together with the source
result fields, run identity, correction flags, units, and normalisation factor.
The `figures` manifest in `analysis_recipe.json` links every PNG and PDF to its
CSV data file and records its SHA-256, fixed selection, absolute tolerance,
actual matched minimum/maximum, correction annotation, series IDs, and row
count.

The version-2 analysis recipe records the four-step correction pipeline (raw
detector data, optional saved-background subtraction, optional filter
transmission correction, then harmonic-window trapezoidal integration), quality
counts, warnings, Python/NumPy/Matplotlib versions, and the SHA-256 of
`harmonic_signals.csv`. Background and copied transmission-curve records carry
their own source checksums. `analysis_recipe.sha256` protects the final recipe,
and `analysis_summary.md` gives a durable human-readable account of the same
choices, warnings, power-field coverage, and figure manifest.

Quick-look figures include a correction footer by default. It identifies the
displayed signal plus the background and transmission choices. Use
`--no-annotate-corrections` only to remove that footer from the figure; it does
not change the calculations, recipe, warnings, or summary.

Input-dependence and fixed-input rotation plots can use any one of four explicit
coordinates:

* `waveplate_angle_deg`
* `power_mw`
* `fluence_mj_cm2`
* `intensity_w_cm2`

Select the coordinate with `--input-coordinate`, select rotation values with
repeatable `--input-value`, set an absolute matching tolerance with
`--input-tolerance` when needed, and choose the plotted quantity with
`--signal`.
For example, after achieved power values have genuinely been measured and saved
with the measurements:

```powershell
python -m tools.analyse_experiment results\Experiment_YYYYMMDD_HHMMSS --harmonic H5:390:410 --use-background --no-transmission-correction --input-coordinate power_mw --input-value 2.0 --input-tolerance 0.1 --sample-angle 0 --signal integrated_signal --polar
```

The analysis never invents a calibrated coordinate and never falls back to
waveplate angle when requested power, fluence, or intensity values are absent.
For a fixed-power rotation plot, `--input-value` is matched against achieved
`power_mw`, not `target_power_mw`, using the absolute `--input-tolerance` in mW.
The tolerance is saved in each figure CSV and manifest record. The manifest and
`analysis_summary.md` also report the actual minimum and maximum achieved power
of the selected rows, so a nominal 2.0 mW selection can be audited against the
measurements it really included. The default tolerance is `1e-6` in the chosen
coordinate's units and is normally too strict for fluctuating measured power;
choose it explicitly from the meter behaviour and experimental requirements.
With `--plot-all`, complete `target_power_mw` values define the nominal
automatic rotation centres; row inclusion still compares achieved `power_mw`
against each centre. If target values are incomplete, the automatic centres
come from the achieved-power values instead. The recipe records which field
supplied those centres.
The default `integrated_signal` is the final value after every explicitly
requested correction. `raw_integrated_signal` retains the uncorrected window
integral, while `background_corrected_integral` stops after saved-background
subtraction and before any transmission correction. Peak fields are also
available through `--signal`.

### Reusable and multi-run analysis

`analysis/data_products.py` provides the hardware-independent publication-data
API:

* `AnalysedRun` represents one analysed experiment and its provenance.
* `load_analysed_run()` reloads an analysis directory containing
  `harmonic_signals.csv` and `analysis_recipe.json`.
* `excitation_scan_data()` selects signal versus an explicit input coordinate.
* `rotation_scan_data()` selects sample-angle dependence at a fixed input
  coordinate.
* `save_figure_data_csv()` exports the exact long-form figure rows.
* `plot_figure_data()` in `plotting/harmonic_plots.py` renders those same rows.

This separation lets a publication script combine independently analysed runs
without rerunning acquisition or depending on the quick-analysis CLI:

```python
from pathlib import Path

from analysis.data_products import (
    excitation_scan_data,
    load_analysed_run,
    rotation_scan_data,
    save_figure_data_csv,
)
from plotting.harmonic_plots import plot_figure_data

run_a = load_analysed_run(Path("results/run_a/analysis/harmonic_analysis_..."))
run_b = load_analysed_run(Path("results/run_b/analysis/harmonic_analysis_..."))

input_data = excitation_scan_data(
    (run_a, run_b),
    sample_angle_deg=0.0,
    x_field="power_mw",
    harmonics=["H5", "H7"],
    signal="integrated_signal",
)
figure, _ = plot_figure_data(input_data)
figure.savefig("harmonics_vs_power.pdf")
save_figure_data_csv(input_data, "harmonics_vs_power.csv")

rotation_data = rotation_scan_data(
    (run_a, run_b),
    fixed_field="power_mw",
    fixed_value=2.0,
    value_tolerance=0.1,
    harmonics=["H5"],
)
polar_figure, _ = plot_figure_data(rotation_data, polar=True)
```

Runs and harmonics remain separate plot series. Repeated measurements at the
same coordinate are preserved as replicates; the API does not average them
automatically. If two runs use the same harmonic name with different wavelength
windows, combining them is rejected by default so unlike integrations are not
silently overlaid.

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
