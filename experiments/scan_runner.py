"""
scan_runner.py

Executes complete scans.

The ScanRunner is responsible only for iterating over the scan positions and
calling the experiment.  It supports either explicit waveplate angles or
closed-loop requested powers; exactly one intensity coordinate is supplied.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class ScanRunner:
    """Execute a complete scan."""

    def __init__(self, experiment, monitor):
        self.experiment = experiment
        self.monitor = monitor

    def run(
        self,
        *,
        sample_angles,
        waveplate_angles=None,
        target_powers_mw=None,
        spectra_per_point=1,
    ):
        """Execute an angle-controlled or target-power-controlled scan."""

        spectra_per_point = int(spectra_per_point)
        if spectra_per_point < 1:
            raise ValueError("spectra_per_point must be at least one.")

        angle_mode = waveplate_angles is not None
        power_mode = target_powers_mw is not None
        if angle_mode == power_mode:
            raise ValueError(
                "Supply exactly one of waveplate_angles or target_powers_mw."
            )

        if hasattr(self.experiment, "scan_started"):
            self.experiment.scan_started()

        if power_mode:
            sample_angles = tuple(
                float(angle)
                for angle in sample_angles
            )

            for power_index, target_power_mw in enumerate(
                target_powers_mw
            ):
                waveplate_angle = (
                    self.experiment.prepare_target_power(
                        target_power_mw=target_power_mw,
                    )
                )

                if power_index % 2 == 0:
                    block_sample_angles = sample_angles
                    scan_direction = "forward"
                else:
                    block_sample_angles = sample_angles[::-1]
                    scan_direction = "reverse"

                logger.info(
                    "Sample-angle scan for target %.6g mW: %s.",
                    target_power_mw,
                    scan_direction,
                )

                for sample_angle in block_sample_angles:
                    for replicate_index in range(1, spectra_per_point + 1):
                        self.monitor.measurement_started(
                            sample_angle=sample_angle,
                            waveplate_angle=waveplate_angle,
                            target_power_mw=target_power_mw,
                        )

                        arguments = {
                            "waveplate_angle": waveplate_angle,
                            "sample_angle": sample_angle,
                            "target_power_mw": target_power_mw,
                        }
                        if spectra_per_point > 1:
                            arguments.update(
                                replicate_index=replicate_index,
                                replicate_count=spectra_per_point,
                            )
                        yield self.experiment.measure(**arguments)

            return

        # Angle-major ordering is intentional.  The waveplate is set once,
        # its incident power is measured once by default, and every requested
        # sample angle uses that same power trace.
        for waveplate_angle in waveplate_angles:
            if hasattr(self.experiment, "prepare_intensity"):
                self.experiment.prepare_intensity(
                    waveplate_angle=waveplate_angle,
                )
            for sample_angle in sample_angles:
                for replicate_index in range(1, spectra_per_point + 1):
                    self.monitor.measurement_started(
                        sample_angle=sample_angle,
                        waveplate_angle=waveplate_angle,
                    )
                    arguments = {
                        "waveplate_angle": waveplate_angle,
                        "sample_angle": sample_angle,
                    }
                    if spectra_per_point > 1:
                        arguments.update(
                            replicate_index=replicate_index,
                            replicate_count=spectra_per_point,
                        )
                    yield self.experiment.measure(**arguments)

    def single(
        self,
        *,
        sample_angle,
        waveplate_angle=None,
        target_power_mw=None,
    ):
        """Execute one angle-controlled or target-power-controlled point."""

        angle_mode = waveplate_angle is not None
        power_mode = target_power_mw is not None
        if angle_mode == power_mode:
            raise ValueError(
                "Supply exactly one of waveplate_angle or target_power_mw."
            )

        if hasattr(self.experiment, "scan_started"):
            self.experiment.scan_started()

        if power_mode:
            waveplate_angle = self.experiment.prepare_target_power(
                target_power_mw=target_power_mw,
            )
        elif hasattr(self.experiment, "prepare_intensity"):
            self.experiment.prepare_intensity(
                waveplate_angle=waveplate_angle,
            )

        self.monitor.measurement_started(
            sample_angle=sample_angle,
            waveplate_angle=waveplate_angle,
            target_power_mw=target_power_mw,
        )
        return self.experiment.measure(
            waveplate_angle=waveplate_angle,
            sample_angle=sample_angle,
            target_power_mw=target_power_mw,
        )
