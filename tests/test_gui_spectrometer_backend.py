"""Hardware-free tests for the capability-limited Ocean SR GUI backend."""

from __future__ import annotations

import tempfile
import threading
import time
from types import SimpleNamespace
from pathlib import Path

import numpy as np

from gui.spectrometer_backend import SpectrometerCampaignBackend
from gui.state import (
    CalibrationRequest,
    LiveViewRequest,
    ScanRequest,
    TargetPowerRequest,
)
from data.data_loader import load_experiment
from hardware.devices.spectrometer.spectrum import Spectrum
from hardware.devices.power_meter.models import PowerSample, PowerTrace


class FakeSpectrometer:
    def __init__(self, serial: str, integration_time_ms: float) -> None:
        self.serial = serial
        self.integration_time_ms = integration_time_ms
        self.connected = False
        self.calls: list[tuple[str, int]] = []
        self.frame = 0

    def connect(self) -> None:
        self.calls.append(("connect", threading.get_ident()))
        self.connected = True

    def disconnect(self) -> None:
        self.calls.append(("disconnect", threading.get_ident()))
        self.connected = False

    def set_integration_time(self, integration_time_ms: float) -> None:
        self.calls.append(("configure", threading.get_ident()))
        self.integration_time_ms = integration_time_ms

    def acquire(self, *, averages: int = 1) -> Spectrum:
        self.calls.append(("acquire", threading.get_ident()))
        time.sleep(0.002)
        self.frame += 1
        return Spectrum(
            wavelengths=np.array([400.0, 500.0, 600.0]),
            intensities=np.array([1.0, 2.0, 3.0]) + self.frame,
            integration_time_ms=self.integration_time_ms,
            serial=self.serial,
            averages=averages,
        )


class FakeStage:
    def __init__(self, serial: str, name: str, maximum_velocity: float | None) -> None:
        self.serial, self.name = serial, name
        self.connected = False
        self.position = 0.0
        self.calls = []
    def connect(self): self.connected = True; self.calls.append("connect")
    def disconnect(self): self.connected = False; self.calls.append("disconnect")
    def move_to(self, angle): self.position = float(angle); self.calls.append("move")
    def stop(self): self.calls.append("stop")
    def home(self): self.position = 0.0; self.calls.append("home")


class FakeShutter:
    def __init__(self, serial: str, name: str) -> None:
        self.serial, self.name = serial, name
        self.connected = False
        self.is_closed = False
        self.calls = []
    def connect(self): self.connected = True; self.calls.append("connect")
    @property
    def is_open(self): return not self.is_closed
    def close(self): self.is_closed = True; self.calls.append("close")
    def open(self): self.is_closed = False; self.calls.append("open")
    def disconnect(self): self.connected = False; self.calls.append("disconnect")


class FakePIStage:
    def __init__(self, serial: str) -> None:
        self.serial = serial
        self.connected = False
        self.position_mm = -12.0
        self.calls = []
        self.referenced = True
    def connect(self): self.connected = True; self.calls.append("connect")
    def disconnect(self): self.connected = False; self.calls.append("disconnect")
    def prepare_for_closed_loop(self): self.calls.append("prepare")
    def refresh_snapshot(self):
        return SimpleNamespace(referenced=self.referenced)
    def reference_to_switch(self, **kwargs):
        self.referenced = True
        self.calls.append("reference")
        return self.refresh_snapshot()
    def move_absolute_mm(self, target): self.position_mm = float(target); self.calls.append("move")
    def halt(self): self.calls.append("halt")


class FakePowerMeter:
    def __init__(self, serial: str) -> None:
        self.controller_serial = serial
        self.connected = False
    def connect(self): self.connected = True
    def disconnect(self): self.connected = False
    def info(self): return {"range_option": "30.0mW", "wavelength_option": ">800"}
    def acquire_trace(self, duration_s, *, poll_interval_s):
        sample = PowerSample(
            batch_index=0, index_in_batch=0, raw_value=0.005,
            raw_timestamp=1.0, raw_status=0, power_w=0.005,
            timestamp_s=1.0, valid_for_statistics=True,
        )
        return PowerTrace(
            samples=(sample,), batch_sizes=(1,), requested_duration_s=duration_s,
            elapsed_duration_s=duration_s, started_at_unix_s=1.0,
            device_serial=self.controller_serial, sensor_serial="FAKE-SENSOR",
            wavelength_option=">800", range_option="30.0mW",
        )


