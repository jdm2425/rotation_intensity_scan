"""
data_writer.py

Save complete experiments to disk.

Each experiment is stored in its own timestamped directory:

    results/
        ExperimentName_YYYYMMDD_HHMMSS/
            metadata.json
            config.json
            hardware.json
            measurements.csv
            spectra/
                spectrum_000001.npz
                spectrum_000002.npz
                ...

Spectrum files contain only standard NumPy arrays and scalar values.
Python object arrays and pickle-based storage are deliberately avoided.
"""

from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np


class DataWriter:
    """
    Save one complete experiment.

    Parameters
    ----------
    output_directory
        Parent directory in which experiment folders are created.

    experiment_name
        Human-readable name used in the experiment directory.
    """

    FORMAT_VERSION = 4

    CSV_FIELDS = [
        "measurement",
        "timestamp",
        "sample_angle_deg",
        "waveplate_angle_deg",
        "power_mw",
        "target_power_mw",
        "power_rms_mw",
        "power_measurement_duration_s",
        "fluence_mj_cm2",
        "intensity_w_cm2",
        "integration_time_ms",
        "averages",
        "spectrometer_serial",
        "dark_corrected",
        "nonlinearity_corrected",
        "peak_counts",
        "integrated_counts",
        "saturated",
        "measurement_metadata",
        "spectrum_file",
    ]

    def __init__(
        self,
        *,
        output_directory: str | Path,
        experiment_name: str,
    ) -> None:

        self.output_directory = Path(output_directory)
        self.experiment_name = str(experiment_name)

        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        self.root = (
            self.output_directory
            / f"{self.experiment_name}_{timestamp}"
        )

        self.spectra_directory = (
            self.root / "spectra"
        )

        self.backgrounds_directory = (
            self.root / "backgrounds"
        )

        self._measurement_number = 0
        self._background_number = 0
        self._background_records: list[dict[str, Any]] = []

        self._csv_file = None
        self._csv_writer = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "DataWriter":

        self.root.mkdir(
            parents=True,
            exist_ok=False,
        )

        self.spectra_directory.mkdir(
            parents=False,
            exist_ok=False,
        )

        self._csv_file = (
            self.root / "measurements.csv"
        ).open(
            "w",
            newline="",
            encoding="utf-8",
        )

        self._csv_writer = csv.DictWriter(
            self._csv_file,
            fieldnames=self.CSV_FIELDS,
        )

        self._csv_writer.writeheader()
        self._csv_file.flush()

        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> bool:

        self.close()

        return False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def experiment_directory(self) -> Path:
        """
        Directory containing this experiment.
        """

        return self.root

    @property
    def measurement_count(self) -> int:
        """
        Number of measurements written so far.
        """

        return self._measurement_number

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def save_metadata(
        self,
        *,
        config,
        hardware_info,
        extra_metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Save experiment metadata, configuration and hardware details.

        Parameters
        ----------
        config
            Experiment configuration object or dictionary.

        hardware_info
            Dictionary returned by HardwareManager.info() or summary().

        extra_metadata
            Optional additional information for metadata.json.
        """

        self._require_open()

        metadata = {
            "experiment_name": self.experiment_name,
            "directory_name": self.root.name,
            "created": datetime.now().isoformat(),
            "software": "Rotation Intensity Scan",
        }

        if extra_metadata:
            metadata.update(
                self._to_json_compatible(
                    extra_metadata
                )
            )

        # The writer, rather than caller-provided metadata, owns the
        # authoritative on-disk format version.
        metadata["format_version"] = self.FORMAT_VERSION

        self._write_json(
            "metadata.json",
            metadata,
        )

        self._write_json(
            "config.json",
            self._to_json_compatible(config),
        )

        self._write_json(
            "hardware.json",
            self._to_json_compatible(
                hardware_info
            ),
        )

    # ------------------------------------------------------------------
    # Measurements
    # ------------------------------------------------------------------

    def save_result(
        self,
        measurement,
    ) -> Path:
        """
        Save one completed Measurement.

        Returns
        -------
        Path
            Path to the saved spectrum file.
        """

        self._require_open()

        spectrum = measurement.spectrum

        if spectrum is None:
            raise ValueError(
                "Cannot save a measurement without a spectrum."
            )

        wavelengths = np.asarray(
            spectrum.wavelengths,
            dtype=float,
        )

        intensities = np.asarray(
            spectrum.intensities,
            dtype=float,
        )

        if wavelengths.ndim != 1:
            raise ValueError(
                "Spectrum wavelengths must be one-dimensional."
            )

        if intensities.ndim != 1:
            raise ValueError(
                "Spectrum intensities must be one-dimensional."
            )

        if wavelengths.shape != intensities.shape:
            raise ValueError(
                "Spectrum wavelength and intensity arrays "
                "must have matching shapes."
            )

        measurement_metadata = self._metadata_json(
            measurement.metadata
        )

        self._measurement_number += 1

        filename = (
            f"spectrum_"
            f"{self._measurement_number:06d}.npz"
        )

        filepath = (
            self.spectra_directory / filename
        )

        np.savez_compressed(
            filepath,
            wavelengths=wavelengths,
            intensities=intensities,
            integration_time_ms=np.asarray(
                spectrum.integration_time_ms,
                dtype=float,
            ),
            serial=np.asarray(
                spectrum.serial,
                dtype=str,
            ),
            averages=np.asarray(
                spectrum.averages,
                dtype=int,
            ),
            dark_corrected=np.asarray(
                spectrum.dark_corrected,
                dtype=bool,
            ),
            nonlinearity_corrected=np.asarray(
                spectrum.nonlinearity_corrected,
                dtype=bool,
            ),
            timestamp=np.asarray(
                spectrum.timestamp,
                dtype=float,
            ),
        )

        self._csv_writer.writerow(
            {
                "measurement":
                    self._measurement_number,

                "timestamp":
                    measurement.timestamp,

                "sample_angle_deg":
                    measurement.sample_angle_deg,

                "waveplate_angle_deg":
                    measurement.waveplate_angle_deg,

                "power_mw":
                    self._optional_value(
                        measurement.power_mw
                    ),

                "target_power_mw":
                    self._optional_value(
                        measurement.target_power_mw
                    ),

                "power_rms_mw":
                    self._optional_value(
                        measurement.power_rms_mw
                    ),

                "power_measurement_duration_s":
                    self._optional_value(
                        measurement.power_measurement_duration_s
                    ),

                "fluence_mj_cm2":
                    self._optional_value(
                        measurement.fluence_mj_cm2
                    ),

                "intensity_w_cm2":
                    self._optional_value(
                        measurement.intensity_w_cm2
                    ),

                "integration_time_ms":
                    spectrum.integration_time_ms,

                "averages":
                    spectrum.averages,

                "spectrometer_serial":
                    spectrum.serial,

                "dark_corrected":
                    spectrum.dark_corrected,

                "nonlinearity_corrected":
                    spectrum.nonlinearity_corrected,

                "peak_counts":
                    self._optional_value(
                        measurement.peak_counts
                    ),

                "integrated_counts":
                    self._optional_value(
                        measurement.integrated_counts
                    ),

                "saturated":
                    measurement.saturated,

                "measurement_metadata":
                    measurement_metadata,

                "spectrum_file":
                    filename,
            }
        )

        # Flush after every measurement so completed data survive
        # if a later acquisition fails or the scan is interrupted.
        self._csv_file.flush()

        return filepath

    def save_background(
        self,
        spectrum,
        *,
        name: str = "pre_scan_dark",
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """Save one named raw background spectrum and update its index."""

        self._require_open()

        name = str(name).strip()
        if not name:
            raise ValueError("Background name must not be empty.")
        if any(
            record["name"] == name
            for record in self._background_records
        ):
            raise ValueError(
                f"A background named {name!r} has already been saved."
            )

        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise ValueError("Background metadata must be a dictionary.")

        metadata = self._to_json_compatible(metadata)
        # Validate serialisability before creating the spectrum file.
        json.dumps(metadata, ensure_ascii=False)

        wavelengths = np.asarray(
            spectrum.wavelengths,
            dtype=float,
        )
        intensities = np.asarray(
            spectrum.intensities,
            dtype=float,
        )

        if wavelengths.ndim != 1 or intensities.ndim != 1:
            raise ValueError(
                "Background wavelength and intensity data must be "
                "one-dimensional."
            )
        if wavelengths.shape != intensities.shape:
            raise ValueError(
                "Background wavelength and intensity arrays must have "
                "matching shapes."
            )

        self._background_number += 1
        filename = f"background_{self._background_number:06d}.npz"

        self.backgrounds_directory.mkdir(
            parents=False,
            exist_ok=True,
        )

        filepath = self.backgrounds_directory / filename

        np.savez_compressed(
            filepath,
            wavelengths=wavelengths,
            intensities=intensities,
            integration_time_ms=np.asarray(
                spectrum.integration_time_ms,
                dtype=float,
            ),
            serial=np.asarray(spectrum.serial, dtype=str),
            averages=np.asarray(spectrum.averages, dtype=int),
            dark_corrected=np.asarray(
                spectrum.dark_corrected,
                dtype=bool,
            ),
            nonlinearity_corrected=np.asarray(
                spectrum.nonlinearity_corrected,
                dtype=bool,
            ),
            timestamp=np.asarray(spectrum.timestamp, dtype=float),
        )

        self._background_records.append(
            {
                "name": name,
                "spectrum_file": (
                    Path("backgrounds") / filename
                ).as_posix(),
                "metadata": metadata,
            }
        )

        self._write_json(
            "backgrounds.json",
            {"backgrounds": self._background_records},
        )

        return filepath

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """
        Flush and close the measurement index.
        """

        if self._csv_file is None:
            return

        try:
            self._csv_file.flush()

        finally:
            self._csv_file.close()
            self._csv_file = None
            self._csv_writer = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_open(self) -> None:

        if (
            self._csv_file is None
            or self._csv_writer is None
        ):
            raise RuntimeError(
                "DataWriter is not open. "
                "Use it inside a 'with DataWriter(...)' block."
            )

    def _write_json(
        self,
        filename: str,
        data,
    ) -> None:

        filepath = self.root / filename

        temporary_path = filepath.with_suffix(
            filepath.suffix + ".tmp"
        )

        with temporary_path.open(
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                data,
                file,
                indent=4,
                ensure_ascii=False,
                default=str,
            )

            file.flush()
            os.fsync(file.fileno())

        temporary_path.replace(filepath)

    @classmethod
    def _to_json_compatible(
        cls,
        value,
    ):

        if is_dataclass(value):
            value = asdict(value)

        if isinstance(value, dict):
            return {
                str(key): cls._to_json_compatible(item)
                for key, item in value.items()
            }

        if isinstance(value, (list, tuple)):
            return [
                cls._to_json_compatible(item)
                for item in value
            ]

        if isinstance(value, Path):
            return str(value)

        if isinstance(value, np.ndarray):
            return value.tolist()

        if isinstance(value, np.generic):
            return value.item()

        return value

    @staticmethod
    def _optional_value(value):

        if value is None:
            return ""

        return value

    @classmethod
    def _metadata_json(
        cls,
        metadata,
    ) -> str:
        """Serialise one measurement's metadata for the CSV index."""

        if metadata is None:
            return "{}"

        if not isinstance(metadata, dict):
            raise ValueError(
                "Measurement metadata must be a dictionary."
            )

        return json.dumps(
            cls._to_json_compatible(metadata),
            ensure_ascii=False,
            separators=(",", ":"),
        )
