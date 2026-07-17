"""
data_writer.py

Writes complete experiments to disk.

Directory structure
-------------------

Experiment_YYYYMMDD_HHMMSS/

    metadata.json
    config.json
    hardware.json
    measurements.csv

    spectra/
        spectrum_000001.npz
        spectrum_000002.npz
        ...
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import numpy as np


class DataWriter:

    def __init__(
        self,
        *,
        output_directory: str,
        experiment_name: str,
    ):

        self.output_directory = Path(output_directory)

        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        self.root = (
            self.output_directory
            / f"{experiment_name}_{timestamp}"
        )

        self.spectra_directory = (
            self.root / "spectra"
        )

        self._measurement_number = 0

        self._csv = None
        self._writer = None

    # ------------------------------------------------------------------

    def __enter__(self):

        self.root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.spectra_directory.mkdir(
            exist_ok=True,
        )

        self._csv = open(
            self.root / "measurements.csv",
            "w",
            newline="",
            encoding="utf-8",
        )

        fieldnames = [

            "measurement",

            "timestamp",

            "sample_angle_deg",

            "waveplate_angle_deg",

            "power_mw",

            "fluence_mj_cm2",

            "intensity_w_cm2",

            "integration_time_ms",

            "peak_counts",

            "integrated_counts",

            "spectrum_file",

        ]

        self._writer = csv.DictWriter(
            self._csv,
            fieldnames=fieldnames,
        )

        self._writer.writeheader()

        return self

    # ------------------------------------------------------------------

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ):

        if self._csv is not None:

            self._csv.close()

        return False

    # ------------------------------------------------------------------

    @property
    def experiment_directory(self):

        return self.root

    # ------------------------------------------------------------------

    def save_metadata(
        self,
        *,
        config,
        hardware_info,
    ):

        metadata = {

            "experiment_name":
                self.root.name,

            "created":
                datetime.now().isoformat(),

            "software":

                "Rotation Intensity Scan",

        }

        self._write_json(
            "metadata.json",
            metadata,
        )

        self._write_json(
            "hardware.json",
            hardware_info,
        )

        #
        # Config may be a dataclass.
        #

        try:

            from dataclasses import asdict

            config = asdict(config)

        except Exception:

            pass

        self._write_json(
            "config.json",
            config,
        )

    # ------------------------------------------------------------------

    def save_result(
        self,
        measurement,
    ):

        self._measurement_number += 1

        filename = (
            f"spectrum_"
            f"{self._measurement_number:06d}.npz"
        )

        np.savez_compressed(

            self.spectra_directory / filename,

            wavelengths=
                measurement.wavelengths_nm,

            intensities=
                measurement.spectrum,

        )

        self._writer.writerow({

            "measurement":
                self._measurement_number,

            "timestamp":
                measurement.timestamp,

            "sample_angle_deg":
                measurement.sample_angle_deg,

            "waveplate_angle_deg":
                measurement.waveplate_angle_deg,

            "power_mw":
                measurement.power_mw,

            "fluence_mj_cm2":
                measurement.fluence_mj_cm2,

            "intensity_w_cm2":
                measurement.intensity_w_cm2,

            "integration_time_ms":
                measurement.integration_time_ms,

            "peak_counts":
                measurement.peak_counts,

            "integrated_counts":
                measurement.integrated_counts,

            "spectrum_file":
                filename,

        })

        self._csv.flush()

    # ------------------------------------------------------------------

    def _write_json(
        self,
        filename,
        data,
    ):

        with open(
            self.root / filename,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                data,
                f,
                indent=4,
                default=str,
            )