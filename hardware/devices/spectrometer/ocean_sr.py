"""
ocean_sr.py

Driver for the Ocean Insight SR spectrometer.

Uses the pyseabreeze backend, which has proven to be the reliable
backend for the SR600415 spectrometer.

Every acquisition returns a universal Spectrum object.
"""

from __future__ import annotations

import logging

import numpy as np
import seabreeze

#
# IMPORTANT:
# The SR600415 only enumerates correctly using the pure-python backend.
#
seabreeze.use("pyseabreeze")

from seabreeze.spectrometers import (
    Spectrometer,
    list_devices,
)

from hardware.devices.spectrometer.spectrum import Spectrum

logger = logging.getLogger(__name__)


class OceanSR:
    """
    Ocean Insight SR spectrometer.

    Parameters
    ----------
    serial
        Spectrometer serial number.

    integration_time_ms
        Exposure time.

    """

    def __init__(
        self,
        serial: str = "SR600415",
        integration_time_ms: float = 10.0,
    ):

        self.serial = serial

        self.integration_time_ms = float(
            integration_time_ms
        )

        self._device = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:

        return self._device is not None

    def connect(self):

        if self.connected:
            return

        logger.info(
            "Searching for Ocean spectrometers..."
        )

        devices = list_devices()

        if not devices:

            raise RuntimeError(
                "No Ocean spectrometers found."
            )

        logger.info(
            "Found %d spectrometer(s).",
            len(devices),
        )

        for device in devices:

            spec = Spectrometer(device)

            logger.info(
                "Detected %s",
                spec.serial_number,
            )

            if spec.serial_number == self.serial:

                self._device = spec

                break

            spec.close()

        if self._device is None:

            raise RuntimeError(
                f"Spectrometer '{self.serial}' not found."
            )

        self.set_integration_time(
            self.integration_time_ms
        )

        logger.info(
            "Connected to Ocean SR (%s)",
            self.serial,
        )

    def info(self):
        """
        Return spectrometer information.
        """

        return {
            "name": "Spectrometer",
            "serial": self.serial,
            "connected": self.connected,
            "integration_time_ms": self.integration_time_ms,
        }
    def disconnect(self):

        if not self.connected:
            return

        logger.info(
            "Disconnecting spectrometer..."
        )

        self._device.close()

        self._device = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_integration_time(
        self,
        integration_time_ms: float,
    ):
        """
        Set exposure time.
        """

        if not self.connected:

            raise RuntimeError(
                "Spectrometer not connected."
            )

        self.integration_time_ms = float(
            integration_time_ms
        )

        self._device.integration_time_micros(
            int(
                self.integration_time_ms
                * 1000
            )
        )

    # ------------------------------------------------------------------
    # Acquisition
    # ------------------------------------------------------------------

    def acquire(
        self,
        *,
        averages: int = 1,
    ) -> Spectrum:
        """
        Acquire one spectrum.

        Parameters
        ----------
        averages
            Number of spectra to average.
        """

        if not self.connected:

            raise RuntimeError(
                "Spectrometer not connected."
            )

        averages = max(
            1,
            int(averages),
        )

        wavelengths = np.asarray(
            self._device.wavelengths()
        )

        summed = None

        for _ in range(averages):

            counts = np.asarray(
                self._device.intensities(
                    correct_dark_counts=False,
                    correct_nonlinearity=False,
                ),
                dtype=float,
            )

            if summed is None:

                summed = counts

            else:

                summed += counts

        intensities = summed / averages

        return Spectrum(
            wavelengths=wavelengths,
            intensities=intensities,
            integration_time_ms=self.integration_time_ms,
            serial=self.serial,
            averages=averages,
            dark_corrected=False,
            nonlinearity_corrected=False,
        )

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def pixels(self) -> int:

        if not self.connected:

            raise RuntimeError(
                "Spectrometer not connected."
            )

        return len(
            self._device.wavelengths()
        )

    @property
    def wavelength_range(self):

        if not self.connected:

            raise RuntimeError(
                "Spectrometer not connected."
            )

        wl = self._device.wavelengths()

        return (
            float(wl[0]),
            float(wl[-1]),
        )

    # ------------------------------------------------------------------

    def __enter__(self):

        self.connect()

        return self

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ):

        self.disconnect()

        return False

    # ------------------------------------------------------------------

    def __repr__(self):

        if self.connected:

            lo, hi = self.wavelength_range

            return (
                f"<OceanSR "
                f"{self.serial} "
                f"{self.pixels} px "
                f"{lo:.1f}-{hi:.1f} nm>"
            )

        return (
            f"<OceanSR "
            f"{self.serial} "
            f"(disconnected)>"
        )