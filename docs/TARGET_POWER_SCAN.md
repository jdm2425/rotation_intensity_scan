# Target-Power Rotation Scans

## Status

Closed-loop target-power scan support is implemented in software and covered by
hardware-free fake-device tests.  It has **not** been validated on the complete
physical apparatus.

The maintained angle-controlled entry point remains:

```powershell
python run_rotation_intensity.py
```

The new target-power entry point is:

```powershell
python run_target_power_scan.py --help
```

## Critical physical prerequisite

`hardware/config.py` currently contains:

```python
in_position_mm=1.0
out_position_mm=-1.0
```

Only use these values if they are the physically established positions for this
exact setup:

- `in_position_mm`: the power sensor is correctly centred in the incident beam.
- `out_position_mm`: the sensor and mount are fully clear of the sample beam.

The positions must be distinct, inside the live PI limits, and verified with the
shutter closed.  Documentation in the uploaded repository still stated that
these positions were unverified, so the code and documentation disagree.

Do not run the full experiment until that discrepancy is resolved.

## Why a waveplate branch is required

Waveplate-plus-polariser transmission is periodic and is not globally
monotonic.  A target-power feedback loop therefore needs one explicit branch
where measured power changes in only one direction as waveplate angle
increases.

You must supply:

- `--waveplate-min-deg`
- `--waveplate-max-deg`
- `--direction increasing` or `--direction decreasing`

The controller never commands a waveplate angle outside those bounds.

The branch endpoints must themselves be safe.  The controller measures both
endpoints to establish a real power bracket before targeting the first power.

## Recommended branch-establishment scan

First use the existing angle-controlled experiment with the power meter enabled
and only one sample angle.  Select a small set of reviewed waveplate angles on
the intended branch.  Confirm that achieved power is monotonic and below the
configured safety ceiling.

For example, edit `run_rotation_intensity.py` temporarily so that:

```python
config.power_meter.enabled = True
config.power_meter.cadence = "per_intensity"

sample_angles = [0.0]
waveplate_angles = [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]
```

This is only an example grid.  Use angles appropriate to the physical setup.

After the run, inspect `measurements.csv` and identify a strictly increasing or
strictly decreasing safe interval.  Use that interval in the target-power
command.

## Target-power command

Example syntax:

```powershell
python run_target_power_scan.py `
    --sample-angles 0 10 20 `
    --target-powers-mw 2 5 10 `
    --waveplate-min-deg 0 `
    --waveplate-max-deg 10 `
    --direction increasing `
    --tolerance-mw 0.2 `
    --maximum-power-mw 20
