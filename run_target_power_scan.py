"""Run a sample-angle scan at requested measured incident powers.

The waveplate is adjusted by bounded feedback on one explicitly supplied
monotonic branch.  For each requested power, the retractable probe is inserted
once, remains inserted while all shutter-gated feedback traces are acquired,
and is retracted once before sample spectra are collected.

Example
-------
python run_target_power_scan.py \
    --sample-angles 0 10 20 \
    --target-powers-mw 2 5 10 \
    --waveplate-min-deg 0 \
    --waveplate-max-deg 12 \
    --direction increasing
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from experiments.experiment_config import ExperimentConfig



def collect_experimental_metadata(config: ExperimentConfig) -> None:
    """Collect run notes before importing or connecting hardware."""

    from experiments.experiment_config import OpticalFilterConfig

    print()
    print("Experimental metadata (press Enter to leave a field blank)")
    print("-" * 60)
    config.metadata.run_label = input("Run label: ").strip()
    config.metadata.sample_name = input("Sample name: ").strip()
    filter_names = [
        value.strip()
        for value in input(
            "Installed filters, comma separated (for example FBH400-40): "
        ).split(",")
        if value.strip()
    ]
    harmonics = [
        value.strip()
        for value in input(
            "Intended harmonics, comma separated (for example H5,H7): "
        ).split(",")
        if value.strip()
    ]
    config.metadata.intended_harmonics = harmonics
    for filter_name in filter_names:
        config.metadata.filters.append(
            OpticalFilterConfig(
                name=filter_name,
                intended_harmonics=harmonics.copy(),
            )
        )
    config.metadata.notes = input("Experiment notes: ").strip()
    print("-" * 60)

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scan sample rotation angles at requested incident powers. "
            "The waveplate search is restricted to one reviewed monotonic branch."
        )
    )
    parser.add_argument(
        "--sample-angles",
        type=float,
        nargs="+",
        required=True,
        help="Sample rotation angles in degrees.",
    )
    parser.add_argument(
        "--target-powers-mw",
        type=float,
        nargs="+",
        required=True,
        help="Requested incident powers in mW.",
    )
    parser.add_argument(
        "--waveplate-min-deg",
        type=float,
        required=True,
        help="Lower endpoint of one verified monotonic waveplate branch.",
    )
    parser.add_argument(
        "--waveplate-max-deg",
        type=float,
        required=True,
        help="Upper endpoint of one verified monotonic waveplate branch.",
    )
    parser.add_argument(
        "--direction",
        choices=("increasing", "decreasing"),
        required=True,
        help="Measured power trend as waveplate angle increases on this branch.",
    )
    parser.add_argument(
        "--tolerance-mw",
        type=float,
        default=0.2,
        help="Allowed absolute target error in mW (default: 0.2).",
    )
    parser.add_argument(
        "--maximum-iterations",
        type=int,
        default=8,
        help="Maximum feedback iterations per target after bracketing (default: 8).",
    )
    parser.add_argument(
        "--minimum-angle-step-deg",
        type=float,
        default=0.02,
        help="Smallest feedback angle resolution in degrees (default: 0.02).",
    )
    parser.add_argument(
        "--maximum-power-mw",
        type=float,
        default=20.0,
        help="Raw positive-reading safety ceiling in mW (default: 20).",
    )
    parser.add_argument(
        "--power-duration-s",
        type=float,
        default=10.0,
        help="Duration of each Ophir trace in seconds (default: 10).",
    )
    parser.add_argument(
        "--power-settle-s",
        type=float,
        default=3.0,
        help="Sensor settling time after each shutter opening (default: 3).",
    )
    parser.add_argument(
        "--integration-time-ms",
        type=float,
        default=10.0,
        help="Spectrometer integration time in ms (default: 10).",
    )
    parser.add_argument(
        "--averages",
        type=int,
        default=1,
        help="Spectra averaged per sample point (default: 1).",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path("results"),
        help="Parent output directory (default: results).",
    )
    parser.add_argument(
        "--experiment-name",
        default="target_power_rotation_scan",
        help="Saved experiment directory prefix.",
    )
    parser.add_argument(
        "--no-background",
        action="store_true",
        help="Disable the pre-scan shutter-closed spectrometer background.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the final typed RUN confirmation.",
    )
    return parser.parse_args()


def build_config(arguments: argparse.Namespace) -> ExperimentConfig:
    config = ExperimentConfig()

    config.spectrometer.integration_time_ms = arguments.integration_time_ms
    config.spectrometer.averages = arguments.averages
    config.background.enabled = not arguments.no_background

    config.power_meter.enabled = True
    config.power_meter.cadence = "per_intensity"
    config.power_meter.measurement_duration_s = arguments.power_duration_s
    config.power_meter.pre_measurement_settle_s = arguments.power_settle_s
    config.power_meter.maximum_allowed_power_mw = arguments.maximum_power_mw

    config.target_power.waveplate_min_deg = arguments.waveplate_min_deg
    config.target_power.waveplate_max_deg = arguments.waveplate_max_deg
    config.target_power.monotonic_direction = arguments.direction
    config.target_power.tolerance_mw = arguments.tolerance_mw
    config.target_power.maximum_iterations = arguments.maximum_iterations
    config.target_power.minimum_angle_step_deg = arguments.minimum_angle_step_deg

    config.saving.output_directory = arguments.output_directory
    config.saving.experiment_name = arguments.experiment_name

    config.power_meter.validate_for_run()
    config.target_power.validate_for_run(
        target_powers_mw=arguments.target_powers_mw,
        power_meter=config.power_meter,
    )
    return config


def print_run_summary(arguments: argparse.Namespace) -> None:
    print()
    print("=" * 72)
    print("TARGET-POWER ROTATION SCAN")
    print("=" * 72)
    print(f"Sample angles       : {arguments.sample_angles}")
    print(f"Target powers       : {arguments.target_powers_mw} mW")
    print(
        "Waveplate branch    : "
        f"[{arguments.waveplate_min_deg}, {arguments.waveplate_max_deg}] deg"
    )
    print(f"Power direction     : {arguments.direction}")
    print(f"Target tolerance    : +/- {arguments.tolerance_mw} mW")
    print(f"Maximum raw power   : {arguments.maximum_power_mw} mW")
    print(f"Power trace         : {arguments.power_duration_s} s")
    print(f"Power settle        : {arguments.power_settle_s} s")
    print(
        "Measurements        : "
        f"{len(arguments.sample_angles) * len(arguments.target_powers_mw)} spectra"
    )
    print("Final safe state    : shutter closed, power probe retracted")
    print("=" * 72)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    arguments = parse_arguments()
    config = build_config(arguments)
    collect_experimental_metadata(config)
    print_run_summary(arguments)

    if not arguments.yes:
        confirmation = input(
            "Type RUN to connect hardware and begin this scan: "
        ).strip()
        if confirmation != "RUN":
            print("Scan cancelled before hardware connection.")
            return

    # Delay hardware-facing imports until after the explicit operator
    # confirmation so --help and cancelled runs cannot load vendor drivers.
    from experiments.experiment_controller import ExperimentController
    from experiments.rotation_intensity_scan import RotationIntensityExperiment

    ExperimentController(
        config=config,
        experiment=RotationIntensityExperiment(),
    ).run(
        sample_angles=arguments.sample_angles,
        target_powers_mw=arguments.target_powers_mw,
    )


if __name__ == "__main__":
    main()
