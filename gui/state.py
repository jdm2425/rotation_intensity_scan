"""Hardware-independent state and validated GUI scan requests."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import math
from pathlib import Path
from typing import Iterable

from analysis.harmonic_analysis import HarmonicWindow


class ConnectionState(StrEnum):
    """Connection state displayed for one device."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    WARNING = "warning"
    FAULT = "fault"


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    """One immutable device status update safe to pass to the GUI thread."""

    key: str
    name: str
    connection: ConnectionState
    identity: str = ""
    value: str = ""
    detail: str = ""
    available: bool = True
    required: bool = True


@dataclass(frozen=True, slots=True)
class GuiSnapshot:
    """Complete status used by the persistent safety header and device table."""

    devices: tuple[DeviceSnapshot, ...]
    shutter_closed: bool | None
    probe_out: bool | None
    beam_power_mw: float | None = None
    busy: bool = False
    simulation: bool = True

    @property
    def all_connected(self) -> bool:
        required = tuple(device for device in self.devices if device.required)
        return bool(required) and all(
            device.connection is ConnectionState.CONNECTED
            for device in required
        )

    @property
    def any_connected(self) -> bool:
        return any(
            device.connection is ConnectionState.CONNECTED
            for device in self.devices
        )

    @property
    def sample_path_safe(self) -> bool:
        return self.shutter_closed is True and self.probe_out is True


@dataclass(frozen=True, slots=True)
class TargetPowerRequest:
    """Validated manual target-power operation from the Alignment workspace."""

    target_power_mw: float
    waveplate_min_deg: float
    waveplate_max_deg: float
    monotonic_direction: str = "increasing"
    target_tolerance_mw: float = 0.2
    target_maximum_iterations: int = 8
    target_minimum_angle_step_deg: float = 0.02
    power_calibration_path: Path | None = None
    output_directory: Path = Path("results")

    def __post_init__(self) -> None:
        numeric = (
            self.target_power_mw,
            self.waveplate_min_deg,
            self.waveplate_max_deg,
            self.target_tolerance_mw,
            self.target_minimum_angle_step_deg,
        )
        if any(not math.isfinite(float(value)) for value in numeric):
            raise ValueError("Manual target-power settings must be finite.")
        if not 0.0 < float(self.target_power_mw) <= 20.0:
            raise ValueError("Target power must be above zero and at most 20 mW.")
        if float(self.waveplate_max_deg) <= float(self.waveplate_min_deg):
            raise ValueError("Target-power branch maximum must exceed its minimum.")
        if self.monotonic_direction not in {"increasing", "decreasing"}:
            raise ValueError("Target-power direction must be increasing or decreasing.")
        if float(self.target_tolerance_mw) <= 0.0:
            raise ValueError("Target-power tolerance must be positive.")
        if int(self.target_maximum_iterations) < 1:
            raise ValueError("Maximum feedback iterations must be at least one.")
        if float(self.target_minimum_angle_step_deg) <= 0.0:
            raise ValueError("Minimum feedback angle step must be positive.")
        if self.power_calibration_path is not None and not Path(
            self.power_calibration_path
        ).is_file():
            raise ValueError(
                f"Power calibration does not exist: {self.power_calibration_path}"
            )


