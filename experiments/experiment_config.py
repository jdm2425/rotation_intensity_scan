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

    boxcar_width: int = 0


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
