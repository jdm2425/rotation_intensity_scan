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

1. The laser.
2. A rotatable waveplate.
3. A polariser after the waveplate.
4. A controllable beam shutter.
5. An Ophir power sensor on a retractable PI linear stage.
6. The sample mounted on a rotation stage.
7. An Ocean Insight Ocean SR spectrometer collecting the emitted spectrum.

Rotating the waveplate before the polariser changes the transmitted power. Rotating the sample changes the sample orientation relative to the incident field.

The beam shutter is used to:

- Keep the beam blocked when the experiment is idle.
- Protect the experiment during stage motion where appropriate.
- Acquire background or dark spectra.
- Ensure a defined safe state after failures.

The shutter is always upstream of the power sensor. Every insertion-stage move
therefore requires a positively verified closed shutter. The sample beam may
open only after the sensor has returned to its configured, live-verified out
position.

## Intended scan

The intended high-level sequence is:

```text
For each waveplate or intensity setting:
    Move waveplate stage and wait for motion to complete.
    By default, acquire one shutter-interlocked incident-power trace.
    Close shutter, retract power meter, and verify the out position.

    For each sample angle:
        Move sample stage and wait for motion to complete.
        Verify the power meter is out.
        Open shutter, acquire spectrum, and close shutter safely.
        Calculate basic statistics.
        Save measurement immediately with the shared power-trace reference.
        Update monitor and plot.
````

The exact shutter sequence may differ for signal and background acquisitions, but the safe final state is closed.

## Measurement content

Each completed acquisition should preserve enough information to reproduce and interpret the measurement.

A measurement includes:

* Measurement timestamp.
* Waveplate angle.
* Sample angle.
* Optional requested power setpoint (`target_power_mw`).
* Optional achieved mean power (`power_mw`).
* Optional population standard deviation (`power_std_mw`) and absolute RMS
  (`power_rms_mw`) of valid power samples.
* Actual power-sampling duration, attempt/trace IDs, status, error, and
  valid/total sample counts.
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
* Shutter-interlocked PI probe insertion and retraction.
* Ophir power streaming with raw samples and explicit validity.
* Spectrum acquisition.
* Live spectrum display.
* Experiment monitoring.
* Immediate persistence of completed measurements.
* Reloading experiments for later analysis.
* Explicit offline background and filter-transmission corrections.
* Reusable single- and multi-run harmonic data products.
* Human- and machine-readable analysis provenance, warnings, and checksums.
* Hardware-independent regression tests.

## Offline analysis

Implemented analysis includes:

* Selecting a wavelength interval containing a harmonic.
* Explicit saved-background subtraction.
* Integration over a wavelength range.
* Peak location and peak height.
* Scalar or wavelength-dependent filter-transmission correction.
* Signal-versus-input and Cartesian/polar rotation plots.
* Exact per-figure CSV products and multi-run overlays.
* Correction pipelines, quality warnings, software versions, and checksums in
  the analysis recipe and `analysis_summary.md`.

Further analysis may include:

* Local baseline or sideband estimation.
* Conversion from wavelength to photon energy where useful.
* Detector response correction where calibration data are available.
* Normalisation by incident power or intensity.
* Angular dependence plots.
* Comparison between two intensity conditions at each sample angle.
* Extraction of harmonic anisotropy or symmetry.

Analysis code should operate on saved `ExperimentDataset` objects and should not require hardware.

For quick analysis, background and transmission decisions remain explicit.
Choosing `--no-background` or `--no-transmission-correction` records a deliberate
choice. Leaving a relevant choice unspecified records a warning rather than
silently applying a correction. Quick figures are correction-annotated by
default; the annotation may be disabled without changing numerical provenance.

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

A normal data-saving experiment acquires a shutter-closed background before
scan-point motion when background acquisition is enabled in `ExperimentConfig`.
The defaults are name `pre_scan_dark`, five averages, and 0.05 s settling.
Unsaved test mode skips it because no dataset exists in which to preserve it.

Those backgrounds should be saved as experiment data rather than relying only on the live-view background file.

The raw background is saved separately from illuminated `Measurement` objects.
Subtraction remains an explicit offline analysis choice.

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

The version-5 data model and acquisition path use distinct power fields:

* `target_power_mw` is the requested setpoint.
* `power_mw` is the arithmetic mean of finite, positive, status-OK raw samples
  and the canonical analysis coordinate.
* `power_std_mw` is their population standard deviation (denominator `N`).
* `power_rms_mw` is their absolute RMS, `sqrt(mean(power**2))`.
* `power_measurement_duration_s` is the actual elapsed trace duration.

Offline fixed-power selection matches achieved `power_mw` using an explicit
absolute tolerance and records both that tolerance and the actual matched
range. It does not use target power as a substitute.
For quick `--plot-all` analysis, complete target-power values can define the
nominal automatic centres, but selection still matches achieved power. The
analysis recipe records whether target or achieved values supplied the
centres.

The Ophir meter driver, PI driver, retractable-probe coordinator, experiment
cadence, persistence, and analysis propagation are implemented. The default is
one power trace after each waveplate setting and before its sample-angle block;
`per_measurement` and `disabled` cadences are also available. The standard
settings are a 10 s trace after 3 s settling, physical fundamental wavelength
2000 nm, sensor option `>800`, automatic meter range selection, and a
separately configured maximum raw positive reading.

Zero, negative, missing, non-finite, or status-flagged raw readings are retained
but excluded from statistics. They are never predicted, substituted, or
derived from waveplate angle. An all-invalid trace therefore has no achieved
power. A bounded closed-loop target-power controller is implemented for an
operator-supplied monotonic waveplate branch. It measures the requested power
with the retractable probe and stores requested and achieved values separately.
No absolute fluence or intensity calibration is implemented, so those fields
remain unset unless independently established.

Power acquisition is still disabled by default because the physical PI-stage
in/out positions have not yet been established. The current hardware manager
also refuses to connect while the installed probe lacks those safe positions.

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

The PI identity/state check and smallest reversible motion are now verified.
The next power-related step is physical in/out-position calibration, followed
by one complete shutter-interlocked intensity-block validation. This must not introduce an
automatic reference/home procedure or a waveplate-power prediction.

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
* The retractable power meter finishes at its verified out position when it is
  physically installed.
* Hardware is disconnected or returned to a defined state.
* The output can be reloaded without enabling pickle.
* The loaded data are suitable for offline analysis.

````
