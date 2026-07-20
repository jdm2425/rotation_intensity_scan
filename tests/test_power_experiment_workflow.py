"""Hardware-free end-to-end power cadence and persistence workflow test."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from data.data_loader import load_experiment
from experiments.experiment_config import ExperimentConfig
from experiments.experiment_controller import ExperimentController
from experiments.rotation_intensity_scan import RotationIntensityExperiment
from hardware.devices.power_meter.models import PowerSample, PowerTrace
from tests.test_experiment_workflow import (
    DummyPlotManager,
    FakeShutter,
    FakeSpectrometer,
    FakeStage,
)


class FakePowerProbe:
    def __init__(self, hardware):
        self.hardware = hardware
        self.call_count = 0

    def acquire_trace(self, *, duration_s, settle_time_s):
        self.call_count += 1
        waveplate = self.hardware.waveplate.position
        self.hardware.events.append(
            ("power", waveplate, duration_s, settle_time_s)
        )
        power_w = (10.0 + waveplate) / 1000.0
        return PowerTrace(
            trace_id=f"trace-{self.call_count}",
            requested_duration_s=duration_s,
            elapsed_duration_s=duration_s + 0.1,
            started_at_unix_s=1000.0 + self.call_count,
            device_serial="3144168",
            sensor_serial="3141552",
            measurement_mode="Power",
            wavelength_option="fake-2000-nm-band",
            range_option="fake-fixed-range",
            batch_sizes=(2,),
            samples=(
                PowerSample(
                    batch_index=0,
                    index_in_batch=0,
                    raw_value=power_w,
                    raw_timestamp=0.1,
                    raw_status=0,
                    power_w=power_w,
                    timestamp_s=0.1,
                    valid_for_statistics=True,
                ),
                PowerSample(
                    batch_index=0,
                    index_in_batch=1,
                    raw_value=0.0,
                    raw_timestamp=0.2,
                    raw_status=0,
                    power_w=0.0,
                    timestamp_s=0.2,
                    valid_for_statistics=False,
                    invalid_reasons=("value_not_positive",),
                ),
            ),
        )

    def safe_retract(self):
        self.hardware.events.append(("power", "retract"))

    def info(self):
        return {"is_out": True}


class FakePowerHardwareManager:
    last_instance = None

    def __init__(
        self,
        *,
        enable_power_meter=False,
        power_meter_wavelength_option=None,
        power_meter_range_option=None,
    ):
        assert enable_power_meter
        self.events: list[tuple] = []
        self.waveplate = FakeStage("Waveplate", self.events)
        self.sample = FakeStage("Sample Stage", self.events)
        self.shutter = FakeShutter(self.events)
        self.spectrometer = FakeSpectrometer(self.shutter, self.events)
        self.power_probe = FakePowerProbe(self)
        self.power_meter_wavelength_option = power_meter_wavelength_option
        self.power_meter_range_option = power_meter_range_option
        FakePowerHardwareManager.last_instance = self

    def __enter__(self):
        self.shutter.close()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.shutter.close()
        return False

    def summary(self):
        return {
            "waveplate": self.waveplate.info(),
            "sample": self.sample.info(),
            "shutter": self.shutter.info(),
            "spectrometer": self.spectrometer.info(),
            "power_probe": self.power_probe.info(),
        }


class FailingSpectrumHardwareManager(FakePowerHardwareManager):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        original_acquire = self.spectrometer.acquire

        def fail_illuminated(*, averages=1):
            if self.shutter.is_open:
                raise RuntimeError("simulated spectrum failure")
            return original_acquire(averages=averages)

        self.spectrometer.acquire = fail_illuminated


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="power_workflow_") as temporary:
        config = ExperimentConfig()
        config.saving.output_directory = Path(temporary)
        config.saving.experiment_name = "PowerWorkflow"
        config.background.enabled = False
        config.shutter.open_delay_s = 0.0
        config.shutter.close_delay_s = 0.0
        config.power_meter.enabled = True
        config.power_meter.cadence = "per_intensity"
        config.power_meter.measurement_duration_s = 10.0
        config.power_meter.pre_measurement_settle_s = 3.0
        config.power_meter.wavelength_option = "fake-2000-nm-band"
        config.power_meter.range_option = "fake-fixed-range"

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
                waveplate_angles=[0.0, 5.0],
                sample_angles=[0.0, 10.0, 20.0],
            )

        hardware = FakePowerHardwareManager.last_instance
        root = next(Path(temporary).iterdir())
        dataset = load_experiment(root)

        assert len(dataset) == 6
        assert len(dataset.power_traces) == 2
        assert hardware.power_probe.call_count == 2
        assert [measurement.waveplate_angle_deg for measurement in dataset] == [
            0.0,
            0.0,
            0.0,
            5.0,
            5.0,
            5.0,
        ]
        assert [measurement.sample_angle_deg for measurement in dataset] == [
            0.0,
            10.0,
            20.0,
            0.0,
            10.0,
            20.0,
        ]
        assert [measurement.power_trace_id for measurement in dataset] == [
            "trace-1",
            "trace-1",
            "trace-1",
            "trace-2",
            "trace-2",
            "trace-2",
        ]
        assert [measurement.power_mw for measurement in dataset] == [
            10.0,
            10.0,
            10.0,
            15.0,
            15.0,
            15.0,
        ]
        assert all(
            measurement.target_power_mw is None for measurement in dataset
        )
        assert len({m.power_measurement_id for m in dataset[:3]}) == 1
        assert len({m.power_measurement_id for m in dataset[3:]}) == 1
        assert dataset[0].power_measurement_id != dataset[3].power_measurement_id
        assert len(dataset.power_attempts) == 2
        assert all(
            measurement.power_measurement_status
            == "measured_with_invalid_samples"
            for measurement in dataset
        )

        significant_events = [
            event
            for event in hardware.events
            if event[0] in {"move", "power", "acquire"}
            and not (event[0] == "acquire" and event[1] == "closed")
        ]
        assert significant_events[:5] == [
            ("move", "Waveplate", 0.0),
            ("power", 0.0, 10.0, 3.0),
            ("move", "Sample Stage", 0.0),
            ("acquire", "open", 1),
            ("move", "Sample Stage", 10.0),
        ]

    # A completed raw power trace is durable even if the first spectrum in
    # its intensity block fails immediately afterwards.
    with tempfile.TemporaryDirectory(prefix="power_before_spectrum_") as temporary:
        config = ExperimentConfig()
        config.saving.output_directory = Path(temporary)
        config.saving.experiment_name = "PowerBeforeSpectrum"
        config.background.enabled = False
        config.shutter.open_delay_s = 0.0
        config.shutter.close_delay_s = 0.0
        config.power_meter.enabled = True
        config.power_meter.wavelength_option = "fake-2000-nm-band"
        config.power_meter.range_option = "fake-fixed-range"

        with (
            patch(
                "experiments.experiment_controller.HardwareManager",
                FailingSpectrumHardwareManager,
            ),
            patch(
                "experiments.experiment_controller.PlotManager",
                DummyPlotManager,
            ),
        ):
            try:
                ExperimentController(
                    config=config,
                    experiment=RotationIntensityExperiment(),
                ).run(waveplate_angles=[0.0], sample_angles=[0.0])
            except RuntimeError as error:
                assert "simulated spectrum failure" in str(error)
            else:
                raise AssertionError("Expected simulated spectrum failure.")

        failed_dataset = load_experiment(next(Path(temporary).iterdir()))
        assert len(failed_dataset) == 0
        assert len(failed_dataset.power_attempts) == 1
        assert len(failed_dataset.power_traces) == 1

    print("POWER EXPERIMENT WORKFLOW TEST PASSED")


if __name__ == "__main__":
    main()
