"""
measurement.py

Canonical measurement object used throughout the project.

Every completed acquisition is represented by one Measurement
instance. This object is passed unchanged between acquisition,
monitoring, saving, loading and analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from hardware.devices.spectrometer.spectrum import Spectrum


@dataclass(slots=True)
class Measurement:
    """
    Represents one completed measurement.

    This is the canonical data structure used throughout the
    project.
    """

    # ==========================================================
    # Timing
    # ==========================================================

    timestamp: float

    # ==========================================================
    # Stage positions
    # ==========================================================

    waveplate_angle_deg: float

    sample_angle_deg: float

    # ==========================================================
    # Beam model (optional)
    # ==========================================================

    power_mw: float | None = None

    fluence_mj_cm2: float | None = None

    intensity_w_cm2: float | None = None

    # ==========================================================
    # Spectrometer
    # ==========================================================

    spectrum: Spectrum | None = None

    # ==========================================================
    # Derived quantities
    # ==========================================================

    peak_counts: float | None = None

    integrated_counts: float | None = None

    saturated: bool = False

    # ==========================================================
    # User metadata
    # ==========================================================

    metadata: dict[str, Any] = field(default_factory=dict)

    # ----------------------------------------------------------

    @property
    def wavelengths_nm(self) -> np.ndarray | None:
        """
        Convenience access to wavelengths.
        """

        if self.spectrum is None:
            return None

        return self.spectrum.wavelengths

    # ----------------------------------------------------------

    @property
    def intensities(self) -> np.ndarray | None:
        """
        Convenience access to intensity values.
        """

        if self.spectrum is None:
            return None

        return self.spectrum.intensities

    # ----------------------------------------------------------

    @property
    def integration_time_ms(self) -> float | None:
        """
        Spectrometer integration time.
        """

        if self.spectrum is None:
            return None

        return self.spectrum.integration_time_ms

    # ----------------------------------------------------------

    @property
    def averages(self) -> int | None:

        if self.spectrum is None:
            return None

        return self.spectrum.averages

    # ----------------------------------------------------------

    def compute_statistics(
        self,
        saturation_level: float = 65535,
    ) -> None:
        """
        Compute commonly used statistics.
        """

        if self.spectrum is None:
            return

        data = self.spectrum.intensities

        self.peak_counts = float(
            np.max(data)
        )

        self.integrated_counts = float(
            np.sum(data)
        )

        self.saturated = (
            self.peak_counts >= saturation_level
        )

    # ----------------------------------------------------------

    @property
    def pixel_count(self) -> int:

        if self.spectrum is None:
            return 0

        return len(
            self.spectrum.intensities
        )

    # ----------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """
        Lightweight summary.
        """

        return {

            "waveplate_angle_deg":
                self.waveplate_angle_deg,

            "sample_angle_deg":
                self.sample_angle_deg,

            "power_mw":
                self.power_mw,

            "peak_counts":
                self.peak_counts,

            "integrated_counts":
                self.integrated_counts,

            "integration_time_ms":
                self.integration_time_ms,

            "pixels":
                self.pixel_count,

            "saturated":
                self.saturated,

        }

    # ----------------------------------------------------------

    def __repr__(self):

        return (
            "Measurement("
            f"sample={self.sample_angle_deg:.2f}°, "
            f"waveplate={self.waveplate_angle_deg:.2f}°, "
            f"peak={self.peak_counts}, "
            f"saturated={self.saturated})"
        )