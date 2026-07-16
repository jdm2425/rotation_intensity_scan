"""
experiment_controller.py

High-level experiment controller.

Responsibilities
----------------
* Connect hardware
* Create acquisition layer
* Run experiment
* Save data
* Update monitor
* Update live plots
* Ensure safe shutdown
"""

from __future__ import annotations

import logging

from acquisition.acquisition import Acquisition
from data.data_writer import DataWriter
from experiments.scan_runner import ScanRunner
from hardware.config import SHUTTER_TIMING
from hardware.hardware_manager import HardwareManager
from monitor.experiment_monitor import ExperimentMonitor
from plotting.plot_manager import PlotManager

logger = logging.getLogger(__name__)


class ExperimentController:
    """
    Executes an experiment safely.
    """

    def __init__(
        self,
        *,
        config,
        experiment,
    ):

        self.config = config
        self.experiment = experiment

    # ------------------------------------------------------------------

    def run(
        self,
        *,
        waveplate_angles,
        sample_angles,
    ):

        total_measurements = (
            len(waveplate_angles)
            * len(sample_angles)
        )

        with HardwareManager() as hardware:

            acquisition = Acquisition(
                spectrometer=hardware.spectrometer,
                shutter=hardware.shutter,
                shutter_open_delay=SHUTTER_TIMING.open_delay_s,
                shutter_close_delay=SHUTTER_TIMING.close_delay_s,
            )

            self.experiment.hardware = hardware
            self.experiment.acquisition = acquisition

            monitor = ExperimentMonitor()

            plotter = PlotManager(
                enabled=True,
            )

            monitor.start(
                total_measurements=total_measurements,
                test_mode=self.config.test.enabled,
            )

            with DataWriter(
                output_directory=self.config.saving.output_directory,
                experiment_name=self.config.saving.experiment_name,
            ) as writer:

                writer.save_metadata(
                    config=self.config,
                    hardware_info=hardware.summary(),
                )

                runner = ScanRunner(
                    experiment=self.experiment,
                    monitor=monitor,
                )

                try:

                    for measurement in runner.run(
                        waveplate_angles=waveplate_angles,
                        sample_angles=sample_angles,
                    ):

                        #
                        # Console output
                        #

                        monitor.measurement_finished(
                            measurement
                        )

                        monitor.hardware_status(
                            hardware
                        )

                        #
                        # Live plotting
                        #

                        plotter.measurement_finished(
                            measurement
                        )

                        #
                        # Save data
                        #

                        if (
                            not self.config.test.enabled
                            or self.config.test.save_data
                        ):

                            writer.save_result(
                                measurement
                            )

                    monitor.finish()

                except KeyboardInterrupt:

                    logger.warning(
                        "Experiment interrupted."
                    )

                    self._safe_shutdown(
                        hardware
                    )

                    monitor.failed(
                        KeyboardInterrupt(
                            "Experiment interrupted by user."
                        )
                    )

                    raise

                except Exception as exc:

                    logger.exception(
                        "Experiment failed."
                    )

                    self._safe_shutdown(
                        hardware
                    )

                    monitor.failed(exc)

                    raise

                finally:

                    plotter.close()

                    monitor.finish()

    # ------------------------------------------------------------------

    def _safe_shutdown(
        self,
        hardware,
    ):
        """
        Put the laboratory into a safe state.
        """

        logger.warning(
            "Performing emergency shutdown..."
        )

        #
        # Close shutter first.
        #

        try:

            hardware.shutter.close()

            logger.info(
                "Beam shutter closed."
            )

        except Exception:

            logger.exception(
                "Failed to close beam shutter."
            )

        #
        # Stop stages.
        #

        for stage in (
            hardware.waveplate,
            hardware.sample,
        ):

            try:

                stage.stop()

            except Exception:

                logger.exception(
                    "Failed to stop %s",
                    stage.name,
                )

        logger.warning(
            "Emergency shutdown complete."
        )