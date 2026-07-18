# `docs/PROJECT_CONTEXT.md`

```markdown
# Project Context

## Project name

Rotation Intensity Scan

## Scientific objective

The project measures how an optical spectrum changes as a function of:

- Sample rotation angle.
- Incident beam intensity.
- Waveplate angle used to control the incident power.

The longer-term analysis objective is to isolate a selected harmonic feature in each spectrum and integrate its intensity as a function of sample angle and incident intensity.

## Physical experiment

The optical arrangement includes:

1. A rotatable waveplate.
2. A polariser after the waveplate.
3. A sample mounted on a rotation stage.
4. A controllable beam shutter.
5. An Ocean Insight Ocean SR spectrometer.

Rotating the waveplate before the polariser changes the transmitted power. Rotating the sample changes the sample orientation relative to the incident field.

The beam shutter is used to:

- Keep the beam blocked when the experiment is idle.
- Protect the experiment during stage motion where appropriate.
- Acquire background or dark spectra.
- Ensure a defined safe state after failures.

## Intended scan

The intended high-level sequence is:

```text
For each sample angle:
    Move sample stage.
    Wait for motion to complete.

    For each waveplate or intensity setting:
        Move waveplate stage.
        Wait for motion to complete.

        Set shutter state required for acquisition.
        Wait for optical settling.
        Acquire spectrum.
        Close shutter safely.
        Calculate basic statistics.
        Save measurement immediately.
        Update monitor and plot.
````

The exact shutter sequence may differ for signal and background acquisitions, but the safe final state is closed.

## Measurement content

Each completed acquisition should preserve enough information to reproduce and interpret the measurement.

A measurement includes:

* Measurement timestamp.
* Waveplate angle.
* Sample angle.
* Optional measured or calculated power.
* Optional fluence.
* Optional intensity.
* Detector spectrum.
* Integration time.
* Number of averages.
* Spectrometer serial number.
* Peak counts.
* Integrated counts.
* Saturation state.
* Additional metadata.

## Current scope

The current project scope includes:

* Hardware configuration.
* Device connection and cleanup.
* Blocking stage motion.
* Shutter control.
* Spectrum acquisition.
* Live spectrum display.
* Experiment monitoring.
* Immediate persistence of completed measurements.
* Reloading experiments for later analysis.
* Hardware-independent regression tests.

## Planned analysis

Future analysis will likely include:

* Selecting a wavelength interval containing a harmonic.
* Baseline or background subtraction.
* Integration over a wavelength range.
* Peak location and peak height.
* Conversion from wavelength to photon energy where useful.
* Transmission correction.
* Detector response correction where calibration data are available.
* Normalisation by incident power or intensity.
* Angular dependence plots.
* Comparison between two intensity conditions at each sample angle.
* Extraction of harmonic anisotropy or symmetry.

Analysis code should operate on saved `ExperimentDataset` objects and should not require hardware.

## Background spectra

There are two related concepts:

### Live-view background

The live spectrometer utility may use one persistent background file:

```text
tools/live_spectrometer_background.npz
```

This is intended as a convenient laboratory display correction.

It should be possible to:

* Capture the current raw spectrum as the background.
* Replace the previous background.
* Toggle subtraction without deleting the background.
* Reuse the background in a later session.
* Record whether subtraction was applied when saving a standalone spectrum.

### Experiment background

A full experiment may later acquire explicit background measurements as part of the scan protocol.

Those backgrounds should be saved as experiment data rather than relying only on the live-view background file.

Do not treat the live-view background as a complete replacement for reproducible experimental background acquisition.

## Beam intensity model

Waveplate angle is not itself a physical intensity.

The project will eventually need a calibrated relationship such as:

```text
waveplate angle
    → measured optical power
    → pulse energy
    → fluence
    → peak or average intensity
```

The final model may depend on:

* Laser repetition rate.
* Pulse duration.
* Beam waist or spot size.
* Polariser orientation.
* Waveplate retardance.
* Optical losses.
* Calibration measurements.

Until that model is implemented and verified, power, fluence, and intensity fields should remain optional.

Do not invent missing physical quantities.

## Design priorities

The project should prioritise:

1. Hardware safety.
2. Data integrity.
3. Reproducibility.
4. Clear separation between hardware, experiment logic, persistence, and analysis.
5. Immediate saving of completed measurements.
6. Useful error messages.
7. Simple standalone laboratory tools.
8. Hardware-independent testing.
9. Traceability of configuration and hardware metadata.
10. Maintainable code over clever abstractions.

## Out of scope unless explicitly added

The following are not currently assumed:

* Autonomous laser safety decisions.
* Remote unattended experiment operation.
* Automatic determination of safe stage limits.
* Automatic calibration of absolute optical intensity.
* Guaranteed compatibility with arbitrary Thorlabs devices.
* A production GUI.
* Database-backed experiment storage.
* Cloud upload of experimental data.

## Definition of a successful complete scan

A scan is successful when:

* All requested points are either completed or explicitly recorded as failed.
* Every completed acquisition has a corresponding saved spectrum.
* Stage angles and acquisition settings are saved.
* Metadata and hardware information are saved.
* The shutter finishes closed.
* Hardware is disconnected or returned to a defined state.
* The output can be reloaded without enabling pickle.
* The loaded data are suitable for offline analysis.

````
