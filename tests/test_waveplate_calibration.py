from __future__ import annotations

import math
import tempfile
from pathlib import Path
from unittest.mock import patch

from experiments.waveplate_calibration import (
    MalusLawCalibration,
    fit_malus_calibration,
    snapshot_calibration_for_experiment,
)


def test_fit_inverse_offset_and_round_trip() -> None:
    angles = list(range(70, 111, 2))
    powers = [
        11.0 - 9.0 * math.cos(math.radians(4.0 * (angle - 75.0)))
        for angle in angles
    ]
    calibration = fit_malus_calibration(
        angles,
        powers,
        waveplate_min_deg=75.0,
        waveplate_max_deg=110.0,
        monotonic_direction="increasing",
        source="synthetic.csv",
    )
    assert calibration.rms_residual_mw < 1e-10
    target_angle = 92.0
    target_power = calibration.predict_power_mw(target_angle)
    assert abs(calibration.angle_for_power_mw(target_power) - target_angle) < 0.01

    shifted = calibration.with_reference(
        angle_deg=110.0,
        measured_power_mw=calibration.predict_power_mw(110.0) + 2.5,
    )
    assert abs(shifted.power_offset_mw - 2.5) < 1e-10

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "calibration.json"
        shifted.save(path)
        assert MalusLawCalibration.load(path) == shifted
        experiment = Path(directory) / "experiment"
        experiment.mkdir()
        snapshot = snapshot_calibration_for_experiment(path, experiment)
        assert snapshot == experiment / "calibration" / "malus_calibration.json"
        assert MalusLawCalibration.load(snapshot) == shifted
        assert not snapshot.with_suffix(".json.tmp").exists()


def test_controller_saves_portable_calibration_snapshot() -> None:
    from data.data_loader import load_experiment
    from tests.test_experiment_workflow import DummyPlotManager, FakeHardwareManager
    from experiments.experiment_config import ExperimentConfig
    from experiments.experiment_controller import ExperimentController
    from experiments.rotation_intensity_scan import RotationIntensityExperiment

    with tempfile.TemporaryDirectory(prefix="controller_calibration_") as temporary:
        root = Path(temporary)
        calibration_path = root / "source_calibration.json"
        fit_malus_calibration(
            [70.0, 80.0, 90.0, 100.0],
            [2.0, 4.0, 7.0, 10.0],
            waveplate_min_deg=70.0,
            waveplate_max_deg=100.0,
            monotonic_direction="increasing",
            source="source_map.csv",
        ).save(calibration_path)
        config = ExperimentConfig()
        config.saving.output_directory = root / "runs"
        config.saving.experiment_name = "PortableCalibration"
        config.background.enabled = False
        config.shutter.open_delay_s = 0.0
        config.shutter.close_delay_s = 0.0
        config.target_power.calibration_path = calibration_path
        with (
            patch(
                "experiments.experiment_controller.HardwareManager",
                FakeHardwareManager,
            ),
            patch(
                "experiments.experiment_controller.PlotManager",
                DummyPlotManager,
            ),
        ):
            ExperimentController(
                config=config,
                experiment=RotationIntensityExperiment(),
            ).run(waveplate_angles=[0.0], sample_angles=[0.0])

        experiment = next((root / "runs").iterdir())
        dataset = load_experiment(experiment)
        assert dataset.config["target_power"]["calibration_path"] is None
        assert dataset.config["target_power"]["calibration_file"] == (
            "calibration/malus_calibration.json"
        )
        assert (experiment / "calibration" / "malus_calibration.json").is_file()


if __name__ == "__main__":
    test_fit_inverse_offset_and_round_trip()
    test_controller_saves_portable_calibration_snapshot()
    print("WAVEPLATE CALIBRATION TEST PASSED")
