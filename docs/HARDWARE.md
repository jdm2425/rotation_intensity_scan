# `docs/HARDWARE.md`

```markdown
# Hardware

## Important warning

This document records the currently known laboratory configuration.

Do not change serial numbers, state mappings, motion behaviour, or driver choice based only on assumptions.

Any new hardware discovery should be verified with the real device and then documented here.

## Current devices

| Role | Device | Serial number | Current interface |
|---|---|---:|---|
| Waveplate rotation | Thorlabs PRM1-Z8 | `27268875` | pylablib / Kinesis |
| Sample rotation | Thorlabs PRM1-Z8 | `27268870` | pylablib / Kinesis |
| Beam shutter | Thorlabs MFF002 controller/device | `37008491` | Thorlabs/Kinesis-compatible driver |
| Spectrometer | Ocean Insight Ocean SR | `SR600415` | seabreeze with `pyseabreeze` |

The exact class names and configuration object names in `hardware/config.py` remain authoritative.

### Power meter status: not integrated

There is currently no configured power meter. The repository contains no
verified meter model, serial number, driver/library choice, configuration
object, `HardwareManager` member, or experiment sampling call. The optional
power fields in the version-4 data format do not imply that power was measured.

When a real meter is added, preserve these meanings:

* `target_power_mw`: requested setpoint.
* `power_mw`: achieved mean power measured for the spectrum.
* `power_rms_mw`: the RMS statistic reported by the meter over
  `power_measurement_duration_s`.

Do not describe `power_rms_mw` as standard deviation unless the authoritative
meter documentation/API and verified acquisition implementation explicitly
define it that way. Record the meter model, serial, interface, units, sampling
method, and statistic definitions before using the values for publication.

Power-meter hardware integration must wait until the persistence and analysis
regressions pass. A first device test still requires explicit operator approval
and should connect only to the meter, query identity, take the smallest useful
read-only sample, and disconnect cleanly. Do not move stages or open the shutter
merely to test meter communication.

## Waveplate stage

### Purpose

The waveplate stage rotates a waveplate placed before a polariser.

Its angle controls transmitted optical power and therefore acts as the experimental intensity-control coordinate.

### Known configuration

- Model/scale used by the current working setup: PRM1-Z8.
- Serial number: `27268875`.
- Motion is expected to be blocking at the high-level driver interface.

### Safety

Before moving:

- Confirm that the requested position is within the physically safe range.
- Confirm that cables and mounts cannot collide.
- Avoid homing unless explicitly required.
- Do not assume that a power-safe angle is also mechanically safe.
- Do not infer absolute beam intensity from waveplate angle without calibration.

## Sample stage

### Purpose

The sample stage rotates the sample through the angular scan.

### Known configuration

- Model/scale used by the current working setup: PRM1-Z8.
- Serial number: `27268870`.
- Motion is expected to be blocking at the high-level driver interface.

### Safety

Before moving:

- Confirm mount clearance.
- Confirm the requested scan range.
- Consider cables, sample holders, optics, and nearby components.
- Use small controlled moves during testing.
- Do not home automatically.

## Beam shutter

### Purpose

The shutter blocks or exposes the beam.

It is used for:

- Safe idle state.
- Signal acquisition.
- Background acquisition.
- Failure cleanup.

### Known state mapping

This mapping was verified on the current hardware:

```text
State 0 = open
State 1 = closed
````

Do not reverse this mapping.

Use meaningful project-level methods such as:

```python
shutter.open()
shutter.close()
```

rather than exposing numeric states throughout experiment logic.

### Safe behaviour

* Assume closed is the safe default.
* Close the shutter during cleanup.
* Close the shutter after acquisition even if acquisition raises.
* Make `close()` safe to call repeatedly.
* Do not leave the shutter open while waiting for user input.
* Avoid toggling the shutter simply to discover its current state.

## Ocean SR spectrometer

### Purpose

The Ocean SR records the optical spectrum for each scan point.

### Known configuration

* Serial number: `SR600415`.
* Python interface: seabreeze.
* Working backend: `pyseabreeze`.

### Spectrum output

The project driver should return a canonical `Spectrum` containing:

* Wavelength array.
* Intensity array.
* Integration time in milliseconds.
* Spectrometer serial.
* Number of averages.
* Dark-correction flag.
* Nonlinearity-correction flag.
* Timestamp where supported.

### Saturation

