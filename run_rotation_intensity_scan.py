"""
run_rotation_intensity_scan.py

Top-level script for running a Rotation + Intensity experiment.

This script wires together:

    Hardware
        ↓
    Spectrometer
        ↓
    Acquisition
        ↓
    Experiment
        ↓
    ScanRunner
        ↓
    DataWriter

The experiment itself contains no file-saving logic.
"""

from __future__ import annotations

import logging

from hardware.hardware_manager import HardwareManager

from hardware.devices.spectrometer.ocean_sr import OceanSR

from acquisition.acquisition import Acquisition

from experiments.rotation_intensity_scan import (
    RotationIntensityExperiment,
)

from experiments.scan_runner import ScanRunner

from experiments.experiment_config import (
    ExperimentConfig,
)

from data.data_writer import DataWriter


logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)


def main():

    #
    # ------------------------------------------------------------
    # Experiment configuration
    # ------------------------------------------------------------
    #

    config = ExperimentConfig()

    #
    # Example scan.
    # These will eventually come from the beam/intensity model.
    #

    waveplate_angles = [
        0,
        5,
        10,
    ]

    sample_angles = [
        0,
        30,
        60,
        90,
    ]

    #
    # ------------------------------------------------------------
    # Hardware
    # ------------------------------------------------------------
    #

    with HardwareManager() as hw:

        #
        # Spectrometer
        #

        spectrometer = OceanSR(
            integration_time_ms=config.spectrometer.integration_time_ms,
            serial="SR600415",
        )

        spectrometer.connect()

        try:

            #
            # Acquisition layer
            #

            acquisition = Acquisition(
                spectrometer=spectrometer,
                shutter=hw.shutter,
                shutter_delay=config.shutter.open_delay_s,
            )

            #
            # Experiment
            #

            experiment = RotationIntensityExperiment(
                hardware=hw,
                acquisition=acquisition,
            )

            #
            # Scan runner
            #

            runner = ScanRunner(
                experiment,
            )

            #
            # Data writer
            #

            with DataWriter(
                output_directory=config.saving.output_directory,
                experiment_name=config.saving.experiment_name,
            ) as writer:

                writer.save_metadata(
                    config=config,
                    hardware_info=hw.summary(),
                )

                for result in runner.run(
                    waveplate_angles=waveplate_angles,
                    sample_angles=sample_angles,
                ):

                    print(
                        f"Sample {result.sample_angle_deg:6.2f}°   "
                        f"Waveplate {result.waveplate_angle_deg:6.2f}°"
                    )

                    if (
                        not config.test.enabled
                        or config.test.save_data
                    ):

                        writer.save_result(result)

        finally:

            spectrometer.disconnect()


if __name__ == "__main__":

    main()