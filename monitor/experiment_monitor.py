"""
experiment_monitor.py

Provides live feedback during an experiment.

The monitor is responsible only for displaying information to the user.
It never controls the experiment.

Initially this module provides console output only, but it will later
also manage live plots, heatmaps and quality monitoring.
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta

logger = logging.getLogger(__name__)


class ExperimentMonitor:
    """
    Displays experiment progress.
    """

    def __init__(self):

        self.total_measurements = 0
        self.completed_measurements = 0

        self.start_time = None

    # ------------------------------------------------------------------

    def start(
        self,
        total_measurements: int,
        *,
        test_mode: bool = False,
    ):

        self.total_measurements = total_measurements
        self.completed_measurements = 0

        self.start_time = time.time()

        print()
        print("=" * 70)
        print("Experiment started")
        print("=" * 70)

        print(f"Measurements : {total_measurements}")
        print(f"Test mode    : {'YES' if test_mode else 'NO'}")

        print("=" * 70)
        print()

    # ------------------------------------------------------------------

    def measurement_started(
        self,
        *,
        sample_angle: float,
        waveplate_angle: float,
    ):

        measurement = self.completed_measurements + 1

        elapsed = time.time() - self.start_time

        if measurement == 1:
            eta = "--:--:--"

        else:

            average = elapsed / self.completed_measurements

            remaining = (
                self.total_measurements
                - self.completed_measurements
            )

            eta = str(
                timedelta(
                    seconds=int(
                        average * remaining
                    )
                )
            )

        print()

        print("-" * 70)

        print(
            f"Measurement {measurement}/{self.total_measurements}"
        )

        print(
            f"Sample angle    : {sample_angle:8.3f}°"
        )

        print(
            f"Waveplate angle : {waveplate_angle:8.3f}°"
        )

        print(
            f"Elapsed         : "
            f"{timedelta(seconds=int(elapsed))}"
        )

        print(
            f"Remaining       : {eta}"
        )

    # ------------------------------------------------------------------

    def measurement_finished(
        self,
        result,
    ):

        self.completed_measurements += 1

        spectrum = result.spectrum

        print()

        print(
            f"Maximum counts  : "
            f"{spectrum.intensities.max():.0f}"
        )

        print(
            f"Pixels          : "
            f"{len(spectrum.intensities)}"
        )

        print("Status          : OK")

    # ------------------------------------------------------------------

    def hardware_status(
        self,
        hardware,
    ):

        print()

        print("Hardware")

        print(
            f"  Waveplate : "
            f"{hardware.waveplate.position:8.3f}°"
        )

        print(
            f"  Sample    : "
            f"{hardware.sample.position:8.3f}°"
        )

        print(
            f"  Beam      : "
            f"{'OPEN' if hardware.shutter.is_open else 'CLOSED'}"
        )

    # ------------------------------------------------------------------

    def finish(self):

        elapsed = (
            time.time()
            - self.start_time
        )

        print()

        print("=" * 70)

        print("Experiment complete")

        print(
            f"Measurements : "
            f"{self.completed_measurements}"
        )

        print(
            f"Elapsed      : "
            f"{timedelta(seconds=int(elapsed))}"
        )

        print("=" * 70)

        print()

    # ------------------------------------------------------------------

    def failed(
        self,
        exc: Exception,
    ):

        elapsed = time.time() - self.start_time

        print()

        print("=" * 70)

        print("EXPERIMENT ABORTED")

        print()

        print(
            f"Completed : "
            f"{self.completed_measurements}/"
            f"{self.total_measurements}"
        )

        print(
            f"Elapsed   : "
            f"{timedelta(seconds=int(elapsed))}"
        )

        print()

        print(
            f"{type(exc).__name__}: {exc}"
        )

        print()

        print(
            "Beam safely blocked."
        )

        print(
            "Motors stopped."
        )

        print("=" * 70)

        print()