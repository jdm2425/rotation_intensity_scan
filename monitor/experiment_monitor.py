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

        power_status = getattr(result, "power_measurement_status", None)
        if power_status is not None:
            power_mw = getattr(result, "power_mw", None)
            power_std_mw = getattr(result, "power_std_mw", None)
            if power_mw is None:
                print(
                    "Incident power  : unavailable "
                    f"(status={power_status})"
                )
            elif power_std_mw is None:
                print(
                    f"Incident power  : {power_mw:.6g} mW "
                    f"(status={power_status})"
                )
            else:
                print(
                    f"Incident power  : {power_mw:.6g} +/- "
                    f"{power_std_mw:.3g} mW (population STD; "
                    f"status={power_status})"
                )
            duration = getattr(
                result,
                "power_measurement_duration_s",
                None,
            )
            valid = getattr(result, "power_valid_sample_count", None)
            total = getattr(result, "power_total_sample_count", None)
            if duration is not None or total is not None:
                duration_text = (
                    f"{duration:.3f} s" if duration is not None else "unknown"
                )
                print(
                    f"Power sampling  : {duration_text}, "
                    f"valid samples={valid}/{total}"
                )
            power_error = getattr(result, "power_measurement_error", None)
            if power_error:
                print(f"Power warning   : {power_error}")

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
        *,
        shutdown_status: dict | None = None,
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

        shutdown_status = shutdown_status or {}
        if shutdown_status.get("shutter_closed"):
            print("Beam shutter closure verified.")
        else:
            print(
                "WARNING: Beam shutter closure was NOT verified; inspect "
                "hardware before enabling the laser."
            )

        probe_out = shutdown_status.get("power_probe_out")
        if probe_out is True:
            print("Power-meter out position verified.")
        elif probe_out is False:
            print(
                "WARNING: Power-meter out position was NOT verified; inspect "
                "the beam path."
            )

        stopped = shutdown_status.get("rotation_stages_stopped", [])
        if stopped:
            print("Stopped rotation stages: " + ", ".join(stopped))

        print("=" * 70)

        print()
