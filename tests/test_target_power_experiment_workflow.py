"""Hardware-free target-power feedback and persistence workflow test."""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys
import types
from unittest.mock import patch

# Keep this test hardware-free even in environments without vendor libraries.
_hardware_manager_stub = types.ModuleType("hardware.hardware_manager")
_hardware_manager_stub.HardwareManager = object
sys.modules.setdefault("hardware.hardware_manager", _hardware_manager_stub)

from data.data_loader import load_experiment
from experiments.experiment_config import ExperimentConfig
from experiments.experiment_controller import ExperimentController
from experiments.power_targeting import (
    TargetPowerBracketError,
    TargetPowerController,
)
from experiments.waveplate_calibration import fit_malus_calibration
from experiments.rotation_intensity_scan import RotationIntensityExperiment
from tests.test_experiment_workflow import DummyPlotManager
from tests.test_power_experiment_workflow import FakePowerHardwareManager


def test_feedback_controller() -> None:
    measured_angles: list[float] = []

    def increasing_power(angle: float) -> float:
        measured_angles.append(float(angle))
        return 10.0 + float(angle)

    controller = TargetPowerController(
        measure_power_at_angle=increasing_power,
        waveplate_min_deg=0.0,
        waveplate_max_deg=10.0,
        monotonic_direction="increasing",
        tolerance_mw=0.01,
        maximum_iterations=6,
    )
    result = controller.set_target(13.0)
    assert abs(result.achieved_power_mw - 13.0) <= 0.01
    assert abs(result.waveplate_angle_deg - 3.0) <= 0.01
    assert min(measured_angles) >= 0.0
    assert max(measured_angles) <= 10.0

    try:
        controller.set_target(25.0)
    except TargetPowerBracketError:
        pass
    else:
        raise AssertionError("Expected an unbracketed target to be rejected.")

    decreasing = TargetPowerController(
        measure_power_at_angle=lambda angle: 20.0 - float(angle),
        waveplate_min_deg=0.0,
        waveplate_max_deg=10.0,
        monotonic_direction="decreasing",
        tolerance_mw=0.01,
        maximum_iterations=6,
    )
    decreasing_result = decreasing.set_target(17.0)
    assert abs(decreasing_result.waveplate_angle_deg - 3.0) <= 0.01
    assert abs(decreasing_result.achieved_power_mw - 17.0) <= 0.01

    calibration = fit_malus_calibration(
        list(range(0, 11)),
        [10.0 + angle for angle in range(0, 11)],
        waveplate_min_deg=0.0,
        waveplate_max_deg=10.0,
        monotonic_direction="increasing",
    )
    calibrated_angles: list[float] = []
    calibrated = TargetPowerController(
        measure_power_at_angle=lambda angle: (
            calibrated_angles.append(float(angle)) or 10.0 + float(angle)
        ),
        waveplate_min_deg=0.0,
        waveplate_max_deg=10.0,
        monotonic_direction="increasing",
        tolerance_mw=0.05,
        maximum_iterations=6,
        calibration=calibration,
    )
    calibrated_result = calibrated.set_target(15.0)
    assert abs(calibrated_result.achieved_power_mw - 15.0) <= 0.05
    assert len(calibrated_angles) == 3


def test_target_power_experiment() -> None:
    with tempfile.TemporaryDirectory(prefix="target_power_workflow_") as temporary:
        config = ExperimentConfig()
        config.saving.output_directory = Path(temporary)
        config.saving.experiment_name = "TargetPowerWorkflow"
        config.background.enabled = False
        config.shutter.open_delay_s = 0.0
        config.shutter.close_delay_s = 0.0

        config.power_meter.enabled = True
        config.power_meter.cadence = "per_intensity"
        config.power_meter.measurement_duration_s = 1.0
        config.power_meter.pre_measurement_settle_s = 0.0
        config.power_meter.wavelength_option = "fake-2000-nm-band"
        config.power_meter.range_option = "fake-fixed-range"
        config.power_meter.maximum_allowed_power_mw = 20.0

        config.target_power.waveplate_min_deg = 0.0
        config.target_power.waveplate_max_deg = 10.0
        config.target_power.monotonic_direction = "increasing"
        config.target_power.tolerance_mw = 0.01
        config.target_power.maximum_iterations = 6

        with (
            patch(
                "experiments.experiment_controller.HardwareManager",
                FakePowerHardwareManager,
            ),
            patch(
                "experiments.experiment_controller.PlotManager",
                DummyPlotManager,
            ),
        ):
            ExperimentController(
                config=config,
                experiment=RotationIntensityExperiment(),
            ).run(
                target_powers_mw=[12.0, 14.0],
                sample_angles=[0.0, 10.0],
            )

        root = next(Path(temporary).iterdir())
        dataset = load_experiment(root)
        hardware = FakePowerHardwareManager.last_instance

        assert len(dataset) == 4
        assert [measurement.target_power_mw for measurement in dataset] == [
            12.0,
            12.0,
            14.0,
            14.0,
        ]
        assert [measurement.power_mw for measurement in dataset] == [
            12.0,
            12.0,
            14.0,
            14.0,
        ]
        assert [measurement.waveplate_angle_deg for measurement in dataset] == [
            2.0,
            2.0,
            4.0,
            4.0,
        ]
        assert [
            measurement.sample_angle_deg
            for measurement in dataset
        ] == [
            0.0,
            10.0,
            10.0,
            0.0,
        ]
        # Each target uses one persistent probe insertion.  The fresh
        # monotonic bracket requires two endpoint traces plus one converged
        # candidate trace for this linear fake response.
        assert hardware.power_probe.session_count == 2
        assert hardware.power_probe.insert_count == 2
        assert hardware.power_probe.retract_count >= 2
        assert hardware.power_probe.call_count == 6
        assert len(dataset.power_attempts) == 6
        assert len(dataset.power_traces) == 6
        assert hardware.shutter.is_closed

        significant_probe_events = [
            event
            for event in hardware.events
            if event[:2] in {
                ("power", "insert"),
                ("power", "retract"),
            }
        ]
        assert significant_probe_events[:4] == [
            ("power", "insert"),
            ("power", "retract"),
            ("power", "insert"),
            ("power", "retract"),
        ]


        # Every feedback waveplate move is immediately preceded by the fake
        # session's closed-shutter motion guard.
        for index, event in enumerate(hardware.events):
            if event[:2] == ("move", "Waveplate"):
                assert hardware.events[index - 1] == ("power", "prepare_motion")

        # The first sample move in each target block occurs only after that
        # target's single session retraction.
        sample_move_indices = [
            index
            for index, event in enumerate(hardware.events)
            if event[:2] == ("move", "Sample Stage")
        ]
        assert sample_move_indices
        for index in (sample_move_indices[0], sample_move_indices[2]):
            preceding_probe_events = [
                event
                for event in hardware.events[:index]
                if event[:2] in {
                    ("power", "insert"),
                    ("power", "retract"),
                }
            ]
            assert preceding_probe_events[-1] == ("power", "retract")


def main() -> None:
    test_feedback_controller()
    test_target_power_experiment()
    print("TARGET POWER EXPERIMENT WORKFLOW TEST PASSED")


if __name__ == "__main__":
    main()
