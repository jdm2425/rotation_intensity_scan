"""
live_spectrum.py

Simple live spectrum display.

The plot updates after every acquired spectrum without blocking the
experiment.
"""

from __future__ import annotations

import matplotlib.pyplot as plt


class LiveSpectrum:
    """
    Live spectrum display.
    """

    def __init__(self):

        plt.ion()

        self.figure, self.axes = plt.subplots(
            figsize=(9, 5)
        )

        (self.line,) = self.axes.plot(
            [],
            [],
            lw=1.5,
        )

        self.axes.set_xlabel("Wavelength (nm)")
        self.axes.set_ylabel("Counts")

        self.axes.set_title("Live Spectrum")

        self.axes.grid(True)

        self.figure.tight_layout()

        self._initialised = False

    # ------------------------------------------------------------------

    def update(self, measurement):
        """
        Update the live spectrum.
        """

        spectrum = measurement.spectrum

        x = spectrum.wavelengths
        y = spectrum.intensities

        self.line.set_data(x, y)

        if not self._initialised:

            self.axes.set_xlim(
                x.min(),
                x.max(),
            )

            self._initialised = True

        ymax = max(
            1000,
            y.max() * 1.05,
        )

        self.axes.set_ylim(
            0,
            ymax,
        )

        self.axes.set_title(
            f"Sample {measurement.sample_angle_deg:.1f}°    "
            f"Waveplate {measurement.waveplate_angle_deg:.1f}°    "
            f"Peak {measurement.peak_counts:.0f}"
        )

        self.figure.canvas.draw_idle()

        self.figure.canvas.flush_events()

        #
        # Tiny pause lets the GUI update without slowing
        # the experiment noticeably.
        #

        plt.pause(0.001)

    # ------------------------------------------------------------------

    def close(self):

        plt.close(self.figure)