Saturation should be assessed using raw detector values.

The software has commonly used `65535` counts as a warning threshold, but the authoritative saturation behaviour should be confirmed against the actual Ocean SR mode and driver output.

Do not use background-subtracted counts to decide whether the detector saturated.

### Integration time

The live utility may change integration time while running.

Background subtraction should account for changed integration time only when linear scaling is physically appropriate.

A new background should be captured when:

* Detector conditions change.
* Integration-time scaling is unreliable.
* Optical stray light changes.
* The detector temperature or environment changes materially.
* Correction settings change.
* The wavelength grid changes.

## Software stack

### Thorlabs rotation stages

The current working rotation-stage implementation uses pylablib with Thorlabs Kinesis support.

Earlier development explored:

* K10CR2 model handling.
* Direct use of Thorlabs .NET DLLs.
* A Cage Rotator implementation.
* Thorlabs Motion Control Python examples.

Those paths produced model-recognition and interface complications.

Do not reintroduce the Cage Rotator or direct-DLL implementation unless the current hardware configuration genuinely requires it.

### Thorlabs Kinesis

The host machine must have the necessary Thorlabs Kinesis software or libraries available for the chosen driver implementation.

Do not copy random DLL versions into the repository.

Keep machine-specific driver installation separate from source control.

### Ocean Insight seabreeze

The Ocean SR uses seabreeze with the `pyseabreeze` backend.

When debugging connection problems, distinguish between:

* USB visibility.
* Backend selection.
* Device serial selection.
* Driver ownership by another application.
* Integration-time or feature support.
* Spectrometer already open in another process.

## Configuration

Hardware serials and model settings should be defined centrally in:

```text
hardware/config.py
```

Experiment modules and tools should consume the configuration rather than duplicate serial numbers.

A standalone tool may accept a command-line serial override, but the configured default should remain clear.

## Hardware manager expectations

The hardware manager should own:

* Waveplate stage.
* Sample stage.
* Shutter.
* Spectrometer.

It does not currently own a power meter. Add one only after its real
configuration and lifecycle have been verified; keep partial-connection cleanup
and the safe closed-shutter state intact.

Connection should be coordinated so that partial failures are cleaned up.

Suggested safe strategy:

1. Construct devices.
2. Connect one at a time.
3. Record which devices connected successfully.
4. Ensure the shutter is closed once available.
5. If any later connection fails, disconnect already-connected devices.
6. Report the original failure.

## Hardware test classification

### Hardware-free

* Synthetic spectrum tests.
* Writer/loader round-trip tests.
* Mocked device tests.
* Data-model tests.
* Analysis tests.

### Spectrometer-only

* Live spectrometer utility.
* Single-spectrum acquisition test.
* Spectrometer metadata test.

### Future power-meter hardware

* Meter identity/configuration test.
* One read-only sample and units/statistics verification.
* Sampling-duration and meter-reported RMS verification.

These require explicit approval even if no stage motion or shutter operation is
intended. They must not be included in automatic hardware-free test runs.

### Motion hardware

* Waveplate move test.
* Sample-stage move test.
* Homing test.

### Shutter hardware

* Open/close test.
* State mapping verification.

### Full system

* Hardware manager connection test.
* Complete experiment.
* Background acquisition through the shutter.
* Coordinated scan.

Codex must not run any hardware category without explicit approval.

## Known historical issues

During earlier development, warnings included model mismatches and unrecognised Thorlabs motor models.

Examples included:

* A K10CR2 model not matching a device-prefix expectation.
* An MFF002 model not matching a generic MFF prefix.
* pylablib falling back to internal units for an unrecognised model.
* A direct .NET Cage Rotator implementation attempting to assign to a read-only `connected` property.

The current working configuration uses the established PRM1-Z8 stage path.

Treat historical experiments as context, not as instructions to revive obsolete code.

## Background capture procedure

For a detector or optical background:

1. Keep the same spectrometer settings intended for the measurement.
2. Block the signal beam using the appropriate safe method.
3. Wait for the detector signal to settle.
4. Acquire enough averages for a useful background.
5. Record integration time and correction flags.
6. Save the raw background.
7. Unblock the beam only after capture completes.
8. Confirm subtraction can be toggled.
9. Recapture when conditions change.

The persistent live-view background is a convenience calibration and should not replace explicit experiment backgrounds where reproducibility requires them.

````
