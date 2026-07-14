"""
acquisition.py

Safe spectrum acquisition.

This class is responsible for ensuring the laser shutter is only open
during the spectrometer exposure.

The experiment code should call Acquisition.acquire() rather than
talking directly to the shutter or spectrometer.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


class Acquisition:
    """
    Safe spectrum acquisition.

    Responsibilities
    ----------------
    - Open shutter
    - Wait for shutter to settle
    - Acquire spectrum
    - Close shutter immediately
    """

    def __init__(
        self,
        spectrometer,
        shutter,
        shutter_delay: float = 0.020,
    ):
        self.spectrometer = spectrometer
        self.shutter = shutter
        self.shutter_delay = shutter_delay

    # ------------------------------------------------------------------

    def acquire(self):
        """
        Acquire one spectrum safely.
        """

        logger.info("Opening shutter...")

        self.shutter.open()

        try:

            #
            # Allow shutter blades to finish moving.
            #

            time.sleep(self.shutter_delay)

            logger.info("Acquiring spectrum...")

            spectrum = self.spectrometer.acquire()

            logger.info("Spectrum acquired.")

            return spectrum

        finally:

            logger.info("Closing shutter...")

            self.shutter.close()

    # ------------------------------------------------------------------

    def dark(self):
        """
        Acquire a dark spectrum.

        The shutter remains closed.
        """

        logger.info("Acquiring dark spectrum...")

        return self.spectrometer.acquire()