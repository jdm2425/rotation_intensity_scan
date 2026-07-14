"""
rotation_intensity_scan.py

Core rotation + intensity experiment.

This class coordinates the hardware required to perform a complete
measurement.

No file saving or analysis is performed here; the experiment simply
returns the acquired data.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# =============================================================================
# Result
# =============================================================================

@dataclass(slots=True)
class RotationIntensityResult:
    """
    Result from a single measurement.
    """

    timestamp: float

    waveplate_angle_deg: float

    sample_angle_deg: float

    spectrum: object


# =============================================================================
# Experiment
# =============================================================================

class RotationIntensityExperiment:
    """
    Rotation + intensity experiment.

    Parameters
    ----------
    hardware
        HardwareManager instance.

    acquisition
        Acquisition object.
    """

    def __init__(
        self,
        hardware,
        acquisition,
    ):

        self.hw = hardware
        self.acquisition = acquisition

    # ------------------------------------------------------------------

    def measure(
        self,
        *,
        waveplate_angle: float,
        sample_angle: float,
    ) -> RotationIntensityResult:
        """
        Perform one complete measurement.
        """

        logger.info(
            "Measurement: waveplate %.3f°, sample %.3f°",
            waveplate_angle,
            sample_angle,
        )

        #
        # Move waveplate first.
        #

        self.hw.waveplate.move_to(
            waveplate_angle
        )

        #
        # Then rotate sample.
        #

        self.hw.sample.move_to(
            sample_angle
        )

        #
        # Acquire spectrum.
        #

        spectrum = self.acquisition.acquire()

        return RotationIntensityResult(
            timestamp=time.time(),
            waveplate_angle_deg=waveplate_angle,
            sample_angle_deg=sample_angle,
            spectrum=spectrum,
        )

    # ------------------------------------------------------------------

    def home(self):
        """
        Home both stages.
        """

        logger.info("Homing rotation stages...")

        self.hw.waveplate.home()

        self.hw.sample.home()