"""
experiment_config.py

Configuration for experiments.

All user-adjustable experiment parameters are collected here rather
than being scattered throughout the code.

The intention is that an experiment can be reproduced simply by
saving one ExperimentConfig alongside the acquired data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import Any


# =============================================================================
# Spectrometer
# =============================================================================

@dataclass(slots=True)
class SpectrometerConfig:
    """
    Spectrometer acquisition settings.
    """

    integration_time_ms: float = 10.0

    averages: int = 1

    # Independent acquisitions saved at each waveplate/sample-angle point.
    # This is deliberately separate from ``averages``, which is performed
    # inside one spectrometer acquisition and therefore cannot estimate
    # between-spectrum uncertainty.
    spectra_per_point: int = 1

    boxcar_width: int = 0

    def __post_init__(self) -> None:
        self.validate_for_run()

    def validate_for_run(self) -> None:
        """Validate settings, including values assigned after construction."""

        if self.averages < 1:
            raise ValueError("Spectrometer averages must be at least one.")
        if self.spectra_per_point < 1:
            raise ValueError("Spectra per point must be at least one.")


# =============================================================================
# Background acquisition
# =============================================================================

@dataclass(slots=True)
class BackgroundConfig:
    """Pre-scan shutter-closed background acquisition settings."""

    enabled: bool = True

    name: str = "pre_scan_dark"

    averages: int = 5

    settle_time_s: float = 0.05

    notes: str = "Shutter-closed background acquired before the scan."

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Background name must not be empty.")
        if self.averages < 1:
            raise ValueError("Background averages must be at least one.")
        if self.settle_time_s < 0:
            raise ValueError("Background settle time must not be negative.")


# =============================================================================
# Incident-power acquisition
# =============================================================================

@dataclass(slots=True)
class PowerMeasurementConfig:
    """Incident-power sampling performed by the retractable meter probe.

    ``enabled`` remains false until the laboratory-specific in/out stage
    positions have been measured and entered in :mod:`hardware.config`.
    Whenever it is enabled, the normal cadence is one measurement after each
    waveplate setting and before the corresponding sample-rotation block.
    """

    enabled: bool = False

    cadence: str = "per_intensity"

    wavelength_nm: float = 2000.0

    # Exact option label verified live on sensor 3141552. ``wavelength_nm``
    # remains the experiment's physical fundamental wavelength and is saved
    # independently. Re-verify this returned label if the sensor is swapped.
    wavelength_option: str | None = ">800"

    measurement_duration_s: float = 10.0

    pre_measurement_settle_s: float = 3.0

    measurement_mode: str = "Power"

    # Ophir option label, deliberately not a fragile numeric option index.
    # AUTO permits reads across the verified meter ranges. The independent
    # raw-power safety ceiling still controls experiment continuation.
    range_option: str | None = "AUTO"

    # Proceeding after a failed/invalid incident-power read would expose the
    # sample at unknown power. It therefore requires an explicit opt-in.
    continue_without_power_on_meter_error: bool = False

    maximum_allowed_power_mw: float | None = 50.0

    def __post_init__(self) -> None:
        allowed_cadences = {
            "per_intensity",
            "per_measurement",
            "disabled",
        }
        if self.cadence not in allowed_cadences:
            raise ValueError(
                "Power-measurement cadence must be one of "
                f"{sorted(allowed_cadences)}."
            )
        if not math.isfinite(float(self.wavelength_nm)) or self.wavelength_nm <= 0:
            raise ValueError("Power-meter wavelength must be positive.")
        if self.wavelength_option is not None and not self.wavelength_option.strip():
            raise ValueError("Power-meter wavelength option must not be empty.")
        if (
            not math.isfinite(float(self.measurement_duration_s))
            or self.measurement_duration_s <= 0
        ):
            raise ValueError(
                "Power-measurement duration must be greater than zero."
            )
        if (
            not math.isfinite(float(self.pre_measurement_settle_s))
            or self.pre_measurement_settle_s < 0
        ):
            raise ValueError(
                "Power-meter pre-measurement settle time must not be negative."
            )
        if self.measurement_mode != "Power":
            raise ValueError(
                "The Ophir integration currently supports measurement_mode "
                "'Power' only."
            )
        if self.range_option is not None and not self.range_option.strip():
            raise ValueError("Power-meter range option must not be empty.")
        if self.maximum_allowed_power_mw is not None and (
            not math.isfinite(float(self.maximum_allowed_power_mw))
            or self.maximum_allowed_power_mw <= 0
        ):
            raise ValueError("Maximum allowed power must be positive.")

    def validate_for_run(self) -> None:
        """Validate settings that become mandatory only when enabled."""

        self.__post_init__()
        if self.enabled and self.cadence != "disabled":
            if self.wavelength_option is None:
                raise ValueError(
                    "Power metering is enabled but wavelength_option is not "
                    "set. Select an exact option returned by the attached "
                    "Ophir sensor so wavelength_nm cannot be mistaken for an "
                    "unverified calibration setting."
                )




# =============================================================================
# Closed-loop target-power control
# =============================================================================

@dataclass(slots=True)
class TargetPowerConfig:
    """Feedback settings for scanning requested powers instead of angles.

    The waveplate bounds must describe one physically reviewed monotonic
    branch.  They intentionally default to ``None`` so the software cannot
    guess a safe branch of the periodic waveplate/polariser response.
    """

    waveplate_min_deg: float | None = None

    waveplate_max_deg: float | None = None

    monotonic_direction: str = "increasing"

    tolerance_mw: float = 0.2

    maximum_iterations: int = 8

    minimum_angle_step_deg: float = 0.02

    calibration_path: Path | None = None

    def validate_for_run(
        self,
        *,
        target_powers_mw,
        power_meter: PowerMeasurementConfig,
    ) -> None:
        if not power_meter.enabled or power_meter.cadence != "per_intensity":
            raise ValueError(
                "Target-power scans require power_meter.enabled=True and "
                "power_meter.cadence='per_intensity'."
            )
        if self.waveplate_min_deg is None or self.waveplate_max_deg is None:
            raise ValueError(
                "Target-power scans require physically verified "
                "waveplate_min_deg and waveplate_max_deg values."
            )
        lower = float(self.waveplate_min_deg)
        upper = float(self.waveplate_max_deg)
        if not math.isfinite(lower) or not math.isfinite(upper) or upper <= lower:
            raise ValueError(
                "Target-power waveplate bounds must be finite and max > min."
            )
        direction = str(self.monotonic_direction).strip().lower()
        if direction not in {"increasing", "decreasing"}:
            raise ValueError(
                "Target-power monotonic_direction must be 'increasing' or "
                "'decreasing'."
            )
        if not math.isfinite(float(self.tolerance_mw)) or self.tolerance_mw <= 0:
            raise ValueError("Target-power tolerance_mw must be positive.")
        if int(self.maximum_iterations) < 1:
            raise ValueError("Target-power maximum_iterations must be at least one.")
        if (
            not math.isfinite(float(self.minimum_angle_step_deg))
            or self.minimum_angle_step_deg <= 0
        ):
            raise ValueError(
                "Target-power minimum_angle_step_deg must be positive."
            )
        if self.calibration_path is not None and not Path(
            self.calibration_path
        ).is_file():
            raise ValueError(
                f"Target-power calibration file does not exist: "
                f"{self.calibration_path}"
            )
        targets = [float(value) for value in target_powers_mw]
        if not targets:
            raise ValueError("At least one target power is required.")
        if any(not math.isfinite(value) or value <= 0 for value in targets):
            raise ValueError("All target powers must be finite and positive.")
        limit = power_meter.maximum_allowed_power_mw
        if limit is not None and any(value > float(limit) for value in targets):
            raise ValueError(
                "A requested target power exceeds maximum_allowed_power_mw."
            )


# =============================================================================
# Experimental metadata
# =============================================================================

@dataclass(slots=True)
class OpticalFilterConfig:
    """Description of an optical filter installed for one experiment."""

    name: str

    manufacturer: str | None = None

    part_number: str | None = None

    intended_harmonics: list[str] = field(default_factory=list)

    nominal_transmission_fraction: float | None = None

    transmission_curve_file: Path | None = None

    notes: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Optical filter name must not be empty.")
        if self.nominal_transmission_fraction is not None and not (
            0 < self.nominal_transmission_fraction <= 1
        ):
            raise ValueError(
                "Nominal filter transmission must be a fraction in (0, 1]."
            )


@dataclass(slots=True)
class ExperimentMetadataConfig:
    """Free-form and structured information describing an experimental run."""

    run_label: str = ""

    sample_name: str = ""

    notes: str = ""

    intended_harmonics: list[str] = field(default_factory=list)

    filters: list[OpticalFilterConfig] = field(default_factory=list)

    extra: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Shutter
# =============================================================================

@dataclass(slots=True)
class ShutterConfig:
    """
    Beam shutter timing.
    """

    open_delay_s: float = 0.020

    close_delay_s: float = 0.010


# =============================================================================
# Motion
# =============================================================================

@dataclass(slots=True)
class MotionConfig:
    """
    Motion settings.
    """

    settle_time_s: float = 0.250

    home_before_scan: bool = False


# =============================================================================
# Saving
# =============================================================================

@dataclass(slots=True)
class SavingConfig:
    """
    Output settings.
    """

    output_directory: Path = Path("results")

    experiment_name: str = "rotation_intensity_scan"

    save_every_measurement: bool = True

    overwrite: bool = False


# =============================================================================
# Test Mode
# =============================================================================

@dataclass(slots=True)
class TestModeConfig:
    """
    Behaviour used while developing hardware/software.
    """

    enabled: bool = False

    save_data: bool = False

    maximum_measurements: int | None = None

    simulate_only: bool = False


# =============================================================================
# Experiment
# =============================================================================

@dataclass(slots=True)
class ExperimentConfig:
    """
    Complete experiment configuration.
    """

    spectrometer: SpectrometerConfig = field(
        default_factory=SpectrometerConfig
    )

    background: BackgroundConfig = field(
        default_factory=BackgroundConfig
    )

    power_meter: PowerMeasurementConfig = field(
        default_factory=PowerMeasurementConfig
    )

    target_power: TargetPowerConfig = field(
        default_factory=TargetPowerConfig
    )

    metadata: ExperimentMetadataConfig = field(
        default_factory=ExperimentMetadataConfig
    )

    shutter: ShutterConfig = field(
        default_factory=ShutterConfig
    )

    motion: MotionConfig = field(
        default_factory=MotionConfig
    )

    saving: SavingConfig = field(
        default_factory=SavingConfig
    )

    test: TestModeConfig = field(
        default_factory=TestModeConfig
    )
