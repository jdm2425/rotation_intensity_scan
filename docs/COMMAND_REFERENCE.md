# Command Reference

This is the central reference for commands normally used at the experiment.
Update it whenever a runnable command, option, default, or safety behaviour
changes. For the parser's exact current syntax, append `--help` to a command.

PowerShell examples use a backtick at the end of a continued line. There must
be no spaces after the backtick.

## Safety levels

- **Offline:** no hardware connection.
- **Read-only hardware:** connects to a device but does not intentionally move
  it or expose the beam.
- **Hardware motion/acquisition:** can move stages, insert the probe, open the
  shutter, or acquire from physical devices. Keep an operator present.
- `--yes` skips typed confirmation; use it only when the command has already
  been reviewed.
- Shutter state `0` is open and state `1` is closed.
- The Ophir range and a power safety ceiling are different settings. `AUTO`
  chooses a supported meter range; it does not disable experiment safety.

## 1. Full target-power rotation scan

**Hardware motion/acquisition.** Connects the complete experiment, targets
measured incident powers, rotates the sample, acquires spectra, and saves data.

```powershell
python run_target_power_scan.py `
    --sample-angles 0 10 20 `
    --target-powers-mw 5 5.5 6 `
    --waveplate-min-deg 75 `
    --waveplate-max-deg 114 `
    --direction increasing `
    --maximum-power-mw 30 `
    --experiment-name MyExperiment
```

Required inputs:

- `--sample-angles`: sample-stage angles in degrees, separated by spaces.
- `--target-powers-mw`: requested powers in mW, separated by spaces.
- `--waveplate-min-deg`, `--waveplate-max-deg`: reviewed endpoints of one
  monotonic optical branch.
- `--direction increasing|decreasing`: power trend as waveplate angle rises.

Optional inputs:

- `--tolerance-mw`: acceptable target error; default `0.2` mW.
- `--maximum-iterations`: feedback iterations after bracketing; default `8`.
- `--minimum-angle-step-deg`: minimum feedback resolution; default `0.02`°.
- `--power-calibration PATH`: Malus calibration used for the first guess only.
- `--maximum-power-mw`: hard raw-sample experiment ceiling; default `20` mW.
  Targets above it are rejected and raw overshoot aborts before spectra.
- `--power-duration-s`: each Ophir trace duration; default `10` s.
- `--power-settle-s`: wait after shutter opening; default `3` s.
- `--integration-time-ms`: spectrometer integration time; default `10` ms.
- `--averages`: spectra averaged internally per acquisition; default `1`.
- `--spectra-per-point`: independent saved spectra per point; default `1`.
  Use more than one for vertical replicate error bars.
- `--output-directory`: output parent; default `results`.
- `--experiment-name`: saved directory prefix.
- `--no-background`: skip the pre-scan shutter-closed background.
- `--yes`: skip typed `RUN` confirmation.

Exact help:

```powershell
python run_target_power_scan.py --help
```

## 2. PowerShell full-scan wrapper

**Hardware motion/acquisition.** This is a convenient editable wrapper around
`run_target_power_scan.py`:

```powershell
.\run_full_power_rotation_scan.ps1
```

Edit these variables near the top of the file:

```powershell
$sampleAngles = 327

$targetPowers = for ($power = 5; $power -le 10; $power += 0.5) {
    $power
}