@dataclass(frozen=True, slots=True)
class ScanRequest:
    """Validated scan settings emitted by the GUI."""

    sample_angles_deg: tuple[float, ...]
    intensity_values: tuple[float, ...]
    rotation_target: str = "sample"
    intensity_mode: str = "target_power_mw"
    spectra_per_point: int = 1
    integration_time_ms: float = 10.0
    averages: int = 1
    acquire_background: bool = True
    output_directory: Path = Path("results")
    experiment_name: str = "campaign_scan"
    notes: str = ""
    waveplate_min_deg: float = 0.0
    waveplate_max_deg: float = 10.0
    monotonic_direction: str = "increasing"
    target_tolerance_mw: float = 0.2
    target_maximum_iterations: int = 8
    target_minimum_angle_step_deg: float = 0.02
    power_calibration_path: Path | None = None
    driving_wavelength_nm: float = 2000.0
    harmonic_windows: tuple[HarmonicWindow, ...] = ()

    def __post_init__(self) -> None:
        if self.rotation_target not in {"sample", "polarization_half_waveplate"}:
            raise ValueError(
                "Rotation target must be sample or polarization_half_waveplate."
            )
        if self.intensity_mode not in {"target_power_mw", "waveplate_angle_deg"}:
            raise ValueError(
                "Intensity mode must be target_power_mw or waveplate_angle_deg."
            )
        _require_finite(self.sample_angles_deg, "sample angles")
        _require_finite(self.intensity_values, "intensity values")
        if not self.sample_angles_deg:
            raise ValueError("At least one sample angle is required.")
        if not self.intensity_values:
            raise ValueError("At least one intensity value is required.")
        if self.intensity_mode == "target_power_mw" and any(
            value <= 0 for value in self.intensity_values
        ):
            raise ValueError("Target powers must be positive.")
        if self.intensity_mode == "target_power_mw" and any(
            value > 20.0 for value in self.intensity_values
        ):
            raise ValueError("Target powers cannot exceed the 20 mW safety ceiling.")
        if self.intensity_mode == "target_power_mw":
            if not math.isfinite(float(self.waveplate_min_deg)) or not math.isfinite(
                float(self.waveplate_max_deg)
            ) or self.waveplate_max_deg <= self.waveplate_min_deg:
                raise ValueError("Target-power branch maximum must exceed its minimum.")
            if self.monotonic_direction not in {"increasing", "decreasing"}:
                raise ValueError("Target-power direction must be increasing or decreasing.")
            if self.target_tolerance_mw <= 0:
                raise ValueError("Target-power tolerance must be positive.")
            if self.target_maximum_iterations < 1:
                raise ValueError("Target-power maximum iterations must be at least one.")
            if self.target_minimum_angle_step_deg <= 0:
                raise ValueError("Target-power minimum angle step must be positive.")
            if self.power_calibration_path is not None and not Path(
                self.power_calibration_path
            ).is_file():
                raise ValueError(
                    f"Power calibration does not exist: {self.power_calibration_path}"
                )
        if int(self.spectra_per_point) < 1:
            raise ValueError("Spectra per point must be at least one.")
        if int(self.averages) < 1:
            raise ValueError("Spectrometer averages must be at least one.")
        if not math.isfinite(float(self.integration_time_ms)) or (
            self.integration_time_ms <= 0
        ):
            raise ValueError("Integration time must be positive.")
        if not str(self.experiment_name).strip():
            raise ValueError("Experiment name must not be empty.")
        if not math.isfinite(float(self.driving_wavelength_nm)) or (
            self.driving_wavelength_nm <= 0
        ):
            raise ValueError("Driving wavelength must be positive.")
        names = [window.name for window in self.harmonic_windows]
        if len(set(names)) != len(names):
            raise ValueError("Harmonic window names must be unique.")

    @property
    def total_spectra(self) -> int:
        return (
            len(self.sample_angles_deg)
            * len(self.intensity_values)
            * int(self.spectra_per_point)
        )

    @property
    def rotation_target_name(self) -> str:
        """Human-readable object mounted on the second rotation stage."""

        return (
            "sample"
            if self.rotation_target == "sample"
            else "polarisation half-waveplate"
        )

    @property
    def rotation_angle_name(self) -> str:
        """Human-readable name for the stored physical stage angle."""

        return (
            "sample angle"
            if self.rotation_target == "sample"
            else "polarisation HWP mount angle"
        )

    @property
    def rotation_angle_label(self) -> str:
        """Sentence-leading angle label while preserving the HWP acronym."""

        return (
            "Sample angle"
            if self.rotation_target == "sample"
            else "Polarisation HWP mount angle"
        )


