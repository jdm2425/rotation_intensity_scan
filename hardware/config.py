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