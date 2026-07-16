"""
plot_manager.py

Central manager for all live experiment plots.

Initially this manages only the live spectrum display, but it is
designed so additional plots (heatmaps, detector health, intensity
traces, etc.) can be added later without changing the experiment
controller.
"""

from __future__ import annotations

import logging

from plotting.live_spectrum import LiveSpectrum

logger = logging.getLogger(__name__)


class PlotManager:
    """
    Coordinates all live plots.
    """

    def __init__(
        self,
        enabled: bool = True,
    ):

        self.enabled = enabled

        self.live_spectrum = None

        if self.enabled:

            logger.info(
                "Creating live plotting window..."
            )

            self.live_spectrum = LiveSpectrum()

    # ------------------------------------------------------------------

    def measurement_finished(
        self,
        measurement,
    ):
        """
        Update every plot after a completed measurement.
        """

        if not self.enabled:
            return

        self.live_spectrum.update(
            measurement
        )

    # ------------------------------------------------------------------

    def close(self):
        """
        Close all plotting windows.
        """

        if not self.enabled:
            return

        if self.live_spectrum is not None:

            self.live_spectrum.close()

    # ------------------------------------------------------------------

    def __enter__(self):

        return self

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ):

        self.close()

        return False