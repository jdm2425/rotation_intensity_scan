"""
run_rotation_intensity.py

Runs a simple Rotation + Intensity experiment.

This script is intended to exercise the complete experimental
workflow before more advanced experiment logic is added.
"""

from __future__ import annotations

import logging

from experiments.experiment_config import (
    ExperimentConfig,
    OpticalFilterConfig,
)
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

    collect_experimental_metadata(config)

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


def collect_experimental_metadata(
    config: ExperimentConfig,
) -> None:
    """Collect run notes before any laboratory hardware is connected."""

    print()
    print("Experimental metadata (press Enter to leave a field blank)")
    print("-" * 60)

    config.metadata.run_label = input(
        "Run label: "
    ).strip()
    config.metadata.sample_name = input(
        "Sample name: "
    ).strip()

    filter_names = [
        value.strip()
        for value in input(
            "Installed filters, comma separated (for example FBH400-40): "
        ).split(",")
        if value.strip()
    ]

    harmonics = [
        value.strip()
        for value in input(
            "Intended harmonics, comma separated (for example H5,H7): "
        ).split(",")
        if value.strip()
    ]

    config.metadata.intended_harmonics = harmonics

    for filter_name in filter_names:
        config.metadata.filters.append(
            OpticalFilterConfig(
                name=filter_name,
                intended_harmonics=harmonics.copy(),
            )
        )

    config.metadata.notes = input(
        "Experiment notes: "
    ).strip()

    print("-" * 60)
    print(
        "A shutter-closed pre-scan background will be acquired and saved."
        if config.background.enabled
        else "Pre-scan background acquisition is disabled."
    )


if __name__ == "__main__":

    main()
