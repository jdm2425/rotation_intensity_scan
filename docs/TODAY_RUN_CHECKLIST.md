# Same-Day Commissioning and Run Checklist

This checklist is intentionally staged. Do not make the first physical command
a full target-power scan.

## 1. Preserve the current repository

```powershell
git status
git add .
git commit -m "Checkpoint before persistent target-power patch"
git switch -c feature/persistent-target-power
```

Apply the supplied patch from the repository root:

```powershell
git apply --check .\rotation_intensity_scan_persistent_target_power.patch
git apply .\rotation_intensity_scan_persistent_target_power.patch
```

## 2. Activate the existing environment

```powershell
.\.venv\Scripts\Activate.ps1
python -c "import sys; print(sys.executable)"
```

Close StarLab and PIMikroMove before connecting their USB devices.

## 3. Run the software-only checks

```powershell
python -m tests.test_power_probe
python -m tests.test_target_power_experiment_workflow
python -m tests.test_power_experiment_workflow
python -m tests.test_power_trace_round_trip
python -m tests.test_round_trip
```

## 4. Inspect the PI stage and Ophir meter

This command does not move the PI stage:

```powershell
python -m tools.test_power_probe_hardware inspect
```

Confirm:

- PI controller serial `118054611`.
- Stage assignment `V-408.132020`.
- Axis already referenced.
- Live position and limits are plausible.
- Ophir controller `3144168` and sensor `3141552` are detected.
- Returned wavelength/range settings match `>800` and `30.0mW`.

## 5. Verify candidate PI positions

The repository currently contains candidate positions:

```text
in  = +1.0 mm
out = -1.0 mm
```

Use small reviewed moves with the laser off. The move command returns to its
starting position unless `--leave-at-target` is explicitly supplied:

```powershell
python -m tools.test_power_probe_hardware move --position-mm -1.0
python -m tools.test_power_probe_hardware move --position-mm 1.0
```

Confirm physically that the out coordinate clears the complete sensor/mount
from the sample beam and that the in coordinate centres the sensor safely.
Update `hardware/config.py` if the physical coordinates differ.

## 6. Test one persistent probe measurement session

With the laser still off, this verifies insertion, shutter gating, three traces,
and one retraction:

```powershell
python -m tools.test_power_probe_hardware measure `
    --traces 3 `
    --duration-s 2 `
    --settle-s 0.5
```

Inspect the files under:

```text
results/power_probe_hardware_tests/
```

Then repeat with a safely attenuated beam when ready.

## 7. Establish a monotonic waveplate branch

A target-power scan cannot safely search the complete periodic waveplate range.
Use a small fixed-angle scan with power metering enabled and one sample angle.
Choose endpoints which are both physically safe and where power changes in one
direction only.

Record:

- Lower waveplate angle.
- Upper waveplate angle.
- Whether power is `increasing` or `decreasing` with angle.
- Power measured at each endpoint.
- Maximum permitted power.

Every target must lie between the freshly measured endpoint powers.

## 8. Run one target and one sample angle

Replace every placeholder with verified values:

```powershell
python run_target_power_scan.py `
    --sample-angles 0 `
    --target-powers-mw YOUR_LOW_SAFE_TARGET `
    --waveplate-min-deg YOUR_BRANCH_MIN `
    --waveplate-max-deg YOUR_BRANCH_MAX `
    --direction increasing `
    --tolerance-mw 0.2 `
    --maximum-power-mw YOUR_REVIEWED_LIMIT `
    --power-duration-s 3 `
    --power-settle-s 1 `
    --experiment-name target_power_one_point
```

Use `--direction decreasing` when appropriate.

After completion confirm:

- Shutter is closed.
- Probe is physically out.
- One spectrum exists.
- `measurements.csv` contains `target_power_mw`, achieved `power_mw`, and
  `waveplate_angle_deg`.
- Absolute target error is within the chosen tolerance.
- `power_attempts.json` and raw trace files exist.

## 9. Expand gradually

Next run two target powers with one sample angle. Only then run the full target
power by sample-angle grid.

The target search inserts the probe once per requested power, keeps it inserted
for all feedback traces, retracts it once, and then scans every sample angle.
