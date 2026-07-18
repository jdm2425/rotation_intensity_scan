# `docs/CURRENT_STATE.md`

```markdown
# Current State

Last reviewed: 18 July 2026

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

- The hardware manager has connected the configured devices successfully.
- It owns:
  - Waveplate stage.
  - Sample stage.
  - Shutter.
  - Spectrometer.

### Experiment execution

- The main experiment has run end-to-end with hardware.
- Stage movement, shutter control, acquisition, monitoring, plotting, and saving have been integrated.
- Live spectrum plotting during an experiment works.

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

The loader:

* Uses `allow_pickle=False`.
* Reconstructs `Spectrum`.
* Reconstructs `Measurement`.
* Returns an `ExperimentDataset`.

The hardware-free round-trip test passes:

```powershell
python -m tests.test_round_trip
```

### Results directory separation

Generated experiment directories are intended to live under:

```text
results/
```

The `data/` directory is reserved for Python source code.

## Implemented but requiring hardware validation

### Live spectrometer utility

A standalone utility has been drafted at:

```text
tools/live_spectrometer.py
```

Intended features include:

* Spectrometer-only connection.
* Live spectrum plot.
* Peak display.
* Saturation warning.
* Adjustable integration time.
* Y-axis autoscaling toggle.
* Manual spectrum saving.
* Clean quit handling.

Its final behaviour should be verified against the actual `OceanSR` constructor and driver setter methods.

Do not mark it fully verified until it has been run with the real spectrometer.

## In progress or planned

### Persistent live background

Planned structure:

```text
tools/spectrum_background.py
tools/live_spectrometer_background.npz
```

Desired controls:

* `B`: capture or replace the saved background.
* `T`: toggle subtraction.
* Keep one background between sessions.
* Start with subtraction disabled unless intentionally configured otherwise.
* Scale for integration time where appropriate.
* Preserve negative corrected values.
* Calculate saturation from raw values.
* Save raw and corrected spectra distinctly.

The background calibration file should normally be excluded from Git.

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

### Harmonic analysis

Not yet implemented as a stable analysis layer.

Needed capabilities include:

* Select wavelength range.
* Estimate or subtract baseline.
* Integrate selected harmonic.
* Record integration bounds.
* Plot integrated signal against sample angle.
* Compare intensity settings.
* Handle saturated or invalid measurements.

### Transmission correction

Not yet implemented.

A future correction should:

* Load a transmission or response curve.
* Interpolate safely to the spectrum wavelength grid.
* Reject invalid or zero correction values.
* Record the correction source.
* Distinguish raw and corrected data.

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

## Immediate recommended sequence

1. Add this documentation pack and `AGENTS.md`.
2. Commit a Git checkpoint.
3. Let Codex inspect the repository without editing.
4. Reconcile documentation with actual code.
5. Run only hardware-free tests.
6. Finish and verify live spectrometer background support.
7. Add a hardware status utility.
8. Add controlled stage movement tools.
9. Design the harmonic-analysis API.
10. Add calibration and correction models.

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