$waveplateMinimum = 75
$waveplateMaximum = 114
```

PowerShell comparison `-le` means “less than or equal”; its first character is
a lowercase letter L, not the number 1.

Edit the options in the final Python command for tolerance, ceiling,
integration time, averages, replicates, calibration, and experiment name.

## 3. Fixed waveplate-angle scan

**Hardware motion/acquisition.** The maintained fixed-angle entry point is:

```powershell
python run_rotation_intensity.py
```

It currently has no CLI arguments. Edit `sample_angles`, `waveplate_angles`,
and the `ExperimentConfig` construction in that file before use.
`run_rotation_intensity_scan.py` is only a compatibility wrapper.

## 4. Standalone power-probe diagnostic

### Inspect

**Read-only hardware.** Connects shutter, PI stage, and Ophir meter, closes the
shutter, reports identity/state, and does not intentionally move the stage:

```powershell
python -m tools.test_power_probe_hardware inspect
```

Options:

- `--wavelength-option`: exact Ophir option; default `>800`.
- `--range-option`: exact Ophir range; default `AUTO`. For a fixed range use,
  for example, `--range-option "30.0mW"`.

### Measure traces

**Hardware motion/acquisition.** Inserts once, records traces, retracts once:

```powershell
python -m tools.test_power_probe_hardware measure --traces 3
```

Options:

- `--traces`: number of saved traces; default `1`.
- `--duration-s`: trace duration; default `3` s.
- `--initial-settle-s`: first-trace settling; default `5` s.
- `--settle-s`: later-trace settling; default `3` s.
- `--poll-interval-s`: meter polling interval; default `0.1` s.
- `--between-trace-delay-s`: shutter-closed delay; default `0` s.
- `--range-option`: `AUTO` by default; fixed values include `30.0mW` and
  `300mW` when returned by this sensor.
- `--maximum-power-mw`: optional diagnostic warning threshold. It does not
  abort by itself.
- `--abort-above-maximum`: make the diagnostic threshold abort after saving
  the trace.
- `--in-position-mm`, `--out-position-mm`: reviewed position overrides.
- `--output-directory`: trace output parent.

Warn above 20 mW but continue:

```powershell
python -m tools.test_power_probe_hardware measure `
    --traces 3 `
    --maximum-power-mw 20
```

### Move PI stage

**Hardware motion.** Moves to a reviewed absolute position and normally
returns to the starting position:

```powershell
python -m tools.test_power_probe_hardware move --position-mm 0.5
```

- `--leave-at-target`: do not return to the starting position.

Full help:

```powershell
python -m tools.test_power_probe_hardware --help
python -m tools.test_power_probe_hardware measure --help
```

## 5. Map waveplate power

**Hardware motion/acquisition.** Measures power across a reviewed interval,
saves CSV/raw traces/a plot, recommends a monotonic branch, and creates
`malus_calibration.json`. It does not search for mechanical end stops.

```powershell
python -m tools.waveplate_power_control scan `
    --scan-start-deg 70 `
    --scan-stop-deg 115 `
    --step-deg 1 `
    --raw-power-ceiling-mw 30
```

Options:

- `--scan-start-deg`, `--scan-stop-deg`: reviewed scan endpoints.
- `--step-deg`: angular step.
- `--noise-tolerance-mw`: tolerated reversal when finding branches; default
  `0.1` mW.
- `--duration-s`: trace duration; default `3` s.
- `--initial-settle-s`: first trace wait; default `5` s.
- `--settle-s`: later trace wait; default `3` s.
- `--poll-interval-s`: default `0.1` s.
- `--range-option`: default `AUTO`; may be set to `"30.0mW"`, for example.
- `--raw-power-ceiling-mw`: hard raw-sample ceiling; default `50` mW.
- `--output-directory`: output parent.

## 6. Set power within a range

**Hardware motion/acquisition.** Uses bounded feedback and leaves the
waveplate at a measured power inside the requested interval:

```powershell
python -m tools.waveplate_power_control set-range `
    --minimum-power-mw 6.9 `
    --maximum-power-mw 7.2 `
    --waveplate-min-deg 75 `
    --waveplate-max-deg 114 `
    --direction increasing `
    --calibration results\waveplate_power_control\scan_NAME\malus_calibration.json `
    --raw-power-ceiling-mw 30
```

- `--calibration`: optional improved first guess; omit it for the original
  interpolation/bisection method.
- `--maximum-iterations`: default `8`.
- `--minimum-angle-step-deg`: default `0.02`°.
- Acquisition/range/ceiling options are the same as the mapping command.

Full help:

```powershell
python -m tools.waveplate_power_control scan --help
python -m tools.waveplate_power_control set-range --help
```

## 7. Fit an existing waveplate calibration CSV

**Offline.** Creates a calibration JSON without connecting hardware:

```powershell
python -m tools.fit_waveplate_calibration `
    results\waveplate_power_control\scan_NAME\waveplate_power.csv `
    --waveplate-min-deg 75 `
    --waveplate-max-deg 114 `
    --direction increasing `
    --output results\waveplate_power_control\scan_NAME\malus_calibration_75_114.json
