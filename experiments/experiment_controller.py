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

from dataclasses import asdict
import logging

from acquisition.acquisition import Acquisition
from data.data_writer import DataWriter
from experiments.scan_runner import ScanRunner
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
        sample_angles,
        waveplate_angles=None,
        target_powers_mw=None,
    ):

        angle_mode = waveplate_angles is not None
        target_power_mode = target_powers_mw is not None
        if angle_mode == target_power_mode:
            raise ValueError(
                "Supply exactly one of waveplate_angles or target_powers_mw."
            )

        self.config.spectrometer.validate_for_run()
        self.config.power_meter.validate_for_run()
        if target_power_mode:
            self.config.target_power.validate_for_run(
                target_powers_mw=target_powers_mw,
                power_meter=self.config.power_meter,
            )
            intensity_values = target_powers_mw
        else:
            intensity_values = waveplate_angles

        total_measurements = (
            len(intensity_values)
            * len(sample_angles)
            * self.config.spectrometer.spectra_per_point
        )

        power_enabled = bool(
            self.config.power_meter.enabled
            and self.config.power_meter.cadence != "disabled"
        )
        if power_enabled:
            hardware_context = HardwareManager(
                enable_power_meter=True,
                power_meter_wavelength_option=(
                    self.config.power_meter.wavelength_option
                ),
                power_meter_range_option=(
                    self.config.power_meter.range_option
                ),
            )
        else:
            hardware_context = HardwareManager()

        with hardware_context as hardware:

            hardware.spectrometer.set_integration_time(
                self.config.spectrometer.integration_time_ms
            )

            acquisition = Acquisition(
                spectrometer=hardware.spectrometer,
                shutter=hardware.shutter,
                shutter_open_delay=self.config.shutter.open_delay_s,
                shutter_close_delay=self.config.shutter.close_delay_s,
                before_open=getattr(
                    hardware,
                    "require_sample_beam_path_clear",
                    None,
                ),
            )

            self.experiment.hardware = hardware
            self.experiment.acquisition = acquisition
            self.experiment.averages = self.config.spectrometer.averages
            self.experiment.power_meter_config = self.config.power_meter
            self.experiment.target_power_config = self.config.target_power

            monitor = ExperimentMonitor()

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
                    extra_metadata={
                        "experimental_metadata": asdict(
                            self.config.metadata
                        ),
                    },
                )

                should_save = (
                    not self.config.test.enabled
                    or self.config.test.save_data
                )
                self.experiment.power_attempt_callback = (
                    writer.save_power_attempt if should_save else None
                )

                plotter = None
                try:

                    if self.config.background.enabled and should_save:
                        logger.info(
                            "Acquiring pre-scan background %r with shutter "
                            "closed.",
                            self.config.background.name,
                        )

                        background = acquisition.acquire_dark(
                            averages=self.config.background.averages,
                            settle_time_s=(
                                self.config.background.settle_time_s
                            ),
                        )

                        writer.save_background(
                            background,
                            name=self.config.background.name,
                            metadata={
                                "kind": "shutter_closed_dark",
                                "purpose": "pre_scan_background_correction",
                                "shutter_state": "closed",
                                "notes": self.config.background.notes,
                            },
                        )

                    plotter = PlotManager(
                        enabled=True,
                    )

                    runner = ScanRunner(
                        experiment=self.experiment,
                        monitor=monitor,
                    )

                    for measurement in runner.run(
                        waveplate_angles=waveplate_angles,
                        target_powers_mw=target_powers_mw,
                        sample_angles=sample_angles,
                        spectra_per_point=(
                            self.config.spectrometer.spectra_per_point
                        ),
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

                        if should_save:

                            writer.save_result(
                                measurement
                            )

                except KeyboardInterrupt:

                    logger.warning(
                        "Experiment interrupted."
                    )

                    shutdown_status = self._safe_shutdown(
                        hardware
                    )

                    monitor.failed(
                        KeyboardInterrupt(
                            "Experiment interrupted by user."
                        ),
                        shutdown_status=shutdown_status,
                    )

                    raise

                except Exception as exc:

                    logger.exception(
                        "Experiment failed."
                    )

                    shutdown_status = self._safe_shutdown(
                        hardware
                    )

                    monitor.failed(
                        exc,
                        shutdown_status=shutdown_status,
                    )

                    raise

                finally:

                    # Clear the callback before closing any resource. This
                    # prevents a failed setup or plot close from leaving a
                    # bound method to a DataWriter that is about to close.
                    self.experiment.power_attempt_callback = None
                    if plotter is not None:
                        plotter.close()

                monitor.finish()

    # ------------------------------------------------------------------

    def _safe_shutdown(
        self,
        hardware,
    ) -> dict:
        """
        Put the laboratory into a safe state.
        """

        logger.warning(
            "Performing emergency shutdown..."
        )

        status = {
            "shutter_closed": False,
            "power_probe_out": None,
            "rotation_stages_stopped": [],
        }

        #
        # Close shutter first.
        #

        try:

            hardware.shutter.close()

            logger.info(
                "Beam shutter closed."
            )
            status["shutter_closed"] = bool(hardware.shutter.is_closed)

        except Exception:

            logger.exception(
                "Failed to close beam shutter."
            )

        # With the shutter upstream, insertion-stage motion is allowed only
        # after the closed state has been positively verified by PowerProbe.
        power_probe = getattr(hardware, "power_probe", None)
        if power_probe is not None:
            try:
                power_probe.safe_retract()
                logger.info("Power meter returned to its verified out position.")
                status["power_probe_out"] = True
            except Exception:
                status["power_probe_out"] = False
                logger.exception(
                    "Failed to return the power meter to its safe out position."
                )
                insertion_stage = getattr(
                    hardware,
                    "power_meter_stage",
                    None,
                )
                if insertion_stage is not None:
                    try:
                        insertion_stage.halt()
                    except Exception:
                        logger.exception(
                            "Failed to halt the power-meter insertion stage."
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
                status["rotation_stages_stopped"].append(stage.name)

            except Exception:

                logger.exception(
                    "Failed to stop %s",
                    stage.name,
                )

        logger.warning(
            "Emergency shutdown complete."
        )

        return status
