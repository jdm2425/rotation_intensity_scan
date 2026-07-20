"""Hardware-free end-to-end experiment-controller workflow test."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

from data.data_loader import load_experiment
from experiments.experiment_config import (
    ExperimentConfig,
    OpticalFilterConfig,
)
from experiments.experiment_controller import ExperimentController
from experiments.rotation_intensity_scan import RotationIntensityExperiment
from hardware.devices.spectrometer.spectrum import Spectrum


class FakeStage:
    def __init__(self, name: str, events: list[tuple]):
        self.name = name
        self.serial = f"FAKE-{name}"
        self.connected = True
        self.position = 0.0
        self.events = events

    def move_to(self, angle: float) -> None:
        self.position = float(angle)
        self.events.append(("move", self.name, self.position))

    def stop(self) -> None:
        self.events.append(("stop", self.name))

    def info(self) -> dict:
        return {
            "name": self.name,
            "serial": self.serial,
            "connected": True,
            "position_deg": self.position,
        }


class FakeShutter:
    def __init__(self, events: list[tuple]):
        self.name = "Beam Shutter"
        self.serial = "FAKE-SHUTTER"
        self.connected = True
        self.state = 1
        self.events = events

    @property
    def is_open(self) -> bool:
        return self.state == 0

    @property
    def is_closed(self) -> bool:
        return self.state == 1

    def open(self) -> None:
        self.state = 0
        self.events.append(("shutter", "open"))

    def close(self) -> None:
        self.state = 1
        self.events.append(("shutter", "closed"))

    def info(self) -> dict:
        return {
            "name": self.name,
            "serial": self.serial,
            "state": self.state,
            "beam_open": self.is_open,
            "connected": True,
        }


class FakeSpectrometer:
    def __init__(self, shutter: FakeShutter, events: list[tuple]):
        self.name = "Spectrometer"
        self.serial = "FAKE-SPECTROMETER"
        self.integration_time_ms = 1.0
        self.shutter = shutter
        self.events = events

    def set_integration_time(self, value: float) -> None:
        self.integration_time_ms = float(value)

    def acquire(self, *, averages: int = 1) -> Spectrum:
        shutter_state = "open" if self.shutter.is_open else "closed"
        self.events.append(("acquire", shutter_state, averages))
        offset = 100.0 if self.shutter.is_open else 10.0
        return Spectrum(
            wavelengths=np.array([400.0, 401.0, 402.0]),
            intensities=np.array([offset, offset + 1.0, offset]),
            integration_time_ms=self.integration_time_ms,
            serial=self.serial,
            averages=averages,
        )

    def info(self) -> dict:
        return {
            "name": self.name,
            "serial": self.serial,
            "connected": True,
            "integration_time_ms": self.integration_time_ms,
        }


class FakeHardwareManager:
    last_instance = None

    def __init__(self):
        self.events: list[tuple] = []
        self.context_exited = False
        self.exit_exception_type = None
        self.waveplate = FakeStage("Waveplate", self.events)
        self.sample = FakeStage("Sample Stage", self.events)
        self.shutter = FakeShutter(self.events)
        self.spectrometer = FakeSpectrometer(self.shutter, self.events)
        FakeHardwareManager.last_instance = self

    def __enter__(self):
        self.shutter.close()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.context_exited = True
        self.exit_exception_type = exc_type
        self.shutter.close()
        return False

    def summary(self) -> dict:
        return {
            "waveplate": self.waveplate.info(),
            "sample": self.sample.info(),
            "shutter": self.shutter.info(),
            "spectrometer": self.spectrometer.info(),
        }


class FailingBackgroundHardwareManager(FakeHardwareManager):
    """Fake a spectrometer failure during pre-scan setup."""

    def __init__(self):
        super().__init__()

        def fail_background(*, averages: int = 1) -> Spectrum:
            shutter_state = "open" if self.shutter.is_open else "closed"
            self.events.append(("acquire", shutter_state, averages))
            raise RuntimeError("simulated background failure")

        self.spectrometer.acquire = fail_background


class DummyPlotManager:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def measurement_finished(self, measurement) -> None:
        pass

    def close(self) -> None:
        pass


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="experiment_workflow_") as temporary:
        config = ExperimentConfig()
        config.saving.output_directory = Path(temporary)
        config.saving.experiment_name = "WorkflowTest"
        config.spectrometer.integration_time_ms = 12.5
        config.spectrometer.averages = 3
        config.background.averages = 4
        config.background.settle_time_s = 0.0
        config.shutter.open_delay_s = 0.0
        config.shutter.close_delay_s = 0.0
        config.metadata.notes = "FBH400-40 filter, H5"
        config.metadata.intended_harmonics = ["H5"]
        config.metadata.filters = [
            OpticalFilterConfig(
                name="FBH400-40",
                intended_harmonics=["H5"],
            )
        ]

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
            controller = ExperimentController(
                config=config,
                experiment=RotationIntensityExperiment(),
            )
            controller.run(
                waveplate_angles=[0.0, 5.0],
                sample_angles=[0.0],
            )

        experiment_directory = next(Path(temporary).iterdir())
        dataset = load_experiment(experiment_directory)
        hardware = FakeHardwareManager.last_instance

        assert len(dataset) == 2
        assert len(dataset.backgrounds) == 1
        assert dataset.get_background().spectrum.averages == 4
        assert all(measurement.spectrum.averages == 3 for measurement in dataset)
        assert all(
            measurement.spectrum.integration_time_ms == 12.5
            for measurement in dataset
        )
        assert dataset.metadata["experimental_metadata"]["notes"] == (
            "FBH400-40 filter, H5"
        )
        assert dataset.metadata["experimental_metadata"]["filters"][0][
            "name"
        ] == "FBH400-40"

        acquisition_events = [
            event for event in hardware.events if event[0] == "acquire"
        ]
        assert acquisition_events == [
            ("acquire", "closed", 4),
            ("acquire", "open", 3),
            ("acquire", "open", 3),
        ]
        first_move = next(
            index
            for index, event in enumerate(hardware.events)
            if event[0] == "move"
        )
        first_acquisition = next(
            index
            for index, event in enumerate(hardware.events)
            if event[0] == "acquire"
        )
        assert first_acquisition < first_move
        assert hardware.shutter.state == 1
        assert hardware.context_exited is True
        assert hardware.exit_exception_type is None

    # The persistence callback is installed before pre-scan acquisition. A
    # setup failure must clear that callback, stop both rotation stages, and
    # still exit the hardware context with the shutter closed.
    with tempfile.TemporaryDirectory(prefix="failed_setup_") as temporary:
        config = ExperimentConfig()
        config.saving.output_directory = Path(temporary)
        config.saving.experiment_name = "FailedSetup"
        config.background.settle_time_s = 0.0
        config.shutter.open_delay_s = 0.0
        config.shutter.close_delay_s = 0.0
        experiment = RotationIntensityExperiment()

        with (
            patch(
                "experiments.experiment_controller.HardwareManager",
                FailingBackgroundHardwareManager,
            ),
            patch(
                "experiments.experiment_controller.PlotManager",
                DummyPlotManager,
            ),
        ):
            try:
                ExperimentController(
                    config=config,
                    experiment=experiment,
                ).run(
                    waveplate_angles=[0.0],
                    sample_angles=[0.0],
                )
            except RuntimeError as error:
                assert "simulated background failure" in str(error)
            else:
                raise AssertionError("Expected simulated background failure.")

        hardware = FailingBackgroundHardwareManager.last_instance
        assert experiment.power_attempt_callback is None
        assert hardware.context_exited is True
        assert hardware.exit_exception_type is RuntimeError
        assert hardware.shutter.is_closed
        assert ("stop", "Waveplate") in hardware.events
        assert ("stop", "Sample Stage") in hardware.events

    print("EXPERIMENT WORKFLOW TEST PASSED")


if __name__ == "__main__":
    main()
