"""
data_writer.py

Handles writing experiment data to disk.

Directory structure
-------------------

experiment_folder/

    metadata.json

    measurements.csv

    spectra/

        spectrum_000001.npz
        spectrum_000002.npz
        ...
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path

import numpy as np


class DataWriter:
    """
    Writes experiment data.

    One DataWriter corresponds to one experiment.
    """

    # ------------------------------------------------------------------

    def __init__(
        self,
        output_directory="data",
        experiment_name="rotation_intensity_scan",
    ):

        timestamp = datetime.now().strftime(
            "%Y-%m-%d_%H-%M-%S"
        )

        self.directory = (
            Path(output_directory)
            / f"{timestamp}_{experiment_name}"
        )

        self.spectra_directory = (
            self.directory / "spectra"
        )

        self.directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.spectra_directory.mkdir(
            exist_ok=True,
        )

        self.csv_file = open(
            self.directory / "measurements.csv",
            "w",
            newline="",
        )

        self.writer = csv.writer(self.csv_file)

        self.writer.writerow(
            [
                "measurement",
                "timestamp",
                "waveplate_angle_deg",
                "sample_angle_deg",
                "spectrum_file",
            ]
        )

        self.measurement_number = 0

    # ------------------------------------------------------------------

    def save_metadata(
        self,
        config,
        hardware_info,
    ):
        """
        Save experiment metadata.
        """

        if is_dataclass(config):

            config = asdict(config)

        metadata = {
            "created": datetime.now().isoformat(),
            "config": config,
            "hardware": hardware_info,
        }

        with open(
            self.directory / "metadata.json",
            "w",
        ) as f:

            json.dump(
                metadata,
                f,
                indent=4,
                default=str,
            )

    # ------------------------------------------------------------------

    def save_result(
        self,
        result,
    ):
        """
        Save one experiment result.
        """

        self.measurement_number += 1

        filename = (
            f"spectrum_{self.measurement_number:06d}.npz"
        )

        filepath = (
            self.spectra_directory / filename
        )

        np.savez_compressed(
            filepath,
            wavelengths=result.spectrum.wavelengths,
            intensities=result.spectrum.intensities,
        )

        self.writer.writerow(
            [
                self.measurement_number,
                result.timestamp,
                result.waveplate_angle_deg,
                result.sample_angle_deg,
                filename,
            ]
        )

        self.csv_file.flush()

    # ------------------------------------------------------------------

    def close(self):

        self.csv_file.close()

    # ------------------------------------------------------------------

    def __enter__(self):

        return self

    def __exit__(
        self,
        exc_type,
        exc_val,
        exc_tb,
    ):

        self.close()

        return False