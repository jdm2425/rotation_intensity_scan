"""
rotation_scan.py

Simple rotation scan experiment.

This experiment rotates the sample stage through a sequence of angles,
acquiring one spectrum at each position.

No files are written here. Data are simply returned to the caller.
"""

from __future__ import annotations

import logging

from acquisition.acquisition import Acquisition
from .base import BaseExperiment

logger = logging.getLogger(__name__)


class RotationScan(BaseExperiment):
    """
    Rotation scan experiment.
    """

    def __init__(
        self,
        angles,
        *,
        hardware=None,
        acquisition=None,
        test_mode=False,
        save=False,
    ):

        super().__init__(
            hardware=hardware,
            test_mode=test_mode,
            save=save,
        )

        self.angles = list(angles)

        self.acquisition = acquisition or Acquisition(
            test_mode=test_mode,
        )

    # ------------------------------------------------------------------

    def run(self):

        logger.info(
            "Starting rotation scan (%d positions)",
            len(self.angles),
        )

        self.acquisition.connect()

        results = []

        try:

            #
            # Open shutter
            #

            logger.info("Opening shutter")

            self.hardware.shutter.open()

            #
            # Loop over angles
            #

            for i, angle in enumerate(self.angles, start=1):

                logger.info(
                    "[%d/%d] Moving sample stage -> %.3f°",
                    i,
                    len(self.angles),
                    angle,
                )

                self.hardware.sample.move_to(angle)

                spectrum = self.acquisition.acquire()

                results.append(
                    {
                        "angle_deg": angle,
                        "spectrum": spectrum,
                    }
                )

            logger.info("Rotation scan complete.")

        finally:

            logger.info("Closing shutter")

            self.hardware.shutter.close()

            self.acquisition.disconnect()

        return results