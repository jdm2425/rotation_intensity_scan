"""
spectrum.py

Universal spectrum data model.

Every spectrometer driver in the project returns a Spectrum object.

The purpose of this class is to completely separate the rest of the
codebase from any particular spectrometer implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time

import numpy as np


def trapezoidal_integral(y, x) -> float:
    """Integrate with the NumPy 1.x/2.x compatible trapezoid API."""

    integrator = getattr(np, "trapezoid", None)
    if integrator is None:
        integrator = getattr(np, "trapz", None)
    if integrator is None:  # pragma: no cover - unsupported NumPy build
        raise RuntimeError("NumPy provides neither trapezoid nor trapz integration.")
    return float(integrator(y, x))


@dataclass(slots=True)
class Spectrum:
    """
    One acquired spectrum.
    """

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    wavelengths: np.ndarray

    intensities: np.ndarray

    integration_time_ms: float

    serial: str

    # ------------------------------------------------------------------
    # Acquisition metadata
    # ------------------------------------------------------------------

    averages: int = 1

    dark_corrected: bool = False

    nonlinearity_corrected: bool = False

    timestamp: float = field(default_factory=time.time)

    # ------------------------------------------------------------------
    # Dimensions
    # ------------------------------------------------------------------

    @property
    def pixels(self) -> int:

        return len(self.wavelengths)

    @property
    def wavelength_min(self) -> float:

        return float(self.wavelengths[0])

    @property
    def wavelength_max(self) -> float:

        return float(self.wavelengths[-1])

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    @property
    def maximum(self) -> float:

        return float(np.max(self.intensities))

    @property
    def minimum(self) -> float:

        return float(np.min(self.intensities))

    @property
    def mean(self) -> float:

        return float(np.mean(self.intensities))

    @property
    def total_counts(self) -> float:

        return float(np.sum(self.intensities))

    @property
    def saturated(self) -> bool:
        """
        Ocean SR uses a 16-bit ADC.
        """

        return self.maximum >= 65000

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def copy(self) -> "Spectrum":

        return Spectrum(
            wavelengths=self.wavelengths.copy(),
            intensities=self.intensities.copy(),
            integration_time_ms=self.integration_time_ms,
            serial=self.serial,
            averages=self.averages,
            dark_corrected=self.dark_corrected,
            nonlinearity_corrected=self.nonlinearity_corrected,
            timestamp=self.timestamp,
        )

    # ------------------------------------------------------------------

    def normalised(self) -> "Spectrum":
        """
        Return a copy scaled so that the maximum equals one.
        """

        spec = self.copy()

        m = spec.maximum

        if m > 0:

            spec.intensities /= m

        return spec

    # ------------------------------------------------------------------

    def integrate(
        self,
        wavelength_min: float,
        wavelength_max: float,
    ) -> float:
        """
        Integrate the spectrum over a wavelength range.

        Uses trapezoidal integration.
        """

        mask = (
            (self.wavelengths >= wavelength_min)
            &
            (self.wavelengths <= wavelength_max)
        )

        if not np.any(mask):

            return 0.0

        return trapezoidal_integral(
            self.intensities[mask],
            self.wavelengths[mask],
        )

    # ------------------------------------------------------------------

    def peak_wavelength(self) -> float:
        """
        Wavelength corresponding to the highest counts.
        """

        index = int(np.argmax(self.intensities))

        return float(self.wavelengths[index])

    # ------------------------------------------------------------------

    def __len__(self):

        return self.pixels

    # ------------------------------------------------------------------

    def __repr__(self):

        return (
            "<Spectrum "
            f"{self.serial} "
            f"{self.pixels} px "
            f"{self.wavelength_min:.1f}-{self.wavelength_max:.1f} nm "
            f"max={self.maximum:.0f}>"
        )
