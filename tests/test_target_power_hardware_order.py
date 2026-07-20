"""Hardware-free regression test for the laser-off hardware-order utility."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from tools.test_target_power_scan_hardware import run_order_test
from tests.test_power_experiment_workflow import FakePowerHardwareManager


class FakeHardwareFactory(FakePowerHardwareManager):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.power_meter_stage = type(
            "FakeInsertionStage",
            (), {"position_mm": 1.0},
        )()

    def require_sample_beam_path_clear(self):
        self.events.append(("power", "require_out"))


class FakeAcquisition:
    def __init__(self, *, spectrometer, shutter, before_open, **kwargs):
        self.spectrometer = spectrometer
        self.shutter = shutter
        self.before_open = before_open

    def acquire(self, *, averages=1):
        self.before_open()
        self.shutter.open()
        try:
            return self.spectrometer.acquire(averages=averages)
        finally:
            self.shutter.close()


def make_arguments(output_directory: Path, *, exercise_optical_paths: bool):
    return argparse.Namespace(
        laser_off=True,
        sample_angles=[-5.0, 0.0, 5.0],
        simulated_target_powers_mw=[2.0, 5.0],
        waveplate_angles=[1.0, 4.0],
        exercise_optical_paths=exercise_optical_paths,
        power_duration_s=1.0,
        power_settle_s=0.0,
        integration_time_ms=10.0,
        averages=1,
        wavelength_option="fake-2000-nm-band",
        range_option="fake-fixed-range",
        leave_rotation_stages=False,
        output_directory=output_directory,
        yes=True,
    )


def test_motion_order_without_opening_shutter() -> None:
    with tempfile.TemporaryDirectory(prefix="hardware_order_motion_") as temporary:
        arguments = make_arguments(Path(temporary), exercise_optical_paths=False)
        run_directory = run_order_test(
            arguments,
            hardware_factory=FakeHardwareFactory,
            acquisition_factory=FakeAcquisition,
        )
        hardware = FakeHardwareFactory.last_instance

        assert (run_directory / "hardware_order_log.json").exists()
        assert hardware.power_probe.session_count == 2
        assert hardware.power_probe.insert_count == 2
        assert hardware.power_probe.retract_count >= 2
        assert hardware.power_probe.call_count == 0

        sample_moves = [
            event
            for event in hardware.events
            if event[:2] == ("move", "Sample Stage")
        ]
        assert sample_moves[:6] == [
            ("move", "Sample Stage", -5.0),
            ("move", "Sample Stage", 0.0),
            ("move", "Sample Stage", 5.0),
            ("move", "Sample Stage", -5.0),
            ("move", "Sample Stage", 0.0),
            ("move", "Sample Stage", 5.0),
        ]
        assert all(
            event != ("shutter", "open")
            for event in hardware.events
        )
        assert hardware.shutter.is_closed


def test_exact_order_with_dark_acquisitions() -> None:
    with tempfile.TemporaryDirectory(prefix="hardware_order_optical_") as temporary:
        arguments = make_arguments(Path(temporary), exercise_optical_paths=True)
        run_directory = run_order_test(
            arguments,
            hardware_factory=FakeHardwareFactory,
            acquisition_factory=FakeAcquisition,
        )
        hardware = FakeHardwareFactory.last_instance

        assert hardware.power_probe.session_count == 2
        assert hardware.power_probe.call_count == 2
        assert len(list((run_directory / "spectra").glob("*.npz"))) == 6

        significant = [
            event
            for event in hardware.events
            if event[:2] in {
                ("power", "insert"),
                ("power", "retract"),
            }
            or event[:2] == ("move", "Sample Stage")
        ]
        first_sample_index = next(
            index
            for index, event in enumerate(significant)
            if event[:2] == ("move", "Sample Stage")
        )
        assert significant[first_sample_index - 1] == ("power", "retract")

        fourth_sample_index = [
            index
            for index, event in enumerate(significant)
            if event[:2] == ("move", "Sample Stage")
        ][3]
        assert significant[fourth_sample_index - 1] == ("power", "retract")
        assert hardware.shutter.is_closed


def main() -> None:
    test_motion_order_without_opening_shutter()
    test_exact_order_with_dark_acquisitions()
    print("TARGET POWER HARDWARE ORDER TEST PASSED")


if __name__ == "__main__":
    main()
