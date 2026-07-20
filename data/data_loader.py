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
from data.power_measurement import PowerMeasurementAttempt
from hardware.devices.power_meter.models import PowerSample, PowerTrace
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

        power_traces = self._load_power_traces(root=root)
        power_traces_by_id = {
            trace.trace_id: trace for trace in power_traces
        }
        power_attempts = self._load_power_attempts(
            root=root,
            power_traces_by_id=power_traces_by_id,
        )
        power_attempts_by_id = {
            attempt.attempt_id: attempt for attempt in power_attempts
        }

        measurements = self._load_measurements(
            root=root,
            measurements_file=measurements_file,
            power_traces_by_id=power_traces_by_id,
            power_attempts_by_id=power_attempts_by_id,
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
            power_traces=power_traces,
            power_attempts=power_attempts,
        )

    def _load_power_attempts(
        self,
        *,
        root: Path,
        power_traces_by_id: dict[str, PowerTrace],
    ) -> list[PowerMeasurementAttempt]:
        index_path = root / "power_attempts.json"
        if not index_path.exists():
            return []
        index = self._read_optional_json(index_path)
        records = index.get("power_attempts", [])
        if not isinstance(records, list):
            raise ValueError(f"Expected a power_attempts list in {index_path}.")

        attempts: list[PowerMeasurementAttempt] = []
        seen: set[str] = set()
        for record_number, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                raise ValueError(
                    f"Power attempt {record_number} in {index_path} is not an object."
                )
            metadata = record.get("metadata", {})
            if not isinstance(metadata, dict):
                raise ValueError(
                    f"Power attempt metadata must be an object in {index_path}."
                )
            attempt = PowerMeasurementAttempt(
                attempt_id=str(record.get("attempt_id", "")),
                attempted_at_unix_s=float(record["attempted_at_unix_s"]),
                waveplate_angle_deg=float(record["waveplate_angle_deg"]),
                cadence=str(record.get("cadence", "")),
                status=str(record.get("status", "")),
                fundamental_wavelength_nm=float(
                    record["fundamental_wavelength_nm"]
                ),
                trace_id=self._optional_text(record.get("trace_id")),
                error=self._optional_text(record.get("error")),
                maximum_allowed_power_mw=self._optional_float(
                    record.get("maximum_allowed_power_mw")
                ),
                metadata=metadata,
            )
            if attempt.attempt_id in seen:
                raise ValueError(
                    f"Duplicate power attempt ID {attempt.attempt_id!r}."
                )
            seen.add(attempt.attempt_id)
            if (
                attempt.trace_id is not None
                and attempt.trace_id not in power_traces_by_id
            ):
                raise ValueError(
                    f"Power attempt {attempt.attempt_id!r} references missing "
                    f"trace {attempt.trace_id!r}."
                )
            attempts.append(attempt)
        return attempts

    def _load_power_traces(self, *, root: Path) -> list[PowerTrace]:
        """Load optional raw incident-power traces saved in format version 5."""

        index_path = root / "power_measurements.json"
        if not index_path.exists():
            return []

        index = self._read_optional_json(index_path)
        records = index.get("power_measurements", [])
        if not isinstance(records, list):
            raise ValueError(
                f"Expected a power_measurements list in {index_path}."
            )

        traces: list[PowerTrace] = []
        seen_ids: set[str] = set()
        for record_number, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                raise ValueError(
                    "Expected each power trace index entry to be an object "
                    f"in {index_path} (entry {record_number})."
                )
            trace_id = str(record.get("trace_id", "")).strip()
            filename = str(record.get("trace_file", "")).strip()
            if not trace_id or not filename:
                raise ValueError(
                    "Power trace entries require trace_id and trace_file "
                    f"in {index_path} (entry {record_number})."
                )
            if trace_id in seen_ids:
                raise ValueError(
                    f"Duplicate power trace ID {trace_id!r} in {index_path}."
                )
            seen_ids.add(trace_id)

            path = (root / filename).resolve()
            try:
                path.relative_to(root)
            except ValueError as error:
                raise ValueError(
                    f"Power trace path escapes experiment directory: {path}"
                ) from error
            traces.append(self._load_power_trace(path=path, record=record))
        return traces

    def _load_power_trace(
        self,
        *,
        path: Path,
        record: dict[str, Any],
    ) -> PowerTrace:
        if not path.exists():
            raise FileNotFoundError(f"Power trace file does not exist: {path}")

        required_keys = {
            "batch_sizes",
            "batch_index",
            "index_in_batch",
            "raw_value_json",
            "raw_timestamp_json",
            "raw_status_json",
            "power_w",
            "timestamp_s",
            "valid_for_statistics",
            "invalid_reasons_json",
        }
        with np.load(path, allow_pickle=False) as arrays:
            missing = sorted(required_keys - set(arrays.files))
            if missing:
                raise KeyError(
                    f"Missing power trace arrays {missing} in {path}."
                )
            loaded = {
                key: np.asarray(arrays[key]).reshape(-1)
                for key in required_keys
            }

        sample_keys = required_keys - {"batch_sizes"}
        lengths = {key: len(loaded[key]) for key in sample_keys}
        if len(set(lengths.values())) != 1:
            raise ValueError(
                f"Power trace arrays have mismatched lengths in {path}: "
                f"{lengths}."
            )

        samples: list[PowerSample] = []
        sample_count = next(iter(lengths.values()), 0)
        for index in range(sample_count):
            power_w_value = float(loaded["power_w"][index])
            timestamp_value = float(loaded["timestamp_s"][index])
            try:
                invalid_reasons = json.loads(
                    str(loaded["invalid_reasons_json"][index])
                )
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Invalid power sample reasons JSON in {path}."
                ) from error
            if not isinstance(invalid_reasons, list) or not all(
                isinstance(reason, str) for reason in invalid_reasons
            ):
                raise ValueError(
                    f"Power sample reasons must be a string list in {path}."
                )
            samples.append(
                PowerSample(
                    batch_index=int(loaded["batch_index"][index]),
                    index_in_batch=int(loaded["index_in_batch"][index]),
                    raw_value=self._decode_raw_json(
                        loaded["raw_value_json"][index], path
                    ),
                    raw_timestamp=self._decode_raw_json(
                        loaded["raw_timestamp_json"][index], path
                    ),
                    raw_status=self._decode_raw_json(
                        loaded["raw_status_json"][index], path
                    ),
                    power_w=(
                        power_w_value if np.isfinite(power_w_value) else None
                    ),
                    timestamp_s=(
                        timestamp_value
                        if np.isfinite(timestamp_value)
                        else None
                    ),
                    valid_for_statistics=bool(
                        loaded["valid_for_statistics"][index]
                    ),
                    invalid_reasons=tuple(invalid_reasons),
                )
            )

        trace = PowerTrace(
            samples=tuple(samples),
            batch_sizes=tuple(
                int(value) for value in loaded["batch_sizes"]
            ),
            requested_duration_s=float(record["requested_duration_s"]),
            elapsed_duration_s=float(record["elapsed_duration_s"]),
            started_at_unix_s=float(record["started_at_unix_s"]),
            trace_id=str(record["trace_id"]),
            source_unit=str(record.get("source_unit", "W")),
            device_serial=self._optional_text(record.get("device_serial")),
            sensor_serial=self._optional_text(record.get("sensor_serial")),
            measurement_mode=self._optional_text(
                record.get("measurement_mode")
            ),
            wavelength_option=self._optional_text(
                record.get("wavelength_option")
            ),
            range_option=self._optional_text(record.get("range_option")),
        )
        declared_count = record.get("total_sample_count")
        if declared_count is not None and int(declared_count) != len(samples):
            raise ValueError(
                f"Power trace sample count disagrees with index for {path}."
            )
        return trace

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
        power_traces_by_id: dict[str, PowerTrace],
        power_attempts_by_id: dict[str, PowerMeasurementAttempt],
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
                    power_traces_by_id=power_traces_by_id,
                    power_attempts_by_id=power_attempts_by_id,
                )

                measurements.append(measurement)

        return measurements

    def _load_measurement(
        self,
        *,
        root: Path,
        row: dict[str, str],
        row_number: int,
        power_traces_by_id: dict[str, PowerTrace],
        power_attempts_by_id: dict[str, PowerMeasurementAttempt],
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

        power_measurement_id = self._optional_text(
            row.get("power_measurement_id")
        )
        if (
            power_measurement_id is not None
            and power_measurement_id not in power_attempts_by_id
        ):
            raise ValueError(
                "Measurement references missing power attempt "
                f"{power_measurement_id!r} in measurements.csv row "
                f"{row_number}."
            )
        power_trace_id = self._optional_text(row.get("power_trace_id"))
        power_trace = None
        if power_trace_id is not None:
            try:
                power_trace = power_traces_by_id[power_trace_id]
            except KeyError as error:
                raise ValueError(
                    "Measurement references missing power trace "
                    f"{power_trace_id!r} in measurements.csv row "
                    f"{row_number}."
                ) from error
        if power_measurement_id is not None:
            attempt = power_attempts_by_id[power_measurement_id]
            if attempt.trace_id != power_trace_id:
                raise ValueError(
                    f"Measurement power trace disagrees with attempt "
                    f"{power_measurement_id!r} in row {row_number}."
                )
            row_status = self._optional_text(
                row.get("power_measurement_status")
            )
            row_error = self._optional_text(row.get("power_measurement_error"))
            if attempt.status != row_status or attempt.error != row_error:
                raise ValueError(
                    f"Measurement power provenance disagrees with attempt "
                    f"{power_measurement_id!r} in row {row_number}."
                )
            row_waveplate = self._required_float(
                row,
                "waveplate_angle_deg",
                row_number,
            )
            if not np.isclose(
                row_waveplate,
                attempt.waveplate_angle_deg,
                rtol=0.0,
                atol=1e-12,
            ):
                raise ValueError(
                    f"Measurement waveplate angle disagrees with power "
                    f"attempt {power_measurement_id!r} in row {row_number}."
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
            power_std_mw=self._optional_float(row.get("power_std_mw")),
            power_measurement_id=power_measurement_id,
            power_trace_id=power_trace_id,
            power_measurement_status=self._optional_text(
                row.get("power_measurement_status")
            ),
            power_measurement_error=self._optional_text(
                row.get("power_measurement_error")
            ),
            power_valid_sample_count=self._optional_int_or_none(
                row.get("power_valid_sample_count")
            ),
            power_total_sample_count=self._optional_int_or_none(
                row.get("power_total_sample_count")
            ),
            power_trace=power_trace,
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
    def _optional_int_or_none(value) -> int | None:
        if value is None:
            return None
        if isinstance(value, str) and value.strip().lower() in {
            "",
            "none",
            "null",
            "nan",
        }:
            return None
        return int(value)

    @staticmethod
    def _optional_text(value) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _decode_raw_json(value, path: Path):
        try:
            return json.loads(str(value))
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Invalid raw power sample JSON in {path}."
            ) from error

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