```

The numerical values above are examples, not verified settings for the real
experiment.

The script prints the complete scan summary and requires the operator to type:

```text
RUN
```

before it imports hardware-facing modules or connects devices.

## Feedback sequence

For each requested target power, the software:

1. Restricts the search to the configured waveplate branch.
2. Closes and verifies the beam shutter.
3. Inserts and verifies the PI-mounted power probe **once**.
4. For each endpoint or candidate angle:
   - closes and verifies the shutter;
   - verifies that the probe is still at the configured in position;
   - moves the waveplate using blocking motion;
   - opens and verifies the shutter;
   - waits for the configured sensor settling time;
   - acquires a real Ophir power trace;
   - closes and verifies the shutter again without retracting the probe.
5. Checks raw meter status and the maximum-power interlock after every trace.
6. Uses bounded interpolation/bisection to choose the next candidate.
7. Stops when achieved mean power is within the requested tolerance.
8. Closes the shutter and retracts/verifies the probe **once** when the target
   block finishes or raises.
9. Reuses the successful final power trace for every sample angle in that
   target-power block.
10. Acquires spectra only with the power probe verified out of the sample beam.

The controller measures both branch endpoints afresh for each requested power,
so it does not trust a stale bracket from an earlier target block.  This costs
extra traces but keeps power drift from silently invalidating the search.

If the target is not bracketed, a meter trace is invalid, the raw power exceeds
the configured ceiling, or convergence fails, the scan aborts rather than
inventing a power or acquiring a spectrum at an unknown setting.  Session
cleanup still closes the shutter and attempts one verified retraction.

## Saved data

Every spectrum row records:

- `target_power_mw`: requested setpoint.
- `power_mw`: achieved arithmetic-mean power.
- `waveplate_angle_deg`: final angle used for the sample spectra.
- Power standard deviation and RMS.
- Power measurement duration.
- Attempt and trace identifiers.
- Status, errors, and sample counts.

Every feedback attempt is saved immediately, including intermediate endpoint
and candidate measurements.  Raw power traces are stored separately under the
experiment's `power_measurements/` directory.

## Important command options

```text
--tolerance-mw
```

Absolute acceptable difference between requested and achieved mean power.
Start conservatively; the tolerance must be larger than realistic meter noise
and drift.

```text
--maximum-iterations
```

Maximum feedback iterations after bracketing.  The probe remains inserted,
but every iteration still includes shutter gating, settling, and a full power
trace, so excessive values can make a run very slow.

```text
--power-duration-s
--power-settle-s
```

Ophir trace and settling durations.  The uploaded configuration used 10 s and
3 s.  Do not shorten them without verifying measurement stability.

```text
--maximum-power-mw
```

Raw positive-sample safety ceiling.  Any raw reading above this value aborts
before a sample spectrum is acquired.

```text
--no-background
```

Disables the shutter-closed pre-scan spectrometer background.  Normally leave
background acquisition enabled.


## Standalone PI/Ophir hardware test

A dedicated operator-controlled utility connects only the shutter, PI stage,
and Ophir meter:

```powershell
python -m tools.test_power_probe_hardware --help
```

Read identities and the current PI state without motion:

```powershell
python -m tools.test_power_probe_hardware inspect
```

Move to one reviewed absolute position and return to the starting position:

```powershell
python -m tools.test_power_probe_hardware move --position-mm 0.5
```

Record several traces during one insertion, then retract once:

```powershell
python -m tools.test_power_probe_hardware measure `
    --traces 3 `
    --duration-s 3 `
    --settle-s 1
```

The utility prints the exact devices and motion before connection and requires
the operator to type `RUN`.  Trace CSV and JSON summaries are written under
`results/power_probe_hardware_tests/`.

Use the `move` command to establish safe physical coordinates before relying
on `hardware.config.POWER_METER_STAGE.in_position_mm` and
`out_position_mm`.  The script does not connect either rotation stage or the
spectrometer.

## Preflight tests

Hardware-free:

```powershell
python -m tests.test_round_trip
python -m tests.test_power_trace_round_trip
python -m tests.test_target_power_experiment_workflow
python run_target_power_scan.py --help
```

Then perform supervised physical validation in increasing scope:

1. Verify the PI probe in/out positions with the shutter closed.
2. Verify one Ophir trace with the probe inserted and safe optical power.
3. Run one target power and one sample angle.
4. Inspect the saved `measurements.csv`, power attempts, traces, shutter state,
   and probe out position.
5. Run two target powers and one sample angle.
6. Only then run the full target-power/sample-angle grid.

## Minimal one-point hardware command

Replace the branch and power values with physically verified values:

```powershell
python run_target_power_scan.py `
    --sample-angles 0 `
    --target-powers-mw 2 `
    --waveplate-min-deg 0 `
    --waveplate-max-deg 10 `
    --direction increasing `
    --tolerance-mw 0.2 `
    --experiment-name target_power_one_point
```

After completion, verify:

- The beam shutter is closed.
- The power probe is physically out.
- Exactly one spectrum was saved.
- `target_power_mw`, `power_mw`, and `waveplate_angle_deg` are populated.
- `abs(power_mw - target_power_mw)` is within the configured tolerance.
