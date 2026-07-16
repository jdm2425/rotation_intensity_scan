"""
scan_runner.py

Executes complete scans.

The ScanRunner is responsible only for iterating over the scan
positions and calling the experiment.

Progress reporting is handled by ExperimentMonitor.
"""

from __future__ import annotations

import logging
from itertools import product

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

        for sample_angle, waveplate_angle in product(
            sample_angles,
            waveplate_angles,
        ):

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

        self.monitor.measurement_started(

            sample_angle=sample_angle,

            waveplate_angle=waveplate_angle,

        )

        return self.experiment.measure(

            waveplate_angle=waveplate_angle,

            sample_angle=sample_angle,

        )