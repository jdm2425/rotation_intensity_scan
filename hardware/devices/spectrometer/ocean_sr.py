"""
ocean_sr.py

Driver for the Ocean Insight SR spectrometer using python-seabreeze.

Responsibilities
----------------
- Connect/disconnect the spectrometer
- Configure integration time
- Acquire spectra

No experiment logic belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time

import numpy as np

import seabreeze
seabreeze.use("pyseabreeze")
from seabreeze.spectrometers import Spectrometer, list_devices

logger = logging.getLogger(__name__)


# =============================================================================
# Result
# =============================================================================

@dataclass(slots=True)
class Spectrum:
    """
    One acquired spectrum.
    """

    timestamp: float

    wavelengths: np.ndarray

    intensities: np.ndarray

    integration_time_ms: float


# =============================================================================
# Driver
# =============================================================================

class OceanSR:
    """
    Ocean Insight SR spectrometer driver.
    """

    def __init__(
        self,
        serial: str,
        integration_time_ms: float = 100,
    ):

        self.serial = serial

        self.integration_time_ms = integration_time_ms

        self._spec = None

    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:

        return self._spec is not None

    # ------------------------------------------------------------------

    def connect(self):

        if self.connected:
            return

        logger.info("Searching for Ocean spectrometers...")

        devices = list_devices()

        if not devices:
            raise RuntimeError("No Ocean spectrometers found.")

        logger.info(
            "Found %d spectrometer(s).",
            len(devices),
        )

        #
        # Find requested serial.
        #

        for device in devices:

            spec = Spectrometer(device)

            if spec.serial_number == self.serial:

                self._spec = spec

                break

            spec.close()

        if self._spec is None:

            available = []

            for d in devices:

                s = Spectrometer(d)

                available.append(s.serial_number)

                s.close()

            raise RuntimeError(
                f"Spectrometer '{self.serial}' not found.\n"
                f"Available: {available}"
            )

        logger.info(
            "Connected to Ocean SR (%s)",
            self.serial,
        )

        self.set_integration_time(
            self.integration_time_ms
        )

    # ------------------------------------------------------------------

    def disconnect(self):

        if not self.connected:
            return

        logger.info(
            "Disconnecting spectrometer..."
        )

        self._spec.close()

        self._spec = None

    # ------------------------------------------------------------------

    def set_integration_time(
        self,
        milliseconds: float,
    ):

        self.integration_time_ms = float(milliseconds)

        if self.connected:

            self._spec.integration_time_micros(
                int(milliseconds * 1000)
            )

    # ------------------------------------------------------------------

    def acquire(self) -> Spectrum:

        if not self.connected:

            raise RuntimeError(
                "Spectrometer is not connected."
            )

        wavelengths = self._spec.wavelengths()

        intensities = self._spec.intensities()

        return Spectrum(
            timestamp=time.time(),
            wavelengths=np.asarray(wavelengths),
            intensities=np.asarray(intensities),
            integration_time_ms=self.integration_time_ms,
        )

    # ------------------------------------------------------------------

    def __repr__(self):

        return (
            f"<OceanSR "
            f"{self.serial} "
            f"connected={self.connected}>"
        )