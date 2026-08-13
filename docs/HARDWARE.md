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
| Power-meter insertion | PI V-408.132020 on C-891.120200, axis 1 | `118054611` | PIPython / 64-bit PI GCS2 DLL |
| Incident-power controller | Ophir Juno | `3144168` | StarLab `OphirLMMeasurement` COM via pywin32 |
| Incident-power sensor | Ophir 3A-P-V1 thermopile | `3141552` | Juno channel 0 |

The exact class names and configuration object names in `hardware/config.py` remain authoritative.

### Optical order and retractable power probe

The fixed order for this experiment is:

```text
laser -> waveplate -> polariser -> shutter -> power meter -> sample
```

The shutter is always before the meter. The probe sequence implemented by
`hardware/power_probe.py:RetractablePowerProbe` is:

```text
close and verify shutter
-> move meter in and verify position
-> open and verify shutter
-> settle and stream power
-> close and verify shutter
-> move meter out and verify position
```

The code never moves the insertion stage after an unverified shutter close.
Every sample-spectrum shutter opening has a live out-position guard. A meter
read failure is considered recoverable only after the shutter-closed out state
has been verified.

### Ophir meter: live-verified identity and settings

An approved live connection verified:

* Controller: Juno, serial `3144168`, ROM `JN1.53`.
* Sensor: thermopile 3A-P-V1, serial `3141552`, channel 0.
* Measurement mode: `Power`.
* Returned wavelength options: `<800`, `>800`.
* Returned range options: `AUTO`, `3.00W`, `300mW`, `30.0mW`, `3.00mW`,
  `300uW`.

The experiment records the physical fundamental wavelength separately as
2000 nm while selecting the sensor's coarse returned option `>800`. The default
range is `AUTO`; the independent raw-power safety ceiling controls whether an
experiment may continue. Reverify the returned option names if the sensor is changed; the
driver selects by returned name and verifies readback rather than hardcoding a
fragile list index. A different fixed range can be selected explicitly in the
experiment config, but no safety limit is inferred from a requested power setpoint.

The stated operating context is a 1 kHz source, approximately 5 mm beam at the
sensor, and anticipated meter readings within roughly 0--50 mW. The current
sample/focusing geometry may damage near 20 mW, so the experiment software uses
20 mW as the stricter interlock unless deliberately reconfigured after a safety
review. Repetition rate and beam size are metadata/context only; the current
software does not derive pulse energy, fluence, or peak intensity from them.

One approved 10 s shutter-closed trace at `>800` and `30.0mW` returned 138/138
valid samples: mean `0.0594928 mW`, population STD `0.00219435 mW`, and absolute
RMS `0.0595332 mW`. This is a recorded dark/offset observation, not an automatic
zero correction. The acquisition and analysis paths do not subtract it or
silently force it to zero.

Raw meter data originate in watts. A reading is valid for statistics only when
its value and timestamp are finite, its power is strictly positive, and its
raw status maps to `ok`. Zero, negative, missing, non-finite, and status-flagged
samples are retained with invalid reasons and excluded; no value is predicted
or substituted. The implemented statistics are:

* `power_mw`: arithmetic mean of valid samples.
* `power_std_mw`: population standard deviation, denominator `N`.
* `power_rms_mw`: absolute RMS, `sqrt(mean(power**2))`.

If no valid sample remains, all three values are `None`. RMS is not the
uncertainty; use the separate population STD as the trace spread.

Power acquisition is disabled by default. When enabled, the standard cadence
is `per_intensity`: set the waveplate, take one 10 s trace after 3 s sensor
settling, retract, then reuse that trace for every sample angle in the block.
`per_measurement` takes a fresh trace before each spectrum and `disabled` takes
none. A failed or all-invalid trace aborts by default; continuation with missing
power requires the explicit `continue_without_power_on_meter_error=True` opt-in.
Any non-finite power value or status-flagged sample makes the trace unsafe, and
any finite positive raw sample above 20 mW trips the interlock. Those cases always
abort before an illuminated spectrum, even if other samples or the mean are
below the limit.

### PI insertion stage: live connection and small motion verified

Configured hardware:

* Controller: C-891.120200, serial `118054611`.
* Live identity: C-891.120200, serial `118054611`, firmware `02.012`.
* Live stage assignment: V-408.132020.
* Axis: `1`.
* Application envelope: -12 to +12 mm, additionally intersected with live
  `TMN?`/`TMX?` controller limits for every move.
