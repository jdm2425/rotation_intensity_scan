# Laser-Off Target-Power Hardware-Order Test

The target-power experiment already uses **power as the outer loop**:

```text
for each requested power:
    insert the power probe once
    find the waveplate angle by feedback
    retract the probe once
    rotate through every requested sample angle
    acquire one spectrum at each sample angle
```

`tools/test_target_power_scan_hardware.py` exercises that same mechanical order
without attempting power feedback. It uses one reviewed waveplate angle for
each simulated power block, so it can be run while the laser is off.

## Movement-only commissioning test

This mode keeps the shutter closed for the complete run. It connects all
configured hardware, inserts and retracts the PI probe once per simulated power
block, moves the waveplate, then moves the sample through the full angle list.

```powershell
python -m tools.test_target_power_scan_hardware `
    --laser-off `
    --sample-angles -5 0 5 `
    --simulated-target-powers-mw 2 5 `
    --waveplate-angles 1 4
```

The simulated powers are labels only. No power convergence is attempted.

## Exact optical-path order with the laser off

To additionally open the shutter for one dark Ophir trace per block and one
dark spectrum per sample angle:

```powershell
python -m tools.test_target_power_scan_hardware `
    --laser-off `
    --sample-angles -5 0 5 `
    --simulated-target-powers-mw 2 5 `
    --waveplate-angles 1 4 `
    --exercise-optical-paths
```

Only use `--exercise-optical-paths` after independently confirming the laser
source is off. The program cannot detect laser state.

## Output

A timestamped directory is written under:

```text
results/target_power_hardware_order_tests/
```

It contains:

- `hardware_order_log.json`, a chronological record of every action.
- One Ophir trace CSV and summary per simulated power block when optical paths
  are exercised.
- One dark spectrum per sample angle when optical paths are exercised.

By default the tool returns both rotation stages to their starting positions.
Use `--leave-rotation-stages` only when deliberately required.

The final requested state is always shutter closed and power probe retracted.
The hardware context performs another cleanup attempt during disconnect.

## Before running

Confirm all of the following:

- The PI stage is referenced.
- `in_position_mm` and `out_position_mm` are physically correct.
- All sample and waveplate test angles are mechanically safe.
- The translation-stage path is unobstructed.
- The configured stage velocity is appropriate.
- No vendor application currently owns any device.
