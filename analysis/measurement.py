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

try:
    from hardware.devices.power_meter.models import PowerTrace
except ImportError:  # Models are optional for legacy/no-meter installations.
    PowerTrace = Any


@dataclass(slots=True)
class Measurement:
    """
    Represents one completed measurement.

    This is the canonical data structure used throughout the
    project. ``power_mw`` is the canonical achieved mean power associated
    with the spectrum, not the requested setpoint. A requested setpoint and
    power-meter sampling statistics are stored separately when available.
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

    # Canonical achieved mean power for this measurement. This field keeps its
    # existing name for saved-data and analysis compatibility.
    power_mw: float | None = None

    # Optional power-meter context. These are keyword-only so adding them does
    # not change the positional constructor layout of the established model.
    target_power_mw: float | None = field(default=None, kw_only=True)

    # RMS statistic reported over the associated power-meter sampling interval.
    power_rms_mw: float | None = field(default=None, kw_only=True)

    power_measurement_duration_s: float | None = field(
        default=None,
        kw_only=True,
    )

    # Population standard deviation of valid power samples. ``power_rms_mw``
    # remains the absolute RMS sqrt(mean(power**2)); these are intentionally
    # separate statistics.
    power_std_mw: float | None = field(default=None, kw_only=True)

    # Stable reference shared by all spectra associated with one raw power
    # trace. No value is manufactured when acquisition fails.
    power_measurement_id: str | None = field(default=None, kw_only=True)

    power_trace_id: str | None = field(default=None, kw_only=True)

    power_measurement_status: str | None = field(default=None, kw_only=True)

    power_measurement_error: str | None = field(default=None, kw_only=True)

    power_valid_sample_count: int | None = field(default=None, kw_only=True)

    power_total_sample_count: int | None = field(default=None, kw_only=True)

    # A transient/shared in-memory reference. DataWriter stores each unique
    # trace once and DataLoader restores shared references after loading.
    power_trace: PowerTrace | None = field(
        default=None,
        kw_only=True,
        repr=False,
        compare=False,
    )

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
    def achieved_power_mw(self) -> float | None:
        """Explicit read-only name for the achieved mean ``power_mw``."""

        return self.power_mw

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

            "achieved_power_mw":
                self.power_mw,

            "target_power_mw":
                self.target_power_mw,

            "power_rms_mw":
                self.power_rms_mw,

            "power_measurement_duration_s":
                self.power_measurement_duration_s,

            "power_std_mw":
                self.power_std_mw,

            "power_measurement_id":
                self.power_measurement_id,

            "power_trace_id":
                self.power_trace_id,

            "power_measurement_status":
                self.power_measurement_status,

            "power_measurement_error":
                self.power_measurement_error,

            "power_valid_sample_count":
                self.power_valid_sample_count,

            "power_total_sample_count":
                self.power_total_sample_count,

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
