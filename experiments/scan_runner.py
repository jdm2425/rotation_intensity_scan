"""
scan_runner.py

Executes complete scans.

The ScanRunner is responsible only for iterating over the scan
positions and calling the experiment.

Progress reporting is handled by ExperimentMonitor.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class ScanRunner:
    """
    Execute a complete scan.
    """

    def __init__(
        self,
        experiment,
        monitor,
    ):

        self.experiment = experiment
        self.monitor = monitor

    # ------------------------------------------------------------------

    def run(
        self,
        *,
        waveplate_angles,
        sample_angles,
    ):
        """
        Execute a scan.

        Yields
        ------
        RotationIntensityResult
        """

        if hasattr(self.experiment, "scan_started"):
            self.experiment.scan_started()

        # Intensity-major ordering is intentional. The intensity waveplate is
        # set once, its incident power is measured once by default, and then
        # every requested sample angle is acquired using that same power
        # trace. This avoids inserting the power meter for every rotation.
        for waveplate_angle in waveplate_angles:

            if hasattr(self.experiment, "prepare_intensity"):
                self.experiment.prepare_intensity(
                    waveplate_angle=waveplate_angle,
                )

            for sample_angle in sample_angles:

            #
            # Notify monitor.
            #

                self.monitor.measurement_started(

                sample_angle=sample_angle,

                waveplate_angle=waveplate_angle,

            )

            #
            # Execute measurement.
            #

                result = self.experiment.measure(

                waveplate_angle=waveplate_angle,

                sample_angle=sample_angle,

            )

                yield result

    # ------------------------------------------------------------------

    def single(
        self,
        *,
        waveplate_angle,
        sample_angle,
    ):
        """
        Execute a single measurement.
        """

        if hasattr(self.experiment, "scan_started"):
            self.experiment.scan_started()

        if hasattr(self.experiment, "prepare_intensity"):
            self.experiment.prepare_intensity(
                waveplate_angle=waveplate_angle,
            )

        self.monitor.measurement_started(

            sample_angle=sample_angle,

            waveplate_angle=waveplate_angle,

        )

        return self.experiment.measure(

            waveplate_angle=waveplate_angle,

            sample_angle=sample_angle,

        )