def main() -> None:
    created: list[FakeSpectrometer] = []

    def factory(serial: str, integration_time_ms: float) -> FakeSpectrometer:
        device = FakeSpectrometer(serial, integration_time_ms)
        created.append(device)
        return device

    backend = SpectrometerCampaignBackend(
        spectrometer_factory=factory,
        stage_factory=FakeStage,
        shutter_factory=FakeShutter,
        pi_stage_factory=FakePIStage,
        power_meter_factory=FakePowerMeter,
        default_serial="FAKE-SR",
    )
    initial = backend.snapshot()
    assert not initial.simulation
    assert {device.key for device in initial.devices if device.available} == {
        "waveplate", "sample", "shutter", "spectrometer", "power_meter_stage",
        "power_meter",
    }
    assert not initial.all_connected

    snapshots = []
    spectra = []
    logs = []
    errors = []
    with tempfile.TemporaryDirectory(prefix="gui_ocean_fake_") as temporary:
        output = Path(temporary)

        def exercise() -> None:
            try:
                backend.connect_all(
                    snapshots.append, serials={"spectrometer": "FAKE-SR-2"}
                )
                backend.power_trace_directory = output
                backend.set_operator_settings({
                    "rotation_readback_tolerance_deg": 0.05,
                    "saturation_warning_counts": 65_535.0,
                    "probe_in_position_mm": 12.0,
                    "probe_out_position_mm": -12.0,
                    "power_measurement_duration_s": 1.0,
                    "power_settle_time_s": 0.0,
                    "power_poll_interval_s": 0.1,
                })
                assert backend.measure_power(snapshots.append) == 5.0
                assert snapshots[-1].probe_out is True
                backend.move_stage("sample", 12.5, snapshots.append)
                backend.move_probe_absolute(5.0, snapshots.append)
                assert snapshots[-1].probe_out is False
                try:
                    backend.open_shutter(snapshots.append)
                except RuntimeError as error:
                    assert "not live-verified out" in str(error)
                else:  # pragma: no cover
                    raise AssertionError("Unverified shutter opening was not interlocked.")
                backend.open_shutter(
                    snapshots.append, allow_unverified_probe=True
                )
                assert snapshots[-1].shutter_closed is False
                backend.move_probe_absolute(-12.0, snapshots.append)
                assert snapshots[-1].probe_out is True
                backend.run_live_view(
                    LiveViewRequest(
                        integration_time_ms=2.0,
                        averages=2,
                        refresh_interval_s=0.01,
                    ),
                    publish_snapshot=snapshots.append,
                    publish_spectrum=lambda raw, displayed, metadata: spectra.append(
                        (raw, displayed, metadata)
                    ),
                    publish_log=logs.append,
                )
                backend.safe_disconnect(snapshots.append)
            except Exception as error:  # pragma: no cover - diagnostic capture
                errors.append(error)

        worker = threading.Thread(target=exercise)
        worker.start()
        deadline = time.monotonic() + 2.0
        while len(spectra) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(spectra) >= 2
        backend.queue_live_settings(integration_time_ms=4.0, averages=3)
        backend.queue_live_background_capture()
        backend.queue_live_save(output)
        deadline = time.monotonic() + 2.0
        while not list(output.glob("live_spectrum_*.npz")) and time.monotonic() < deadline:
            time.sleep(0.01)
        backend.request_live_stop()
        worker.join(timeout=2.0)
        assert not worker.is_alive()
        assert not errors
        saved = next(output.glob("*.npz"))
        power_saved = next(output.glob("power_trace_*.npz"))
        with np.load(power_saved, allow_pickle=False) as archive:
            assert archive["power_w"].tolist() == [0.005]
            assert archive["valid_for_statistics"].tolist() == [True]
            assert archive["range_option"].item() == "30.0mW"
        live_saved = next(path for path in output.glob("live_spectrum_*.npz"))
        with np.load(live_saved, allow_pickle=False) as archive:
            assert archive["simulation"].item() is False
            assert archive["serial"].item() == "FAKE-SR-2"

    assert snapshots[-1].any_connected is False
    call_threads = {thread_id for _, thread_id in created[0].calls}
    assert len(call_threads) == 1
    assert any(name == "acquire" for name, _ in created[0].calls)
    assert any("background" in message.lower() for message in logs)
    assert snapshots[-1].shutter_closed is None

    stuck_backend = SpectrometerCampaignBackend(
        spectrometer_factory=factory,
        stage_factory=FakeStage,
        shutter_factory=FakeShutter,
        pi_stage_factory=FakePIStage,
        power_meter_factory=FakePowerMeter,
    )
    stuck_backend.connect_device("shutter", "FAKE-SHUTTER", snapshots.append)
    stuck_backend.connect_device("sample", "FAKE-SAMPLE", snapshots.append)
    stuck_backend._stages["sample"].move_to = lambda angle: None
    stuck_backend.set_operator_settings(
        {
            "rotation_readback_tolerance_deg": 0.125,
            "saturation_warning_counts": 60_000.0,
            "probe_in_position_mm": 12.0,
            "probe_out_position_mm": -12.0,
            "power_measurement_duration_s": 1.0,
            "power_settle_time_s": 0.0,
            "power_poll_interval_s": 0.1,
        }
    )
    try:
        stuck_backend.move_stage("sample", 20.0, snapshots.append)
    except RuntimeError as error:
        assert "requested 20.0000" in str(error)
        assert "live position readback is 0.0000" in str(error)
        assert "mount is connected" in str(error)
        assert "Tolerance is 0.125 deg" in str(error)
    else:  # pragma: no cover
        raise AssertionError("A false completed move was accepted.")
    stuck_backend.safe_disconnect(snapshots.append)

    class HealthStage(FakeStage):
        def __init__(self, *args):
            super().__init__(*args)
            self.healthy = True

        def check_connection(self):
            if not self.healthy:
                raise RuntimeError("simulated USB removal")
            _ = self.position
            return True

    class HealthSpectrometer(FakeSpectrometer):
        def __init__(self, *args):
            super().__init__(*args)
            self.healthy = True

        def check_connection(self):
            if not self.healthy:
                raise RuntimeError("simulated spectrometer USB removal")
            return True

    class HealthPowerMeter(FakePowerMeter):
        def __init__(self, *args):
            super().__init__(*args)
            self.healthy = True

        def check_connection(self):
            if not self.healthy:
                raise RuntimeError("simulated power-meter USB removal")
            return True

    health_spectrometers = []

    def health_spectrometer_factory(serial, integration_time_ms):
        device = HealthSpectrometer(serial, integration_time_ms)
        health_spectrometers.append(device)
        return device

    health_backend = SpectrometerCampaignBackend(
        spectrometer_factory=health_spectrometer_factory,
        stage_factory=HealthStage,
        shutter_factory=FakeShutter,
        pi_stage_factory=FakePIStage,
        power_meter_factory=HealthPowerMeter,
    )
    health_backend.connect_all(snapshots.append)
    health_backend._stages["sample"].healthy = False
    health_snapshot, health_losses = health_backend.poll_idle_health()
    assert any("sample: simulated USB removal" in loss for loss in health_losses)
    assert not health_snapshot.all_connected
    assert "sample" not in health_backend._stages
    assert "move" not in health_backend._stages["waveplate"].calls

    health_spectrometers[0].healthy = False
    health_snapshot, health_losses = health_backend.poll_idle_health()
    assert any(
        "spectrometer: simulated spectrometer USB removal" in loss
        for loss in health_losses
    )
    assert health_backend._spectrometer is None
    assert next(
        device for device in health_snapshot.devices if device.key == "spectrometer"
    ).connection.value == "disconnected"

    assert health_backend._power_meter is not None
    health_backend._power_meter.healthy = False
    health_snapshot, health_losses = health_backend.poll_idle_health()
    assert any(
        "power_meter: simulated power-meter USB removal" in loss
        for loss in health_losses
    )
    assert health_backend._power_meter is None
    assert next(
        device for device in health_snapshot.devices if device.key == "power_meter"
    ).connection.value == "disconnected"
    health_backend.safe_disconnect(snapshots.append)

    class MissingPIStage(FakePIStage):
        def connect(self):
            raise RuntimeError("simulated translation stage absent")

    partial_backend = SpectrometerCampaignBackend(
        spectrometer_factory=factory,
        stage_factory=FakeStage,
        shutter_factory=FakeShutter,
        pi_stage_factory=MissingPIStage,
        power_meter_factory=FakePowerMeter,
    )
    partial_report = partial_backend.connect_all(snapshots.append)
    assert any(
        key == "power_meter_stage" and "translation stage absent" in message
        for key, message in partial_report["failures"]
    )
    assert partial_backend.snapshot().any_connected
    assert partial_backend.connected
    assert not partial_backend.snapshot().all_connected
    assert "power_meter_stage" not in {
        device.key
        for device in partial_backend.snapshot().devices
        if device.connection.value == "connected"
    }
    partial_backend.safe_disconnect(snapshots.append)

    scan_backend = SpectrometerCampaignBackend(
        spectrometer_factory=factory,
        stage_factory=FakeStage,
        shutter_factory=FakeShutter,
        pi_stage_factory=FakePIStage,
        power_meter_factory=FakePowerMeter,
    )
    scan_backend.connect_all(snapshots.append)
    scan_backend.set_operator_settings({
        "rotation_readback_tolerance_deg": 0.05,
        "saturation_warning_counts": 65_535.0,
        "probe_in_position_mm": 12.0,
        "probe_out_position_mm": -12.0,
        "power_measurement_duration_s": 0.01,
        "power_settle_time_s": 0.0,
        "power_poll_interval_s": 0.01,
    })
    with tempfile.TemporaryDirectory(prefix="gui_hardware_scan_fake_") as temporary:
        output = Path(temporary)
        published = []
        completed = scan_backend.run_scan(
            ScanRequest(
                sample_angles_deg=(0.0, 10.0),
                intensity_values=(2.0,),
                rotation_target="polarization_half_waveplate",
                intensity_mode="waveplate_angle_deg",
                spectra_per_point=2,
                integration_time_ms=3.0,
                averages=1,
                output_directory=output,
                experiment_name="fake_hardware_scan",
            ),
            publish_snapshot=snapshots.append,
            publish_measurement=lambda measurement, done, total: published.append(
                (measurement, done, total)
            ),
            publish_log=logs.append,
        )
        assert completed is True
        assert len(published) == 4
        experiment = next(output.glob("fake_hardware_scan_*"))
        dataset = load_experiment(experiment)
        assert len(dataset.measurements) == 4
        assert len(dataset.power_attempts) == 1
        assert len(dataset.power_traces) == 1
        assert all(item.power_mw == 5.0 for item in dataset.measurements)
        assert dataset.config["rotation_target"] == "polarization_half_waveplate"
        assert dataset.config["rotation_stage_key"] == "sample"
        assert all(
            item.metadata["rotation"]["target"]
            == "polarization_half_waveplate"
            for item in dataset.measurements
        )
        assert any(
            "Moving polarisation half-waveplate mount" in message
            for message in logs
        )
        assert scan_backend.snapshot().shutter_closed is True
        assert scan_backend.snapshot().probe_out is True
    scan_backend.safe_disconnect(snapshots.append)

    disconnect_backend = SpectrometerCampaignBackend(
        spectrometer_factory=factory,
        stage_factory=FakeStage,
        shutter_factory=FakeShutter,
        pi_stage_factory=FakePIStage,
        power_meter_factory=FakePowerMeter,
    )
    disconnect_backend.connect_all(snapshots.append)
    disconnect_backend.set_operator_settings({
        "rotation_readback_tolerance_deg": 0.05,
        "saturation_warning_counts": 65_535.0,
        "probe_in_position_mm": 12.0,
        "probe_out_position_mm": -12.0,
        "power_measurement_duration_s": 0.01,
        "power_settle_time_s": 0.0,
        "power_poll_interval_s": 0.01,
    })
    disconnect_spectrometer = disconnect_backend._spectrometer
    original_acquire = disconnect_spectrometer.acquire

    def acquire_then_disconnect(*, averages=1):
        spectrum = original_acquire(averages=averages)
        disconnect_spectrometer.connected = False
        return spectrum

    disconnect_spectrometer.acquire = acquire_then_disconnect
    with tempfile.TemporaryDirectory(prefix="gui_disconnect_scan_fake_") as temporary:
        output = Path(temporary)
        published = []
        try:
            disconnect_backend.run_scan(
                ScanRequest(
                    sample_angles_deg=(0.0,),
                    intensity_values=(2.0,),
                    intensity_mode="waveplate_angle_deg",
                    spectra_per_point=2,
                    acquire_background=False,
                    output_directory=output,
                    experiment_name="fake_disconnect_scan",
                ),
                publish_snapshot=snapshots.append,
                publish_measurement=lambda measurement, done, total: published.append(
                    (measurement, done, total)
                ),
                publish_log=logs.append,
            )
        except RuntimeError as error:
            assert "connection lost during scan" in str(error)
            assert "spectrometer" in str(error)
        else:  # pragma: no cover
            raise AssertionError("A lost spectrometer connection did not abort the scan.")
        assert len(published) == 1
        dataset = load_experiment(next(output.glob("fake_disconnect_scan_*")))
        assert len(dataset.measurements) == 1
        assert disconnect_backend.snapshot().shutter_closed is True
    disconnect_backend.safe_disconnect(snapshots.append)

    positions = {"Waveplate": 0.0}

    class TargetStage(FakeStage):
        def move_to(self, angle):
            super().move_to(angle)
            if "waveplate" in self.name.lower():
                positions["Waveplate"] = float(angle)

    class TargetPowerMeter(FakePowerMeter):
        def acquire_trace(self, duration_s, *, poll_interval_s):
            power_w = (10.0 + positions["Waveplate"]) / 1000.0
            sample = PowerSample(
                batch_index=0, index_in_batch=0, raw_value=power_w,
                raw_timestamp=1.0, raw_status=0, power_w=power_w,
                timestamp_s=1.0, valid_for_statistics=True,
            )
            return PowerTrace(
                samples=(sample,), batch_sizes=(1,), requested_duration_s=duration_s,
                elapsed_duration_s=duration_s, started_at_unix_s=1.0,
                device_serial=self.controller_serial, sensor_serial="FAKE-SENSOR",
                wavelength_option=">800", range_option="30.0mW",
            )

    target_backend = SpectrometerCampaignBackend(
        spectrometer_factory=factory,
        stage_factory=TargetStage,
        shutter_factory=FakeShutter,
        pi_stage_factory=FakePIStage,
        power_meter_factory=TargetPowerMeter,
    )
    target_backend.connect_all(snapshots.append)
    target_backend.set_operator_settings({
        "rotation_readback_tolerance_deg": 0.05,
        "saturation_warning_counts": 65_535.0,
        "probe_in_position_mm": 12.0,
        "probe_out_position_mm": -12.0,
        "power_measurement_duration_s": 0.01,
        "power_settle_time_s": 0.0,
        "power_poll_interval_s": 0.01,
    })
    with tempfile.TemporaryDirectory(prefix="gui_target_scan_fake_") as temporary:
        output = Path(temporary)
        manual_power = target_backend.set_power(
            TargetPowerRequest(
                target_power_mw=12.0,
                waveplate_min_deg=0.0,
                waveplate_max_deg=10.0,
                monotonic_direction="increasing",
                target_tolerance_mw=0.01,
                output_directory=output,
            ),
            snapshots.append,
            publish_log=logs.append,
        )
        assert manual_power == 12.0
        manual_run = next(output.glob("manual_target_power_*"))
        manual_dataset = load_experiment(manual_run)
        assert len(manual_dataset.measurements) == 0
        assert len(manual_dataset.power_attempts) == 3
        assert len(manual_dataset.power_traces) == 3
        assert target_backend.snapshot().probe_out is True
        assert target_backend.snapshot().shutter_closed is True

        assert target_backend.run_scan(
            ScanRequest(
                sample_angles_deg=(0.0,), intensity_values=(13.0,),
                intensity_mode="target_power_mw", spectra_per_point=1,
                acquire_background=False, output_directory=output,
                experiment_name="fake_target_scan", waveplate_min_deg=0.0,
                waveplate_max_deg=10.0, monotonic_direction="increasing",
                target_tolerance_mw=0.01,
            ),
            publish_snapshot=snapshots.append,
            publish_measurement=lambda *args: None,
            publish_log=logs.append,
        )
        dataset = load_experiment(next(output.glob("fake_target_scan_*")))
        assert len(dataset.measurements) == 1
        assert dataset.measurements[0].target_power_mw == 13.0
        assert dataset.measurements[0].power_mw == 13.0
        assert dataset.measurements[0].waveplate_angle_deg == 3.0
        assert len(dataset.power_attempts) == 3
        assert len(dataset.power_traces) == 3
        assert target_backend.snapshot().probe_out is True
        assert target_backend.snapshot().shutter_closed is True

        calibration_points = []
        calibration_result = target_backend.run_calibration(
            CalibrationRequest(
                start_deg=0.0, stop_deg=10.0, step_deg=5.0,
                output_directory=output / "calibrations",
            ),
            publish_snapshot=snapshots.append,
            publish_point=lambda *point: calibration_points.append(point),
            publish_log=logs.append,
        )
        assert len(calibration_points) == 3
        assert calibration_result["direction"] == "increasing"
        assert Path(calibration_result["calibration_path"]).is_file()
        assert target_backend.snapshot().probe_out is True
        assert target_backend.snapshot().shutter_closed is True
    target_backend.safe_disconnect(snapshots.append)

    print("GUI SPECTROMETER BACKEND TEST PASSED")


if __name__ == "__main__":
    main()
