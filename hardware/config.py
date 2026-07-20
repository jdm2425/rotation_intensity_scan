"""
config.py

Central configuration for the Rotation + Intensity Scan project.

This module contains experiment-independent configuration only:

    • Hardware serial numbers
    • Default motion parameters
    • Default acquisition parameters

No hardware driver should contain hard-coded serial numbers.
"""

from __future__ import annotations

from dataclasses import dataclass


# =============================================================================
# Hardware configuration
# =============================================================================

@dataclass(frozen=True)
class RotationStageConfig:
    """
    Configuration for a motorised rotation stage.
    """

    serial: str
    name: str


@dataclass(frozen=True)
class ShutterConfig:
    """
    Configuration for the beam shutter.
    """

    serial: str
    name: str = "Beam Shutter"


@dataclass(frozen=True)
class LinearStageConfig:
    """Configuration for a PI linear insertion stage.

    The application limits are an additional software safety envelope. They
    do not replace the controller limits queried at connection time.
    """

    serial: str
    controller_model: str
    stage_model: str
    installed: bool = True
    axis: str = "1"
    name: str = "Linear Stage"
    application_min_mm: float = -12.0
    application_max_mm: float = 12.0
    in_position_mm: float | None = None
    out_position_mm: float | None = None
    velocity_mm_s: float | None = 1.0
    position_tolerance_mm: float = 0.01
    motion_timeout_s: float = 30.0


@dataclass(frozen=True)
class PowerMeterHardwareConfig:
    """Identity of the Ophir USB power-meter controller and sensor head."""

    controller_serial: str
    sensor_serial: str
    name: str = "Incident Power Meter"

# =============================================================================
# Shutter timing
# =============================================================================

@dataclass(frozen=True)
class ShutterTimingConfig:
    """
    Timing parameters for beam shutter operation.
    """

    open_delay_s: float = 0.10

    close_delay_s: float = 0.02

# =============================================================================
# Spectrometer
# =============================================================================

@dataclass(frozen=True)
class SpectrometerConfig:
    """
    Ocean Insight spectrometer configuration.
    """

    serial: str

    integration_time_ms: float = 10.0

    name: str = "Ocean SR"


# =============================================================================
# Installed hardware
# =============================================================================

#
# Waveplate rotation stage
#
WAVEPLATE = RotationStageConfig(
    serial="27268875",
    name="Waveplate",
)

#
# Sample rotation stage
#
# Replace the serial number below with the serial number
# of your second PRM1-Z8 controller.
#
SAMPLE_STAGE = RotationStageConfig(
    serial="27268870",
    name="Sample Stage",
)

#
# Beam shutter
#
SHUTTER = ShutterConfig(
    serial="37008491",
)

SHUTTER_TIMING = ShutterTimingConfig()

SPECTROMETER = SpectrometerConfig(
    serial="SR600415",
    integration_time_ms=10.0,
)

#
# Retractable incident-power probe. The repository currently contains
# candidate in/out positions of +1.0/-1.0 mm. Treat them as usable only after
# they have been physically verified on this exact setup. Set either value to
# None to force HardwareManager to refuse probe operation until recommissioned.
#
POWER_METER_STAGE = LinearStageConfig(
    serial="118054611",
    controller_model="C-891.120200",
    stage_model="V-408.132020",
    installed=True,
    axis="1",
    name="Power Meter Translation Stage",
    application_min_mm=-12.0,
    application_max_mm=12.0,
    in_position_mm=12.0,
    out_position_mm=-12.0,
    velocity_mm_s=20.0,
)

POWER_METER = PowerMeterHardwareConfig(
    controller_serial="3144168",
    sensor_serial="3141552",
)

# =============================================================================
# Motion defaults
# =============================================================================

DEFAULT_TIMEOUT = 30.0          # seconds

DEFAULT_POLL_INTERVAL = 0.05    # seconds


# =============================================================================
# Experiment defaults
# =============================================================================

DEFAULT_SETTLE_TIME = 0.25       # seconds

DEFAULT_BACKGROUND_AVERAGES = 5
