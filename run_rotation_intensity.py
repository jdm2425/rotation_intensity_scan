"""
run_rotation_intensity.py

Runs a simple Rotation + Intensity experiment.

This script is intended to exercise the complete experimental
workflow before more advanced experiment logic is added.
"""

from __future__ import annotations

import logging

from experiments.experiment_config import ExperimentConfig
from experiments.rotation_intensity_scan import (
    RotationIntensityExperiment,
)
from experiments.experiment_controller import (
    ExperimentController,
)


def main():

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    #
    # Experiment configuration.
    #

    config = ExperimentConfig()

    #
    # Create experiment.
    #

    experiment = RotationIntensityExperiment()

    #
    # Controller.
    #

    controller = ExperimentController(
        config=config,
        experiment=experiment,
    )

    #
    # Small scan for testing.
    #

    sample_angles = [
        0,
        10,
        20,
    ]

    waveplate_angles = [
        0,
        5,
        10,
    ]

    controller.run(
        sample_angles=sample_angles,
        waveplate_angles=waveplate_angles,
    )


if __name__ == "__main__":

    main()