"""
acquisition.py

High-level acquisition interface.

This class coordinates the spectrometer and beam shutter so that
experiments never need to manipulate either device directly.

Safety philosophy
-----------------
The beam should remain blocked whenever possible.

The shutter is opened only immediately before acquisition and closed
immediately afterwards.
"""

from __future__ import annotations

import logging
import time

from hardware.devices.spectrometer.spectrum import Spectrum

logger = logging.getLogger(__name__)


class Acquisition:
    """
    Coordinates spectrum acquisition.

    Parameters
    ----------
    spectrometer
        Spectrometer driver.

    shutter
        Beam shutter.

    shutter_open_delay
        Delay after opening the shutter before beginning acquisition.

    shutter_close_delay
        Optional hold time after acquisition and before closing the shutter.

    before_open
        Optional safety guard called immediately before every illuminated
        shutter opening.
    """

    def __init__(
        self,
        *,
        spectrometer,
        shutter,
        shutter_open_delay: float = 0.10,
        shutter_close_delay: float = 0.00,
        before_open=None,
    ):

        self.spectrometer = spectrometer

        self.shutter = shutter

        #
        # Delay after opening the shutter before acquisition.
        #
        self.shutter_open_delay = float(
            shutter_open_delay
        )

        #
        # Optional delay before closing the shutter after
        # acquisition has completed.
        #
        self.shutter_close_delay = float(
            shutter_close_delay
        )
        self.before_open = before_open
    # ------------------------------------------------------------------

    def acquire(
        self,
        *,
        averages: int = 1,
    ) -> Spectrum:
        """
        Acquire a single illuminated spectrum.

        The shutter is always closed afterwards,
        even if an exception occurs.
        """

        try:

            logger.debug("Opening shutter.")

            if self.before_open is not None:
                self.before_open()

            self.shutter.open()

            #
            # Allow the shutter to finish moving.
            #

            if self.shutter_open_delay > 0:

                time.sleep(
                    self.shutter_open_delay
                )

            spectrum = self.spectrometer.acquire(
                averages=averages,
            )

            #
            # Optional hold time before closing.
            #

            if self.shutter_close_delay > 0:

                time.sleep(
                    self.shutter_close_delay
                )

            return spectrum

        finally:

            logger.debug("Closing shutter.")

            self.shutter.close()
    # ------------------------------------------------------------------

    def acquire_dark(
        self,
        *,
        averages: int = 1,
        settle_time_s: float = 0.0,
    ) -> Spectrum:
        """
        Acquire a dark spectrum.

        The shutter is forced closed before acquisition.
        """

        self.shutter.close()

        if settle_time_s > 0:
            time.sleep(float(settle_time_s))

        return self.spectrometer.acquire(
            averages=averages,
        )

    # ------------------------------------------------------------------

    def acquire_pair(
        self,
        *,
        averages: int = 1,
    ):
        """
        Acquire both a dark and illuminated spectrum.

        Returns
        -------
        (dark, light)
        """

        dark = self.acquire_dark(
            averages=averages,
        )

        light = self.acquire(
            averages=averages,
        )

        return dark, light

    # ------------------------------------------------------------------

    def acquire_background_corrected(
        self,
        *,
        averages: int = 1,
    ) -> Spectrum:
        """
        Acquire a dark spectrum followed by an illuminated spectrum.

        Returns a new background-subtracted Spectrum.
        """

        dark, light = self.acquire_pair(
            averages=averages,
        )

        corrected = light.copy()

        corrected.intensities -= dark.intensities

        return corrected

    # ------------------------------------------------------------------

    def __repr__(self):

        return (
            "<Acquisition "
            f"{self.spectrometer.serial}>"
        )