@dataclass(frozen=True, slots=True)
class LiveViewRequest:
    """Initial settings for the alignment spectrometer stream."""

    integration_time_ms: float = 10.0
    averages: int = 1
    refresh_interval_s: float = 0.1
    saturation_level: float = 65_535.0
    output_directory: Path = Path("results/live_spectrometer")

    def __post_init__(self) -> None:
        if not math.isfinite(float(self.integration_time_ms)) or (
            self.integration_time_ms <= 0
        ):
            raise ValueError("Live integration time must be positive.")
        if int(self.averages) < 1:
            raise ValueError("Live averages must be at least one.")
        if not math.isfinite(float(self.refresh_interval_s)) or (
            self.refresh_interval_s <= 0
        ):
            raise ValueError("Live refresh interval must be positive.")
        if not math.isfinite(float(self.saturation_level)) or (
            self.saturation_level <= 0
        ):
            raise ValueError("Saturation level must be positive.")


@dataclass(frozen=True, slots=True)
class CalibrationRequest:
    """Operator-reviewed bounded waveplate-power mapping request."""

    start_deg: float
    stop_deg: float
    step_deg: float
    noise_tolerance_mw: float = 0.05
    output_directory: Path = Path("results/waveplate_calibration")

    def __post_init__(self) -> None:
        values = (self.start_deg, self.stop_deg, self.step_deg, self.noise_tolerance_mw)
        if any(not math.isfinite(float(value)) for value in values):
            raise ValueError("Calibration settings must be finite.")
        if self.stop_deg <= self.start_deg:
            raise ValueError("Calibration stop must exceed start.")
        if self.step_deg <= 0:
            raise ValueError("Calibration step must be positive.")
        if self.noise_tolerance_mw < 0:
            raise ValueError("Calibration noise tolerance cannot be negative.")

    @property
    def angles_deg(self) -> tuple[float, ...]:
        from tools.waveplate_power_control import scan_angles
        return scan_angles(self.start_deg, self.stop_deg, self.step_deg)


def parse_number_list(text: str, *, field_name: str) -> tuple[float, ...]:
    """Parse comma- or whitespace-separated finite numbers."""

    tokens = str(text).replace(",", " ").split()
    if not tokens:
        raise ValueError(f"{field_name} must contain at least one number.")
    try:
        values = tuple(float(token) for token in tokens)
    except ValueError as error:
        raise ValueError(
            f"{field_name} must contain numbers separated by spaces or commas."
        ) from error
    _require_finite(values, field_name)
    return values


def inclusive_range(start: float, stop: float, step: float) -> tuple[float, ...]:
    """Return an inclusive finite range in either direction."""

    start, stop, step = float(start), float(stop), float(step)
    if any(not math.isfinite(value) for value in (start, stop, step)):
        raise ValueError("Range start, stop, and step must be finite.")
    if step == 0:
        raise ValueError("Range step cannot be zero.")
    direction = 1.0 if stop >= start else -1.0
    step = abs(step) * direction
    count = int(math.floor(abs(stop - start) / abs(step)))
    values = [start + index * step for index in range(count + 1)]
    if not math.isclose(values[-1], stop, rel_tol=0.0, abs_tol=1e-10):
        values.append(stop)
    return tuple(float(value) for value in values)


def parse_harmonic_windows(text: str) -> tuple[HarmonicWindow, ...]:
    """Parse ``H5:390:410, H7:275:295`` harmonic window definitions."""

    if not str(text).strip():
        return ()
    windows = []
    for definition in str(text).split(","):
        parts = [part.strip() for part in definition.split(":")]
        if len(parts) != 3:
            raise ValueError(
                "Harmonic windows must use NAME:MIN_NM:MAX_NM separated by commas."
            )
        try:
            windows.append(HarmonicWindow(parts[0], float(parts[1]), float(parts[2])))
        except ValueError as error:
            raise ValueError(f"Invalid harmonic window {definition.strip()!r}: {error}") from error
    return tuple(windows)


def _require_finite(values: Iterable[float], field_name: str) -> None:
    if any(not math.isfinite(float(value)) for value in values):
        raise ValueError(f"{field_name} must contain only finite numbers.")
