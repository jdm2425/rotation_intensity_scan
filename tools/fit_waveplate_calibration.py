"""Fit and save a Malus-law calibration from a waveplate-power CSV."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from experiments.waveplate_calibration import fit_malus_calibration


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--waveplate-min-deg", type=float, required=True)
    parser.add_argument("--waveplate-max-deg", type=float, required=True)
    parser.add_argument(
        "--direction",
        choices=("increasing", "decreasing"),
        required=True,
    )
    parser.add_argument("--output", type=Path, default=None)
    arguments = parser.parse_args()

    angles: list[float] = []
    powers: list[float] = []
    with arguments.csv_path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            angles.append(float(row["angle_deg"]))
            powers.append(float(row["power_mw"]))

    calibration = fit_malus_calibration(
        angles,
        powers,
        waveplate_min_deg=arguments.waveplate_min_deg,
        waveplate_max_deg=arguments.waveplate_max_deg,
        monotonic_direction=arguments.direction,
        source=str(arguments.csv_path),
    )
    output = arguments.output or arguments.csv_path.with_name(
        "malus_calibration.json"
    )
    calibration.save(output)
    print(f"Saved calibration: {output}")
    print(f"Points used: {calibration.point_count}")
    print(f"RMS residual: {calibration.rms_residual_mw:.6g} mW")


if __name__ == "__main__":
    main()