* Final-position tolerance: 0.01 mm; motion timeout: 30 s.

After fully terminating a hidden PIMikroMove process, PIPython connected to the
exact enumerated controller and verified axis 1. Live readback reported:

* `FRF? = true` (already referenced; no reference/home command was issued).
* Motor enabled and servo initially disabled.
* Controller travel limits -12.5 to +12.5 mm; the narrower application envelope
  remains -12 to +12 mm.
* Initial `VEL? = 200 mm/s`.

With the shutter verified closed, closed-loop preparation enabled the servo;
the controller target readback then matched the current position without any
reference motion. A single +0.100 mm absolute move and return to the observed starting position
succeeded, with the final return within the configured 0.01 mm tolerance. The
shutter began and ended closed.

The configured `velocity_mm_s=1.0` is a maximum startup velocity. The driver
reduces a faster live value to 1 mm/s and verifies readback before closed-loop
preparation; if the controller is already slower, it retains that safer value.
It never speeds the axis up automatically.

The supplied `C-891-UserManual-MS251E.pdf` is not an exact model manual: its
stated scope is C-891.130300, although C-891.120200 appears in examples/updater
material. It is useful for general GCS guidance only; every command and state
assumption for this controller must be checked against live readback and the
correct controller documentation.

The driver deliberately does not reference/home, run a startup helper, perform
phase finding, select a stage database record, redefine position, or write
persistent parameters. Connection validates `*IDN?`, active axis, and `CST?`,
then captures read-only state. Closed-loop enable is allowed only when `FRF?` is
already true. The only velocity write is the guarded, readback-verified startup
reduction described above. Motion is a bounded absolute `MOV`, waits for
`ONT?`, verifies `POS?`, and attempts a smooth `HLT` after motion failure.
Disconnect closes the GCS connection without disabling the motor or servo;
that preserves the user-approved controller state.

The current configuration contains candidate positions
`in_position_mm=+1.0` and `out_position_mm=-1.0`. They must be checked on the
physical setup before automatic use. `HardwareManager` can reject missing or
indistinguishable values, but it cannot detect a collision or determine whether
the sensor is truly centred/clear. Do not use automatic reference motion to
create these coordinates.

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

### PI Software Suite and PIPython

The reusable PI driver imports PIPython only when a real connection is
requested. The host needs the 64-bit PI GCS2 DLL installed by PI Software
Suite. The tested Python dependency is `PIPython==2.11.0.6`.

PIMikroMove and Python should not own the controller simultaneously. A PI error
`-9` during `ConnectUSB` while PIMikroMove is still running should be treated as
an ownership/connection failure, not as permission to retry motion or alter
controller parameters.

### Ophir StarLab COM

The Juno driver uses the registered
`OphirLMMeasurement.CoLMMeasurement` COM server supplied with StarLab through
`pywin32==312`. Connection, configuration, streaming, data retrieval, and
cleanup must remain on the same thread because COM is apartment-threaded.
Close StarLab before Python opens the Juno.

The pinned Python hardware dependencies are recorded in
`requirements-hardware.txt`; vendor runtimes remain machine installations and
must not be copied into the repository.

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
* The PI insertion stage whenever it is physically marked installed.
* The Ophir power meter when experiment power sampling is enabled.
* The `RetractablePowerProbe` coordinator.

Connection should be coordinated so that partial failures are cleaned up.

Implemented safe strategy:

1. Validate configured in/out positions before connecting anything.
2. Connect the shutter first and close it.
3. Connect other devices one at a time and track partial ownership.
4. Connect the PI stage, require an already referenced axis, enable motor/servo
   if required, and retract/verify the probe before any acquisition.
5. Connect Ophir last when enabled.
6. On failure, close the shutter, safely retract if closure is verifiable, or
   halt without motion if it is not, then disconnect in reverse order.
7. Preserve the original exception while reporting any safe-state failure.

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

### Power-meter hardware

* Meter identity/configuration test.
* One read-only or shutter-closed stream and units/statistics verification.
* Sampling-duration, population-STD, and absolute-RMS verification.

### PI insertion-stage hardware

* USB connection and read-only state queries.
* Closed-loop enable on an already referenced axis.
* Any insertion, retraction, or small reversible move.

Never combine a first PI connection attempt with reference motion. Before any
motion, state the exact start, target, maximum displacement, effective limits,
and return position, and verify that the shutter begins and ends closed.

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
* Coordinated power insertion, measurement, retraction, and sample acquisition.

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
