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