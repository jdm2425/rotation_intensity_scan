"""
data_loader.py

Load a previously saved experiment from disk.

The loader reconstructs an ExperimentDataset, including every
Measurement and associated spectrum.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np

from data.experiment_dataset import ExperimentDataset
from analysis.measurement import Measurement


class DataLoader:
    """
    Load experiments from disk.
    """

    def load(
        self,
        directory: str | Path,
    ) -> ExperimentDataset:

        root = Path(directory)

        if not root.exists():
            raise FileNotFoundError(root)

        #
        # ------------------------------------------------------------------
        # Metadata
        # ------------------------------------------------------------------
        #

        metadata = self._load_json(
            root / "metadata.json",
            default={},
        )

        config = self._load_json(
            root / "config.json",
            default={},
        )

        hardware = self._load_json(
            root / "hardware.json",
            default={},
        )

        dataset = ExperimentDataset(

            root=root,

            experiment_name=metadata.get(
                "experiment_name",
                root.name,
            ),

            created=metadata.get(
                "created",
                datetime.fromtimestamp(
                    root.stat().st_mtime
                ).isoformat(),
            ),

            metadata=metadata,

            config=config,

            hardware=hardware,
        )

        #
        # ------------------------------------------------------------------
        # Measurements
        # ------------------------------------------------------------------
        #

        csv_file = root / "measurements.csv"

        if not csv_file.exists():

            return dataset

        spectra_directory = root / "spectra"

        import csv

        with csv_file.open(
            newline="",
            encoding="utf-8",
        ) as f:

            reader = csv.DictReader(f)

            for row in reader:

                wavelengths = None
                spectrum = None

                filename = row.get(
                    "spectrum_file",
                    "",
                )

                if filename:

                    spectrum_path = (
                        spectra_directory
                        / filename
                    )

                    if spectrum_path.exists():

                        arrays = np.load(
                            spectrum_path
                        )

                        wavelengths = arrays[
                            "wavelengths"
                        ]

                        spectrum = arrays[
                            "intensities"
                        ]

                measurement = Measurement(

                    timestamp=float(
                        row.get(
                            "timestamp",
                            0.0,
                        )
                    ),

                    waveplate_angle_deg=float(
                        row.get(
                            "waveplate_angle_deg",
                            0.0,
                        )
                    ),

                    sample_angle_deg=float(
                        row.get(
                            "sample_angle_deg",
                            0.0,
                        )
                    ),

                    power_mw=self._optional_float(
                        row.get("power_mw")
                    ),

                    fluence_mj_cm2=self._optional_float(
                        row.get(
                            "fluence_mj_cm2"
                        )
                    ),

                    intensity_w_cm2=self._optional_float(
                        row.get(
                            "intensity_w_cm2"
                        )
                    ),

                    integration_time_ms=self._optional_float(
                        row.get(
                            "integration_time_ms"
                        )
                    ),

                    wavelengths_nm=wavelengths,

                    spectrum=spectrum,
                )

                measurement.compute_statistics()

                dataset.add(
                    measurement
                )

        return dataset

    # ------------------------------------------------------------------

    @staticmethod
    def _load_json(
        filename: Path,
        *,
        default,
    ):

        if not filename.exists():

            return default

        with filename.open(
            "r",
            encoding="utf-8",
        ) as f:

            return json.load(f)

    # ------------------------------------------------------------------

    @staticmethod
    def _optional_float(value):

        if value in (
            None,
            "",
        ):

            return None

        return float(value)


#
# Convenience function
#

def load_experiment(
    directory: str | Path,
) -> ExperimentDataset:

    return DataLoader().load(
        directory
    )