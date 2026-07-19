"""
data_loader.py

Load experiments previously written by DataWriter.

The loader reconstructs the project's canonical object hierarchy:

    ExperimentDataset
        └── Measurement
                └── Spectrum

NumPy files are loaded with allow_pickle=False so experiment data never
depends on unsafe Python object deserialization.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import numpy as np

from analysis.measurement import Measurement
from data.background_spectrum import BackgroundSpectrum
from data.experiment_dataset import ExperimentDataset
from hardware.devices.spectrometer.spectrum import Spectrum


class DataLoader:
    """
    Load a complete saved experiment.
    """

    def load(
        self,
        experiment_directory: str | Path,
    ) -> ExperimentDataset:
        """
        Load an experiment directory.

        Parameters
        ----------
        experiment_directory
            Directory containing metadata.json, measurements.csv,
            and the spectra directory.

        Returns
        -------
        ExperimentDataset
            Fully reconstructed experiment.
        """

        root = Path(
            experiment_directory
        ).expanduser().resolve()

        if not root.exists():
            raise FileNotFoundError(
                f"Experiment directory does not exist: {root}"
            )

        if not root.is_dir():
            raise NotADirectoryError(
                f"Experiment path is not a directory: {root}"
            )

        measurements_file = (
            root / "measurements.csv"
        )

        if not measurements_file.exists():
            raise FileNotFoundError(
                "Could not find measurements.csv in "
                f"experiment directory: {root}"
            )

        metadata = self._read_optional_json(
            root / "metadata.json"
        )

        config = self._read_optional_json(
            root / "config.json"
        )

        hardware = self._read_optional_json(
            root / "hardware.json"
        )

        measurements = self._load_measurements(
            root=root,
            measurements_file=measurements_file,
        )

        backgrounds = self._load_backgrounds(
            root=root,
        )

        experiment_name = str(
            metadata.get(
                "experiment_name",
                root.name,
            )
        )

        created = str(
            metadata.get(
                "created",
                "",
            )
        )

        return ExperimentDataset(
            root=root,
            experiment_name=experiment_name,
            created=created,
            config=config,
            hardware=hardware,
            metadata=metadata,
            measurements=measurements,
            backgrounds=backgrounds,
        )

    def _load_backgrounds(
        self,
        *,
        root: Path,
    ) -> list[BackgroundSpectrum]:
        """Load optional named background spectra saved with an experiment."""

        index_path = root / "backgrounds.json"
        if not index_path.exists():
            return []

        index = self._read_optional_json(index_path)
        records = index.get("backgrounds", [])

        if not isinstance(records, list):
            raise ValueError(
                f"Expected a background list in {index_path}."
            )

        backgrounds: list[BackgroundSpectrum] = []

        for record_number, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                raise ValueError(
                    "Expected each background index entry to be an object "
                    f"in {index_path} (entry {record_number})."
                )

            name = str(record.get("name", "")).strip()
            filename = str(record.get("spectrum_file", "")).strip()
            background_metadata = record.get("metadata", {})

            if not name or not filename:
                raise ValueError(
                    "Background entries require name and spectrum_file "
                    f"in {index_path} (entry {record_number})."
                )
            if not isinstance(background_metadata, dict):
                raise ValueError(
                    "Background metadata must be a JSON object "
                    f"in {index_path} (entry {record_number})."
                )

            path = (root / filename).resolve()
            try:
                path.relative_to(root)
            except ValueError as error:
                raise ValueError(
                    f"Background path escapes the experiment directory: {path}"
                ) from error

            backgrounds.append(
                BackgroundSpectrum(
                    name=name,
                    spectrum=self._load_spectrum(
                        path=path,
                        row={},
                    ),
                    metadata=background_metadata,
                    source_path=path,
                )
            )

        return backgrounds

    # ------------------------------------------------------------------
    # Measurement loading
    # ------------------------------------------------------------------

    def _load_measurements(
        self,
        *,
        root: Path,
        measurements_file: Path,
    ) -> list[Measurement]:
        """
        Load every measurement listed in measurements.csv.
        """

        measurements: list[Measurement] = []

        with measurements_file.open(
            "r",
            newline="",
            encoding="utf-8",
        ) as file:

            reader = csv.DictReader(file)

            if reader.fieldnames is None:
                raise ValueError(
                    f"CSV file has no header: {measurements_file}"
                )

            for row_number, row in enumerate(
                reader,
                start=2,
            ):

                measurement = self._load_measurement(
                    root=root,
                    row=row,
                    row_number=row_number,
                )

                measurements.append(measurement)

        return measurements

    def _load_measurement(
        self,
        *,
        root: Path,
        row: dict[str, str],
        row_number: int,
    ) -> Measurement:
        """
        Reconstruct one Measurement from its CSV row and NPZ file.
        """

        spectrum_filename = (
            row.get("spectrum_file", "").strip()
        )

        if not spectrum_filename:
            raise ValueError(
                "Missing spectrum_file value in "
                f"measurements.csv row {row_number}."
            )

        spectrum_path = self._resolve_spectrum_path(
            root=root,
            filename=spectrum_filename,
        )

        spectrum = self._load_spectrum(
            path=spectrum_path,
            row=row,
        )

        measurement = Measurement(
            timestamp=self._required_float(
                row,
                "timestamp",
                row_number,
            ),
            waveplate_angle_deg=self._required_float(
                row,
                "waveplate_angle_deg",
                row_number,
            ),
            sample_angle_deg=self._required_float(
                row,
                "sample_angle_deg",
                row_number,
            ),
            power_mw=self._optional_float(
                row.get("power_mw")
            ),
            target_power_mw=self._optional_float(
                row.get("target_power_mw")
            ),
            power_rms_mw=self._optional_float(
                row.get("power_rms_mw")
            ),
            power_measurement_duration_s=self._optional_float(
                row.get("power_measurement_duration_s")
            ),
            fluence_mj_cm2=self._optional_float(
                row.get("fluence_mj_cm2")
            ),
            intensity_w_cm2=self._optional_float(
                row.get("intensity_w_cm2")
            ),
            spectrum=spectrum,
            peak_counts=self._optional_float(
                row.get("peak_counts")
            ),
            integrated_counts=self._optional_float(
                row.get("integrated_counts")
            ),
            saturated=self._parse_bool(
                row.get("saturated"),
                default=False,
            ),
            metadata=self._parse_metadata(
                row.get("measurement_metadata"),
                row_number=row_number,
            ),
        )

        # Older datasets may not contain the derived statistics.
        # Recalculate them when either value is absent.
        if (
            measurement.peak_counts is None
            or measurement.integrated_counts is None
        ):
            measurement.compute_statistics()

        return measurement

    # ------------------------------------------------------------------
    # Spectrum loading
    # ------------------------------------------------------------------

    def _load_spectrum(
        self,
        *,
        path: Path,
        row: dict[str, str],
    ) -> Spectrum:
        """
        Reconstruct a Spectrum from one compressed NumPy file.
        """

        if not path.exists():
            raise FileNotFoundError(
                f"Spectrum file does not exist: {path}"
            )

        try:
            with np.load(
                path,
                allow_pickle=False,
            ) as arrays:

                wavelengths = self._required_array(
                    arrays,
                    "wavelengths",
                    path,
                )

                intensities = self._required_array(
                    arrays,
                    "intensities",
                    path,
                )

                if wavelengths.ndim != 1:
                    raise ValueError(
                        "Wavelength data must be one-dimensional "
                        f"in {path}."
                    )

                if intensities.ndim != 1:
                    raise ValueError(
                        "Intensity data must be one-dimensional "
                        f"in {path}."
                    )

                if wavelengths.shape != intensities.shape:
                    raise ValueError(
                        "Wavelength and intensity arrays have "
                        f"different shapes in {path}: "
                        f"{wavelengths.shape} and "
                        f"{intensities.shape}."
                    )

                integration_time_ms = float(
                    self._npz_scalar(
                        arrays,
                        "integration_time_ms",
                        self._optional_float(
                            row.get("integration_time_ms")
                        ),
                    )
                )

                serial = str(
                    self._npz_scalar(
                        arrays,
                        "serial",
                        row.get(
                            "spectrometer_serial",
                            "",
                        ),
                    )
                )

                averages = int(
                    self._npz_scalar(
                        arrays,
                        "averages",
                        self._optional_int(
                            row.get("averages"),
                            default=1,
                        ),
                    )
                )

                dark_corrected = self._parse_bool(
                    self._npz_scalar(
                        arrays,
                        "dark_corrected",
                        row.get("dark_corrected"),
                    ),
                    default=False,
                )

                nonlinearity_corrected = self._parse_bool(
                    self._npz_scalar(
                        arrays,
                        "nonlinearity_corrected",
                        row.get(
                            "nonlinearity_corrected"
                        ),
                    ),
                    default=False,
                )

                spectrum_timestamp = self._optional_float(
                    self._npz_scalar(
                        arrays,
                        "timestamp",
                        None,
                    )
                )

        except ValueError as error:
            if "Object arrays cannot be loaded" in str(error):
                raise ValueError(
                    f"{path} contains a Python object array. "
                    "It was probably created by the older "
                    "DataWriter that saved the Spectrum object "
                    "instead of its numerical arrays."
                ) from error

            raise

        spectrum = Spectrum(
            wavelengths=wavelengths,
            intensities=intensities,
            integration_time_ms=integration_time_ms,
            serial=serial,
            averages=averages,
            dark_corrected=dark_corrected,
            nonlinearity_corrected=(
                nonlinearity_corrected
            ),
        )

        # Preserve the spectrum acquisition timestamp when the
        # Spectrum implementation allows it to be updated.
        if (
            spectrum_timestamp is not None
            and hasattr(spectrum, "timestamp")
        ):
            try:
                spectrum.timestamp = spectrum_timestamp
            except (AttributeError, TypeError):
                pass

        return spectrum

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_spectrum_path(
        *,
        root: Path,
        filename: str,
    ) -> Path:
        """
        Resolve either a bare filename or an experiment-relative path.
        """

        relative_path = Path(filename)

        if relative_path.is_absolute():
            return relative_path

        if (
            relative_path.parts
            and relative_path.parts[0] == "spectra"
        ):
            return root / relative_path

        return root / "spectra" / relative_path

    # ------------------------------------------------------------------
    # JSON helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_optional_json(
        path: Path,
    ) -> dict[str, Any]:
        """
        Read a JSON dictionary, returning an empty dictionary
        when the file is absent.
        """

        if not path.exists():
            return {}

        with path.open(
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError(
                f"Expected a JSON object in {path}."
            )

        return data

    # ------------------------------------------------------------------
    # NumPy helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _required_array(
        arrays,
        key: str,
        path: Path,
    ) -> np.ndarray:
        """
        Read a required one-dimensional numeric array.
        """

        if key not in arrays.files:
            raise KeyError(
                f"Missing '{key}' array in {path}."
            )

        return np.asarray(
            arrays[key],
            dtype=float,
        )

    @staticmethod
    def _npz_scalar(
        arrays,
        key: str,
        default,
    ):
        """
        Read a scalar value from an NPZ archive.
        """

        if key not in arrays.files:
            return default

        value = np.asarray(
            arrays[key]
        )

        if value.size == 0:
            return default

        return value.reshape(-1)[0].item()

    # ------------------------------------------------------------------
    # CSV conversion helpers
    # ------------------------------------------------------------------

    @classmethod
    def _required_float(
        cls,
        row: dict[str, str],
        key: str,
        row_number: int,
    ) -> float:
        """
        Read a required floating-point value from a CSV row.
        """

        value = cls._optional_float(
            row.get(key)
        )

        if value is None:
            raise ValueError(
                f"Missing or invalid '{key}' value in "
                f"measurements.csv row {row_number}."
            )

        return value

    @staticmethod
    def _optional_float(
        value,
    ) -> float | None:
        """
        Convert an optional value to float.
        """

        if value is None:
            return None

        if isinstance(value, str):
            value = value.strip()

            if value.lower() in {
                "",
                "none",
                "null",
                "nan",
            }:
                return None

        return float(value)

    @staticmethod
    def _optional_int(
        value,
        *,
        default: int,
    ) -> int:
        """
        Convert an optional value to int.
        """

        if value is None:
            return default

        if isinstance(value, str):
            value = value.strip()

            if value.lower() in {
                "",
                "none",
                "null",
                "nan",
            }:
                return default

        return int(value)

    @staticmethod
    def _parse_bool(
        value,
        *,
        default: bool,
    ) -> bool:
        """
        Convert common boolean representations.
        """

        if value is None:
            return default

        if isinstance(value, (bool, np.bool_)):
            return bool(value)

        if isinstance(value, (int, np.integer)):
            return bool(value)

        text = str(value).strip().lower()

        if text in {
            "true",
            "1",
            "yes",
            "y",
            "on",
        }:
            return True

        if text in {
            "false",
            "0",
            "no",
            "n",
            "off",
            "",
            "none",
            "null",
        }:
            return False

        raise ValueError(
            f"Cannot interpret boolean value: {value!r}"
        )

    @staticmethod
    def _parse_metadata(
        value,
        *,
        row_number: int,
    ) -> dict[str, Any]:
        """Parse optional per-measurement metadata from the CSV index."""

        if value is None or not str(value).strip():
            return {}

        try:
            metadata = json.loads(value)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError(
                "Invalid measurement_metadata JSON in "
                f"measurements.csv row {row_number}."
            ) from error

        if not isinstance(metadata, dict):
            raise ValueError(
                "Expected measurement_metadata to contain a JSON object "
                f"in measurements.csv row {row_number}."
            )

        return metadata


def load_experiment(
    experiment_directory: str | Path,
) -> ExperimentDataset:
    """
    Convenience function for loading one experiment.
    """

    return DataLoader().load(
        experiment_directory
    )
