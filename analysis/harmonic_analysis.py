"""Hardware-independent harmonic integration for saved experiments."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from data.background_spectrum import BackgroundSpectrum
from data.experiment_dataset import ExperimentDataset
from hardware.devices.spectrometer.spectrum import Spectrum


@dataclass(frozen=True, slots=True)
class HarmonicWindow:
    """Named wavelength interval over which one harmonic is integrated."""

    name: str
    wavelength_min_nm: float
    wavelength_max_nm: float

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Harmonic name must not be empty.")
        if not np.isfinite(self.wavelength_min_nm):
            raise ValueError("Harmonic minimum wavelength must be finite.")
        if not np.isfinite(self.wavelength_max_nm):
            raise ValueError("Harmonic maximum wavelength must be finite.")
        if self.wavelength_max_nm <= self.wavelength_min_nm:
            raise ValueError(
                "Harmonic maximum wavelength must exceed its minimum."
            )

    @property
    def center_nm(self) -> float:
        return (self.wavelength_min_nm + self.wavelength_max_nm) / 2.0

    @classmethod
    def from_center(
        cls,
        name: str,
        *,
        center_nm: float,
        half_width_nm: float,
    ) -> "HarmonicWindow":
        """Construct a window from its centre and positive half-width."""

        if half_width_nm <= 0:
            raise ValueError("Harmonic half-width must be positive.")
        return cls(
            name=name,
            wavelength_min_nm=center_nm - half_width_nm,
            wavelength_max_nm=center_nm + half_width_nm,
        )


@dataclass(frozen=True, slots=True)
class TransmissionCurve:
    """Wavelength-dependent filter transmission expressed as fractions."""

    wavelengths_nm: np.ndarray
    transmission_fraction: np.ndarray
    source: str = ""

    def __post_init__(self) -> None:
        wavelengths = np.asarray(self.wavelengths_nm, dtype=float)
        transmission = np.asarray(self.transmission_fraction, dtype=float)

        if wavelengths.ndim != 1 or transmission.ndim != 1:
            raise ValueError("Transmission curve arrays must be one-dimensional.")
        if wavelengths.shape != transmission.shape or wavelengths.size < 2:
            raise ValueError(
                "Transmission wavelengths and values must have matching "
                "shapes containing at least two points."
            )
        if not np.all(np.isfinite(wavelengths)):
            raise ValueError("Transmission wavelengths must be finite.")
        if not np.all(np.diff(wavelengths) > 0):
            raise ValueError("Transmission wavelengths must increase strictly.")
        if not np.all(np.isfinite(transmission)):
            raise ValueError("Transmission values must be finite.")
        if np.any(transmission <= 0) or np.any(transmission > 1):
            raise ValueError(
                "Transmission values must be fractions greater than zero "
                "and no greater than one."
            )

        object.__setattr__(self, "wavelengths_nm", wavelengths.copy())
        object.__setattr__(self, "transmission_fraction", transmission.copy())

    @classmethod
    def from_csv(cls, path: str | Path) -> "TransmissionCurve":
        """Load columns named wavelength_nm and transmission_fraction."""

        path = Path(path).expanduser().resolve()
        wavelengths: list[float] = []
        transmissions: list[float] = []

        with path.open("r", newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            required = {"wavelength_nm", "transmission_fraction"}
            if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                raise ValueError(
                    f"Transmission CSV must contain {sorted(required)}: {path}"
                )

            for row_number, row in enumerate(reader, start=2):
                try:
                    wavelengths.append(float(row["wavelength_nm"]))
                    transmissions.append(float(row["transmission_fraction"]))
                except (TypeError, ValueError) as error:
                    raise ValueError(
                        f"Invalid transmission value in {path}, row {row_number}."
                    ) from error

        return cls(
            wavelengths_nm=np.asarray(wavelengths),
            transmission_fraction=np.asarray(transmissions),
            source=str(path),
        )


@dataclass(frozen=True, slots=True)
class HarmonicResult:
    """One integrated harmonic result from one saved measurement."""

    measurement_number: int
    harmonic: str
    wavelength_min_nm: float
    wavelength_max_nm: float
    sample_angle_deg: float
    waveplate_angle_deg: float
    # Canonical achieved mean power propagated from Measurement.power_mw.
    power_mw: float | None
    integrated_signal: float
    raw_integrated_signal: float
    background_corrected_integral: float
    raw_peak_signal: float
    peak_signal: float
    peak_wavelength_nm: float
    background_subtracted: bool
    background_name: str | None
    transmission_corrected: bool
    transmission_source: str | None
    saturated: bool
    window_saturated: bool
    measurement_timestamp: float = 0.0
    fluence_mj_cm2: float | None = None
    intensity_w_cm2: float | None = None
    integration_time_ms: float = 0.0
    averages: int = 1
    spectrometer_serial: str = ""
    transmission_fraction: float | None = None
    analysis_format_version: int = 1
    target_power_mw: float | None = None
    power_rms_mw: float | None = None
    power_measurement_duration_s: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def achieved_power_mw(self) -> float | None:
        """Explicit read-only name for the achieved mean ``power_mw``."""

        return self.power_mw


def analyse_dataset(
    dataset: ExperimentDataset,
    windows: Iterable[HarmonicWindow],
    *,
    background: BackgroundSpectrum | None = None,
    transmission_fraction: float | None = None,
    transmission_curve: TransmissionCurve | None = None,
    minimum_transmission_fraction: float = 1e-6,
) -> list[HarmonicResult]:
    """Integrate one or more harmonic windows for every measurement."""

    windows = list(windows)
    if not windows:
        raise ValueError("At least one harmonic window is required.")
    if len({window.name for window in windows}) != len(windows):
        raise ValueError("Harmonic names must be unique.")
    if transmission_fraction is not None and transmission_curve is not None:
        raise ValueError(
            "Use either a scalar transmission fraction or a curve, not both."
        )
    minimum_transmission_fraction = float(minimum_transmission_fraction)
    if not np.isfinite(minimum_transmission_fraction) or not (
        0 < minimum_transmission_fraction <= 1
    ):
        raise ValueError(
            "Minimum transmission fraction must lie in (0, 1]."
        )
    if transmission_fraction is not None:
        transmission_fraction = float(transmission_fraction)
        if not np.isfinite(transmission_fraction) or not (
            0 < transmission_fraction <= 1
        ):
            raise ValueError(
                "Transmission fraction must be greater than zero and at most one."
            )
        if transmission_fraction < minimum_transmission_fraction:
            raise ValueError(
                "Transmission fraction is below the configured safe correction "
                "threshold."
            )

    results: list[HarmonicResult] = []

    for measurement_number, measurement in enumerate(dataset, start=1):
        spectrum = measurement.spectrum
        if spectrum is None:
            raise ValueError(
                f"Measurement {measurement_number} has no spectrum."
            )

        wavelengths, raw = _validated_arrays(spectrum)
        corrected = raw.copy()

        if background is not None:
            corrected -= _validated_background(
                spectrum,
                background,
                measurement_number=measurement_number,
            )

        for window in windows:
            if (
                window.wavelength_min_nm < wavelengths[0]
                or window.wavelength_max_nm > wavelengths[-1]
            ):
                raise ValueError(
                    f"Harmonic {window.name!r} lies outside the wavelength "
                    f"range in measurement {measurement_number}."
                )

            interior = (
                (wavelengths > window.wavelength_min_nm)
                & (wavelengths < window.wavelength_max_nm)
            )
            x = np.concatenate(
                (
                    [window.wavelength_min_nm],
                    wavelengths[interior],
                    [window.wavelength_max_nm],
                )
            )
            raw_y = np.interp(x, wavelengths, raw)
            background_corrected_y = np.interp(x, wavelengths, corrected)
            y = background_corrected_y.copy()
            transmission_source: str | None = None

            if transmission_fraction is not None:
                y /= transmission_fraction
                transmission_source = "scalar"
            elif transmission_curve is not None:
                if (
                    x[0] < transmission_curve.wavelengths_nm[0]
                    or x[-1] > transmission_curve.wavelengths_nm[-1]
                ):
                    raise ValueError(
                        f"Transmission curve does not cover harmonic "
                        f"{window.name!r}."
                    )
                transmission = np.interp(
                    x,
                    transmission_curve.wavelengths_nm,
                    transmission_curve.transmission_fraction,
                )
                if np.any(transmission < minimum_transmission_fraction):
                    raise ValueError(
                        f"Transmission for harmonic {window.name!r} falls below "
                        "the configured safe correction threshold."
                    )
                y /= transmission
                transmission_source = transmission_curve.source or "curve"

            peak_index = int(np.argmax(y))
            results.append(
                HarmonicResult(
                    measurement_number=measurement_number,
                    measurement_timestamp=measurement.timestamp,
                    harmonic=window.name,
                    wavelength_min_nm=window.wavelength_min_nm,
                    wavelength_max_nm=window.wavelength_max_nm,
                    sample_angle_deg=measurement.sample_angle_deg,
                    waveplate_angle_deg=measurement.waveplate_angle_deg,
                    power_mw=measurement.power_mw,
                    target_power_mw=measurement.target_power_mw,
                    power_rms_mw=measurement.power_rms_mw,
                    power_measurement_duration_s=(
                        measurement.power_measurement_duration_s
                    ),
                    fluence_mj_cm2=measurement.fluence_mj_cm2,
                    intensity_w_cm2=measurement.intensity_w_cm2,
                    integration_time_ms=spectrum.integration_time_ms,
                    averages=spectrum.averages,
                    spectrometer_serial=spectrum.serial,
                    integrated_signal=float(np.trapezoid(y, x)),
                    raw_integrated_signal=float(np.trapezoid(raw_y, x)),
                    background_corrected_integral=float(
                        np.trapezoid(background_corrected_y, x)
                    ),
                    raw_peak_signal=float(np.max(raw_y)),
                    peak_signal=float(y[peak_index]),
                    peak_wavelength_nm=float(x[peak_index]),
                    background_subtracted=background is not None,
                    background_name=(
                        background.name if background is not None else None
                    ),
                    transmission_corrected=transmission_source is not None,
                    transmission_source=transmission_source,
                    transmission_fraction=transmission_fraction,
                    saturated=measurement.saturated,
                    window_saturated=bool(np.any(raw_y >= 65_535.0)),
                )
            )

    return results


def save_results_csv(
    results: Iterable[HarmonicResult],
    path: str | Path,
) -> Path:
    """Save derived harmonic results without modifying the source dataset."""

    results = list(results)
    if not results:
        raise ValueError("Cannot save an empty harmonic result collection.")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(results[0].as_dict())

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(result.as_dict() for result in results)

    return path


def load_results_csv(path: str | Path) -> list[HarmonicResult]:
    """Load a saved harmonic result table with explicit scalar types.

    ``path`` may name ``harmonic_signals.csv`` directly or its containing
    analysis directory. Tables written before analysis format version 1 are
    accepted; publication-provenance fields that did not yet exist receive
    conservative empty values.
    """

    path = Path(path).expanduser().resolve()
    if path.is_dir():
        path = path / "harmonic_signals.csv"
    if not path.exists():
        raise FileNotFoundError(f"Harmonic result table does not exist: {path}")

    results: list[HarmonicResult] = []
    with path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise ValueError(f"Harmonic result table has no header: {path}")

        required = {
            "measurement_number",
            "harmonic",
            "wavelength_min_nm",
            "wavelength_max_nm",
            "sample_angle_deg",
            "waveplate_angle_deg",
            "integrated_signal",
            "raw_integrated_signal",
            "background_corrected_integral",
            "raw_peak_signal",
            "peak_signal",
            "peak_wavelength_nm",
            "background_subtracted",
            "transmission_corrected",
            "saturated",
            "window_saturated",
        }
        missing = sorted(required - set(reader.fieldnames))
        if missing:
            raise ValueError(
                f"Harmonic result table is missing columns {missing}: {path}"
            )

        for row_number, row in enumerate(reader, start=2):
            try:
                results.append(
                    HarmonicResult(
                        measurement_number=_csv_int(
                            row, "measurement_number", row_number
                        ),
                        measurement_timestamp=_csv_float(
                            row,
                            "measurement_timestamp",
                            row_number,
                            default=0.0,
                        ),
                        harmonic=_csv_text(row, "harmonic", row_number),
                        wavelength_min_nm=_csv_float(
                            row, "wavelength_min_nm", row_number
                        ),
                        wavelength_max_nm=_csv_float(
                            row, "wavelength_max_nm", row_number
                        ),
                        sample_angle_deg=_csv_float(
                            row, "sample_angle_deg", row_number
                        ),
                        waveplate_angle_deg=_csv_float(
                            row, "waveplate_angle_deg", row_number
                        ),
                        power_mw=_csv_optional_float(row.get("power_mw")),
                        target_power_mw=_csv_optional_float(
                            row.get("target_power_mw")
                        ),
                        power_rms_mw=_csv_optional_float(
                            row.get("power_rms_mw")
                        ),
                        power_measurement_duration_s=_csv_optional_float(
                            row.get("power_measurement_duration_s")
                        ),
                        fluence_mj_cm2=_csv_optional_float(
                            row.get("fluence_mj_cm2")
                        ),
                        intensity_w_cm2=_csv_optional_float(
                            row.get("intensity_w_cm2")
                        ),
                        integration_time_ms=_csv_float(
                            row,
                            "integration_time_ms",
                            row_number,
                            default=0.0,
                        ),
                        averages=_csv_int(
                            row, "averages", row_number, default=1
                        ),
                        spectrometer_serial=str(
                            row.get("spectrometer_serial", "")
                        ),
                        integrated_signal=_csv_float(
                            row, "integrated_signal", row_number
                        ),
                        raw_integrated_signal=_csv_float(
                            row, "raw_integrated_signal", row_number
                        ),
                        background_corrected_integral=_csv_float(
                            row,
                            "background_corrected_integral",
                            row_number,
                        ),
                        raw_peak_signal=_csv_float(
                            row, "raw_peak_signal", row_number
                        ),
                        peak_signal=_csv_float(
                            row, "peak_signal", row_number
                        ),
                        peak_wavelength_nm=_csv_float(
                            row, "peak_wavelength_nm", row_number
                        ),
                        background_subtracted=_csv_bool(
                            row, "background_subtracted", row_number
                        ),
                        background_name=_csv_optional_text(
                            row.get("background_name")
                        ),
                        transmission_corrected=_csv_bool(
                            row, "transmission_corrected", row_number
                        ),
                        transmission_source=_csv_optional_text(
                            row.get("transmission_source")
                        ),
                        transmission_fraction=_csv_optional_float(
                            row.get("transmission_fraction")
                        ),
                        saturated=_csv_bool(
                            row, "saturated", row_number
                        ),
                        window_saturated=_csv_bool(
                            row, "window_saturated", row_number
                        ),
                        analysis_format_version=_csv_int(
                            row,
                            "analysis_format_version",
                            row_number,
                            default=0,
                        ),
                    )
                )
            except ValueError as error:
                raise ValueError(
                    f"Invalid harmonic result in {path}, row {row_number}: "
                    f"{error}"
                ) from error

    if not results:
        raise ValueError(f"Harmonic result table contains no rows: {path}")
    return results


def _csv_text(
    row: dict[str, str],
    name: str,
    row_number: int,
) -> str:
    value = str(row.get(name, "")).strip()
    if not value:
        raise ValueError(f"missing {name!r} at row {row_number}")
    return value


def _csv_optional_text(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    return str(value)


def _csv_float(
    row: dict[str, str],
    name: str,
    row_number: int,
    *,
    default: float | None = None,
) -> float:
    value = row.get(name)
    if value is None or not str(value).strip():
        if default is not None:
            return default
        raise ValueError(f"missing {name!r} at row {row_number}")
    result = float(value)
    if not np.isfinite(result):
        raise ValueError(f"non-finite {name!r} at row {row_number}")
    return result


def _csv_optional_float(value: str | None) -> float | None:
    if value is None or not str(value).strip():
        return None
    result = float(value)
    if not np.isfinite(result):
        raise ValueError("optional numeric value is not finite")
    return result


def _csv_int(
    row: dict[str, str],
    name: str,
    row_number: int,
    *,
    default: int | None = None,
) -> int:
    value = row.get(name)
    if value is None or not str(value).strip():
        if default is not None:
            return default
        raise ValueError(f"missing {name!r} at row {row_number}")
    return int(value)


def _csv_bool(
    row: dict[str, str],
    name: str,
    row_number: int,
) -> bool:
    value = str(row.get(name, "")).strip().lower()
    if value in {"true", "1", "yes"}:
        return True
    if value in {"false", "0", "no"}:
        return False
    raise ValueError(f"invalid boolean {name!r} at row {row_number}")


def _validated_arrays(spectrum: Spectrum) -> tuple[np.ndarray, np.ndarray]:
    wavelengths = np.asarray(spectrum.wavelengths, dtype=float)
    intensities = np.asarray(spectrum.intensities, dtype=float)

    if wavelengths.ndim != 1 or intensities.ndim != 1:
        raise ValueError("Spectrum arrays must be one-dimensional.")
    if wavelengths.shape != intensities.shape:
        raise ValueError("Spectrum arrays must have matching shapes.")
    if not np.all(np.isfinite(wavelengths)):
        raise ValueError("Spectrum wavelengths must be finite.")
    if not np.all(np.diff(wavelengths) > 0):
        raise ValueError("Spectrum wavelengths must increase strictly.")
    if not np.all(np.isfinite(intensities)):
        raise ValueError("Spectrum intensities must be finite.")

    return wavelengths, intensities


def _validated_background(
    spectrum: Spectrum,
    background: BackgroundSpectrum,
    *,
    measurement_number: int,
) -> np.ndarray:
    wavelengths, _ = _validated_arrays(spectrum)
    background_wavelengths, background_intensities = _validated_arrays(
        background.spectrum
    )

    if spectrum.serial != background.spectrum.serial:
        raise ValueError(
            f"Background serial does not match measurement {measurement_number}."
        )
    if (
        wavelengths.shape != background_wavelengths.shape
        or not np.allclose(wavelengths, background_wavelengths)
    ):
        raise ValueError(
            f"Background wavelength grid does not match measurement "
            f"{measurement_number}."
        )
    if not np.isclose(
        spectrum.integration_time_ms,
        background.spectrum.integration_time_ms,
    ):
        raise ValueError(
            f"Background integration time does not match measurement "
            f"{measurement_number}; capture a matching background rather than "
            "silently scaling it."
        )
    if (
        spectrum.dark_corrected != background.spectrum.dark_corrected
        or spectrum.nonlinearity_corrected
        != background.spectrum.nonlinearity_corrected
    ):
        raise ValueError(
            f"Background correction flags do not match measurement "
            f"{measurement_number}."
        )

    return background_intensities
