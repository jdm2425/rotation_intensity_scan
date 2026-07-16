"""
rotation_intensity_scan.py

Core rotation + intensity experiment.

This class defines what a single measurement is.

It does not connect hardware, save data or perform analysis.
"""

from __future__ import annotations

import logging
import time

from analysis.measurement import Measurement

logger = logging.getLogger(__name__)


class RotationIntensityExperiment:
    """
    Rotation + intensity experiment.

    Hardware and acquisition are supplied by the
    ExperimentController immediately before the scan begins.
    """

    def __init__(self):

        self.hardware = None
        self.acquisition = None

    # ------------------------------------------------------------------

    def measure(
        self,
        *,
        waveplate_angle: float,
        sample_angle: float,
    ) -> Measurement:
        """
        Perform one complete measurement.
        """

        if self.hardware is None:
            raise RuntimeError(
                "Hardware has not been attached."
            )

        if self.acquisition is None:
            raise RuntimeError(
                "Acquisition has not been attached."
            )

        logger.info(
            "Measurement: waveplate %.3f°, sample %.3f°",
            waveplate_angle,
            sample_angle,
        )

        #
        # Move hardware.
        #

        self.hardware.waveplate.move_to(
            waveplate_angle
        )

        self.hardware.sample.move_to(
            sample_angle
        )

        #
        # Acquire spectrum.
        #

        spectrum = self.acquisition.acquire()

        #
        # Build measurement.
        #

        measurement = Measurement(
            timestamp=time.time(),
            waveplate_angle_deg=waveplate_angle,
            sample_angle_deg=sample_angle,
            spectrum=spectrum,
        )

        #
        # Compute simple statistics immediately.
        #

        measurement.compute_statistics()

        return measurement

    # ------------------------------------------------------------------

    def home(self):
        """
        Home both stages.
        """

        if self.hardware is None:
            raise RuntimeError(
                "Hardware has not been attached."
            )

        logger.info(
            "Homing rotation stages..."
        )

        self.hardware.waveplate.home()

        self.hardware.sample.home()