```

- `csv_path`: positional path to `waveplate_power.csv`.
- `--output`: optional JSON path; otherwise saves beside the CSV.

## 8. Analyse a saved experiment

**Offline.** Integrates harmonic windows and creates publication-data CSVs and
plots without modifying acquisition data:

```powershell
python -m tools.analyse_experiment `
    results\Experiment_Name `
    --harmonic H5:390:410 `
    --use-background `
    --no-transmission-correction `
    --plot-all `
    --polar
```

Inputs:

- `experiment_directory`: first positional path.
- `--harmonic NAME:MIN_NM:MAX_NM`: repeat for multiple harmonic windows.
- `--use-background [NAME]`: subtract a saved background; default name is
  `pre_scan_dark`.
- `--no-background`: explicitly use no background.
- `--transmission-fraction`: scalar fraction in `(0, 1]`.
- `--transmission-curve`: CSV with wavelength and transmission fraction.
- `--no-transmission-correction`: explicitly use no transmission correction.
- `--sample-angle`: create an input scan at one sample angle; repeatable.
- `--input-coordinate`: one of `waveplate_angle_deg`, `power_mw`,
  `fluence_mj_cm2`, or `intensity_w_cm2`. Default is achieved power when
  complete, otherwise waveplate angle.
- `--input-value`: create a rotation plot at a selected coordinate value;
  repeatable.
- `--input-tolerance`: absolute matching tolerance; default `1e-6`.
- `--waveplate-angle`: legacy angle-selection alias.
- `--signal`: plotted derived quantity. Choices are `integrated_signal`,
  `raw_integrated_signal`, `background_corrected_integral`, `peak_signal`, and
  `raw_peak_signal`.
- `--plot-all`: create all available input and rotation plots.
- `--polar`: also create polar rotation plots.
- `--normalise`: normalise each harmonic series.
- `--save-pdf`: add PDF output; default output is PNG plus exact CSV.
- `--power-decimal-places`: display/filename precision; default `1`. CSV/JSON
  retain full precision.
- `--annotate-corrections` / `--no-annotate-corrections`: toggle figure footer.
- `--output-directory`: choose the analysis output folder.

## 9. Live spectrometer

**Hardware acquisition.** Connects only the Ocean SR and opens a live plot:

```powershell
python -m tools.live_spectrometer
```

CLI inputs:

- `--serial`: spectrometer serial.
- `--integration-time-ms`: initial integration time; default `10` ms.
- `--averages`: default `1`.
- `--output-directory`: save directory used by the `S` key.
- `--refresh-interval`: plot refresh pause; default `0.05` s.
- `--x-min`, `--x-max`, `--y-min`, `--y-max`: initial axes.
- `--saturation-level`: warning threshold; default `65535` counts.

Important keyboard controls are printed in the terminal after startup. `B`
captures/replaces the live background, `G` toggles subtraction, `S` saves, and
the quit key closes the utility cleanly.

## 10. Laser-off target-scan order test

**Hardware motion; optional dark acquisition.** This is a commissioning tool,
not a normal regression test:

```powershell
python -m tools.test_target_power_scan_hardware `
    --laser-off `
    --sample-angles 0 10 `
    --simulated-target-powers-mw 5 7 `
    --waveplate-angles 80 90
```

- `--laser-off`: required operator assertion.
- `--simulated-target-powers-mw`: labels only; no feedback targeting.
- `--waveplate-angles`: one reviewed angle per simulated power.
- `--exercise-optical-paths`: opens the shutter with the laser asserted off to
  acquire dark power traces and spectra.
- `--leave-rotation-stages`: otherwise stages return to starting positions.
- Power duration, settling, spectrometer, range, output, and `--yes` options
  are available; use `--help` for their exact current defaults.

## 11. Custom intensity plotting script

**Offline.** `analysis/plot_harmonic_intensity_data_after_analysis_code.py`
currently has no command-line parser. Edit its input CSV path, beam parameters,
selected signal column, and plotting choices inside the file before running:

```powershell
python analysis\plot_harmonic_intensity_data_after_analysis_code.py
```

## Quick help rule

Before using an unfamiliar command:

```powershell
python -m MODULE_NAME --help
```

For commands with subcommands, put `--help` after the subcommand:

```powershell
python -m tools.test_power_probe_hardware measure --help
python -m tools.waveplate_power_control scan --help
```
