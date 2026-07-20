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

    FORMAT_VERSION = 5

    CSV_FIELDS = [
        "measurement",
        "timestamp",
        "sample_angle_deg",
        "waveplate_angle_deg",
        "power_mw",
        "target_power_mw",
        "power_rms_mw",
        "power_measurement_duration_s",
        "power_std_mw",
        "power_measurement_id",
        "power_trace_id",
        "power_measurement_status",
        "power_measurement_error",
        "power_valid_sample_count",
        "power_total_sample_count",
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

        self.power_measurements_directory = (
            self.root / "power_measurements"
        )

        self._measurement_number = 0
        self._background_number = 0
        self._background_records: list[dict[str, Any]] = []
        self._power_trace_records: list[dict[str, Any]] = []
        self._power_trace_paths: dict[str, Path] = {}
        self._power_trace_objects: dict[str, Any] = {}
        self._power_attempt_records: list[dict[str, Any]] = []
        self._power_attempt_objects: dict[str, Any] = {}

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

    @property
    def power_trace_count(self) -> int:
        """Number of unique raw incident-power traces written so far."""

        return len(self._power_trace_records)

    @property
    def power_attempt_count(self) -> int:
        """Number of incident-power acquisition attempts persisted."""

        return len(self._power_attempt_records)

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

        power_trace = getattr(measurement, "power_trace", None)
        power_status = getattr(measurement, "power_measurement_status", None)
        attempt_id = getattr(measurement, "power_measurement_id", None)
        measurement_trace_id = getattr(measurement, "power_trace_id", None)
        if power_status and not attempt_id:
            raise ValueError(
                "A power measurement status requires a stable "
                "power_measurement_id."
            )
        if attempt_id:
            attempt = self._power_attempt_objects.get(str(attempt_id))
            if attempt is None:
                raise ValueError(
                    "Power measurement attempt must be persisted before its "
                    "associated spectrum."
                )
            if attempt.trace_id != measurement_trace_id:
                raise ValueError(
                    "Measurement power_trace_id disagrees with its persisted "
                    "power attempt."
                )
            if not np.isclose(
                float(attempt.waveplate_angle_deg),
                float(measurement.waveplate_angle_deg),
                rtol=0.0,
                atol=1e-12,
            ):
                raise ValueError(
                    "Measurement waveplate angle disagrees with its power "
                    "attempt."
                )
            if attempt.status != power_status:
                raise ValueError(
                    "Measurement power status disagrees with its persisted "
                    "power attempt."
                )
            if attempt.error != getattr(
                measurement,
                "power_measurement_error",
                None,
            ):
                raise ValueError(
                    "Measurement power error disagrees with its persisted "
                    "power attempt."
                )
        if measurement_trace_id and power_trace is None:
            raise ValueError(
                "power_trace_id is set but no raw power trace is attached."
            )
        if power_trace is not None:
            trace_id = str(power_trace.trace_id)
            if measurement_trace_id != trace_id:
                raise ValueError(
                    "Measurement power_trace_id does not match its "
                    f"attached power trace ({measurement_trace_id!r} != "
                    f"{trace_id!r})."
                )
            self._validate_power_summary(measurement, power_trace)
            self.save_power_trace(power_trace)

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

                "power_std_mw":
                    self._optional_value(
                        getattr(measurement, "power_std_mw", None)
                    ),

                "power_measurement_id":
                    getattr(measurement, "power_measurement_id", None) or "",

                "power_trace_id":
                    getattr(measurement, "power_trace_id", None) or "",

                "power_measurement_status":
                    getattr(
                        measurement,
                        "power_measurement_status",
                        None,
                    ) or "",

                "power_measurement_error":
                    getattr(
                        measurement,
                        "power_measurement_error",
                        None,
                    ) or "",

                "power_valid_sample_count":
                    self._optional_value(
                        getattr(
                            measurement,
                            "power_valid_sample_count",
                            None,
                        )
                    ),

                "power_total_sample_count":
                    self._optional_value(
                        getattr(
                            measurement,
                            "power_total_sample_count",
                            None,
                        )
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

    def save_power_trace(self, trace) -> Path:
        """Save one unique raw power trace and atomically update its index.

        Raw COM values are encoded as JSON strings inside a non-object NumPy
        array. This preserves missing values and primitive types without
        enabling pickle when the experiment is reloaded.
        """

        self._require_open()

        trace_id = str(trace.trace_id).strip()
        if not trace_id:
            raise ValueError("Power trace ID must not be empty.")
        existing_path = self._power_trace_paths.get(trace_id)
        if existing_path is not None:
            if self._power_trace_objects[trace_id] != trace:
                raise ValueError(
                    f"Power trace ID collision for {trace_id!r}."
                )
            return existing_path

        samples = tuple(trace.samples)
        batch_sizes = np.asarray(trace.batch_sizes, dtype=int)
        if batch_sizes.ndim != 1 or np.any(batch_sizes < 0):
            raise ValueError(
                "Power-trace batch sizes must be a one-dimensional, "
                "non-negative integer sequence."
            )
        if int(np.sum(batch_sizes)) != len(samples):
            raise ValueError(
                "Power-trace batch sizes do not account for every sample."
            )

        self.power_measurements_directory.mkdir(
            parents=False,
            exist_ok=True,
        )
        filename = f"power_{len(self._power_trace_records) + 1:06d}.npz"
        filepath = self.power_measurements_directory / filename

        np.savez_compressed(
            filepath,
            batch_sizes=batch_sizes,
            batch_index=np.asarray(
                [sample.batch_index for sample in samples],
                dtype=int,
            ),
            index_in_batch=np.asarray(
                [sample.index_in_batch for sample in samples],
                dtype=int,
            ),
            raw_value_json=np.asarray(
                [self._raw_json(sample.raw_value) for sample in samples],
                dtype=str,
            ),
            raw_timestamp_json=np.asarray(
                [self._raw_json(sample.raw_timestamp) for sample in samples],
                dtype=str,
            ),
            raw_status_json=np.asarray(
                [self._raw_json(sample.raw_status) for sample in samples],
                dtype=str,
            ),
            power_w=np.asarray(
                [
                    np.nan if sample.power_w is None else sample.power_w
                    for sample in samples
                ],
                dtype=float,
            ),
            timestamp_s=np.asarray(
                [
                    np.nan
                    if sample.timestamp_s is None
                    else sample.timestamp_s
                    for sample in samples
                ],
                dtype=float,
            ),
            valid_for_statistics=np.asarray(
                [sample.valid_for_statistics for sample in samples],
                dtype=bool,
            ),
            invalid_reasons_json=np.asarray(
                [
                    json.dumps(
                        list(sample.invalid_reasons),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    for sample in samples
                ],
                dtype=str,
            ),
        )

        record = {
            "trace_id": trace_id,
            "trace_file": (
                Path("power_measurements") / filename
            ).as_posix(),
            "requested_duration_s": float(trace.requested_duration_s),
            "elapsed_duration_s": float(trace.elapsed_duration_s),
            "started_at_unix_s": float(trace.started_at_unix_s),
            "source_unit": str(trace.source_unit),
            "device_serial": trace.device_serial,
            "sensor_serial": trace.sensor_serial,
            "measurement_mode": trace.measurement_mode,
            "wavelength_option": trace.wavelength_option,
            "range_option": trace.range_option,
            "total_sample_count": len(samples),
            "valid_sample_count": trace.statistics.valid_sample_count,
        }
        self._power_trace_records.append(record)
        self._power_trace_paths[trace_id] = filepath
        self._power_trace_objects[trace_id] = trace
        try:
            self._write_json(
                "power_measurements.json",
                {"power_measurements": self._power_trace_records},
            )
        except Exception:
            self._power_trace_records.pop()
            self._power_trace_paths.pop(trace_id, None)
            self._power_trace_objects.pop(trace_id, None)
            raise

        return filepath

    def save_power_attempt(self, attempt, trace=None) -> None:
        """Persist one success/failure attempt before spectrum acquisition."""

        self._require_open()
        attempt_id = str(attempt.attempt_id).strip()
        existing = self._power_attempt_objects.get(attempt_id)
        if existing is not None:
            if existing != attempt:
                raise ValueError(
                    f"Power measurement attempt ID collision: {attempt_id!r}."
                )
            return

        if trace is None:
            if attempt.trace_id is not None:
                raise ValueError(
                    "Power attempt references a trace but no trace was supplied."
                )
        else:
            if attempt.trace_id != trace.trace_id:
                raise ValueError(
                    "Power attempt trace_id does not match the supplied trace."
                )
            self.save_power_trace(trace)

        record = self._to_json_compatible(attempt)
        self._power_attempt_records.append(record)
        self._power_attempt_objects[attempt_id] = attempt
        try:
            self._write_json(
                "power_attempts.json",
                {"power_attempts": self._power_attempt_records},
            )
        except Exception:
            self._power_attempt_records.pop()
            self._power_attempt_objects.pop(attempt_id, None)
            raise

    @staticmethod
    def _validate_power_summary(measurement, trace) -> None:
        """Prevent derived CSV values drifting from the preserved raw trace."""

        statistics = trace.statistics
        expected = {
            "power_mw": statistics.arithmetic_mean_power_mw,
            "power_std_mw": statistics.population_standard_deviation_mw,
            "power_rms_mw": statistics.absolute_root_mean_square_power_mw,
            "power_measurement_duration_s": trace.elapsed_duration_s,
            "power_valid_sample_count": statistics.valid_sample_count,
            "power_total_sample_count": statistics.total_sample_count,
        }
        for name, expected_value in expected.items():
            actual_value = getattr(measurement, name, None)
            if expected_value is None or actual_value is None:
                matches = expected_value is None and actual_value is None
            elif isinstance(expected_value, int):
                matches = int(actual_value) == expected_value
            else:
                matches = bool(
                    np.isclose(
                        float(actual_value),
                        float(expected_value),
                        rtol=1e-12,
                        atol=1e-12,
                    )
                )
            if not matches:
                raise ValueError(
                    f"Measurement {name}={actual_value!r} does not match "
                    f"raw power trace statistic {expected_value!r}."
                )

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

    @classmethod
    def _raw_json(cls, value) -> str:
        """Encode one raw vendor value without requiring a NumPy object array."""

        return json.dumps(
            cls._to_json_compatible(value),
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
