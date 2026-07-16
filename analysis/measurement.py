"""
measurement.py

Represents one completed experimental measurement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from hardware.devices.spectrometer.spectrum import Spectrum


@dataclass(slots=True)
class Measurement:
    """
    One completed experimental measurement.
    """

    # ------------------------------------------------------------------
    # Time
    # ------------------------------------------------------------------

    timestamp: float

    # ------------------------------------------------------------------
    # Hardware state
    # ------------------------------------------------------------------

    waveplate_angle_deg: float

    sample_angle_deg: float

    # ------------------------------------------------------------------
    # Spectrometer
    # ------------------------------------------------------------------

    spectrum: Spectrum

    # ------------------------------------------------------------------
    # Estimated beam properties
    # ------------------------------------------------------------------

    power_mw: Optional[float] = None

    fluence_mj_cm2: Optional[float] = None

    intensity_w_cm2: Optional[float] = None

    # ------------------------------------------------------------------
    # Derived values
    # ------------------------------------------------------------------

    peak_counts: float = 0.0

    integrated_counts: float = 0.0

    saturated: bool = False

    metadata: dict = field(default_factory=dict)

    # ------------------------------------------------------------------

    def compute_statistics(
        self,
        saturation_level: float = 65535,
    ):
        """
        Compute simple statistics from the acquired spectrum.
        """

        intensities = self.spectrum.intensities

        self.peak_counts = float(
            intensities.max()
        )

        self.integrated_counts = float(
            intensities.sum()
        )

        self.saturated = (
            self.peak_counts >= saturation_level
        )