"""Hardware-free state, persistence, and cancellation tests for the GUI backend."""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np

from data.data_loader import load_experiment
from gui.simulated_backend import SimulatedCampaignBackend
from gui.state import (
    CalibrationRequest, LiveViewRequest, ScanRequest, inclusive_range,
    parse_harmonic_windows, parse_number_list,
)
from hardware.devices.spectrometer.spectrum import Spectrum


def main() -> None:
    assert parse_number_list("0, 10  20", field_name="angles") == (
        0.0,
        10.0,
        20.0,
    )
    assert len(inclusive_range(0, 360, 5)) == 73
    assert inclusive_range(10, 0, 3) == (10.0, 7.0, 4.0, 1.0, 0.0)
    windows = parse_harmonic_windows("H5:390:410, H7:275:295")
    assert windows[0].center_nm == 400.0
    compatibility_spectrum = Spectrum(
        wavelengths=np.asarray([1.0, 2.0, 3.0]),
        intensities=np.asarray([2.0, 2.0, 2.0]),
        integration_time_ms=1.0,
        serial="COMPATIBILITY",
    )
    with patch.object(
        np, "trapezoid", getattr(np, "trapz", np.trapezoid), create=True
    ), patch.object(np, "trapz", None, create=True):
        assert compatibility_spectrum.integrate(1.0, 3.0) == 4.0

    with tempfile.TemporaryDirectory(prefix="campaign_gui_") as temporary:
        backend = SimulatedCampaignBackend()
        snapshots = []
        measurements = []
        logs = []
        backend.connect_device(
            "spectrometer",
            "SIM-CUSTOM-SPECTROMETER",
            snapshots.append,
        )
        assert snapshots[-1].any_connected
        assert not snapshots[-1].all_connected
        backend.disconnect_device("spectrometer", snapshots.append)
        assert not snapshots[-1].any_connected
        backend.connect_all(
            snapshots.append,
            serials={"spectrometer": "SIM-CUSTOM-SPECTROMETER"},
        )
        assert snapshots[-1].all_connected
        assert next(
            device.identity
            for device in snapshots[-1].devices
            if device.key == "spectrometer"
        ) == "SIM-CUSTOM-SPECTROMETER"
        assert snapshots[-1].sample_path_safe
        backend.open_shutter(snapshots.append)
        assert snapshots[-1].shutter_closed is False
        backend.close_shutter(snapshots.append)
        assert snapshots[-1].shutter_closed is True

        backend.move_stage("sample", 12.5, snapshots.append)
        backend.set_probe(out=False, publish=snapshots.append)
        assert snapshots[-1].probe_out is False
        backend.set_probe(out=True, publish=snapshots.append)
        backend.set_power(6.5, snapshots.append)
        assert snapshots[-1].beam_power_mw == 6.5
        assert snapshots[-1].shutter_closed is True
        assert snapshots[-1].probe_out is True
        measured_power = backend.measure_power(snapshots.append)
        assert measured_power == 6.5

        request = ScanRequest(
            sample_angles_deg=(0.0, 15.0),
            intensity_values=(5.0, 7.0),
            rotation_target="polarization_half_waveplate",
            spectra_per_point=3,
            integration_time_ms=2.0,
            output_directory=Path(temporary),
            experiment_name="GuiSimulation",
            notes="hardware-free GUI regression",
        )
        completed = backend.run_scan(
            request,
            publish_snapshot=snapshots.append,
            publish_measurement=lambda measurement, index, total: measurements.append(
                (measurement, index, total)
            ),
            publish_log=logs.append,
        )
        assert completed is True
        assert len(measurements) == request.total_spectra == 12
        assert snapshots[-1].shutter_closed is True
        assert snapshots[-1].probe_out is True
        assert snapshots[-1].busy is False
        assert all(item[0].metadata["simulation"] for item in measurements)

        experiment_directory = next(Path(temporary).iterdir())
        dataset = load_experiment(experiment_directory)
        assert len(dataset) == request.total_spectra
        assert len(dataset.backgrounds) == 1
        assert dataset.metadata["simulation"] is True
        assert dataset.metadata["operator_notes"] == (
            "hardware-free GUI regression"
        )
        assert dataset.config["rotation_target"] == "polarization_half_waveplate"
        assert dataset.config["rotation_stage_key"] == "sample"
        assert dataset.config["rotation_angle_semantics"] == "physical_mount_angle_deg"
        assert all(
            measurement.metadata["replicate"]["count"] == 3
            for measurement in dataset
        )
        assert all(
            measurement.metadata["rotation"] == {
                "target": "polarization_half_waveplate",
                "target_name": "polarisation half-waveplate",
                "stage_key": "sample",
                "angle_name": "polarisation HWP mount angle",
                "angle_semantics": "physical_mount_angle_deg",
                "physical_mount_angle_deg": measurement.sample_angle_deg,
            }
            for measurement in dataset
        )

        paused_measurements = []
        pause_request = ScanRequest(
            sample_angles_deg=tuple(float(value) for value in range(10)),
            intensity_values=(5.0,), spectra_per_point=2,
            acquire_background=False, output_directory=Path(temporary),
            experiment_name="PauseResumeSimulation",
        )
        pause_thread = threading.Thread(
            target=backend.run_scan,
            kwargs={
                "request": pause_request,
                "publish_snapshot": snapshots.append,
                "publish_measurement": lambda measurement, index, total: paused_measurements.append(measurement),
                "publish_log": logs.append,
            },
        )
        pause_thread.start()
        deadline = time.monotonic() + 2.0
        while not paused_measurements:
            if time.monotonic() > deadline:
                raise AssertionError("Pause test did not begin.")
            time.sleep(0.01)
        backend.request_pause(True)
        time.sleep(0.15)
        paused_count = len(paused_measurements)
        time.sleep(0.15)
        assert len(paused_measurements) == paused_count
        backend.request_pause(False)
        pause_thread.join(timeout=3.0)
        assert not pause_thread.is_alive()
        assert len(paused_measurements) == pause_request.total_spectra
        assert any("paused at a safe point" in message for message in logs)

        calibration_points = []
        pre_calibration_waveplate = backend.waveplate_angle_deg
        calibration_result = backend.run_calibration(
            CalibrationRequest(
                start_deg=0.0,
                stop_deg=10.0,
                step_deg=5.0,
                output_directory=Path(temporary) / "calibrations",
            ),
            publish_snapshot=snapshots.append,
            publish_point=lambda *point: calibration_points.append(point),
            publish_log=logs.append,
        )
        assert len(calibration_points) == 3
        assert Path(calibration_result["calibration_path"]).is_file()
        assert calibration_result["direction"] == "increasing"
        assert backend.waveplate_angle_deg == pre_calibration_waveplate
        assert snapshots[-1].shutter_closed is True
        assert snapshots[-1].probe_out is True

        live_spectra = []
        live_directory = Path(temporary) / "live"
        live_thread = threading.Thread(
            target=backend.run_live_view,
            kwargs={
                "request": LiveViewRequest(
                    integration_time_ms=5.0,
                    averages=2,
                    refresh_interval_s=0.01,
                    output_directory=live_directory,
                ),
                "publish_snapshot": snapshots.append,
                "publish_spectrum": (
                    lambda raw, displayed, metadata: live_spectra.append(
                        (raw, displayed, metadata)
                    )
                ),
                "publish_log": logs.append,
            },
        )
        live_thread.start()
        deadline = time.monotonic() + 2.0
        while len(live_spectra) < 2:
            if time.monotonic() > deadline:
                raise AssertionError("Simulated live spectra did not arrive.")
            time.sleep(0.01)
        backend.queue_live_background_capture()
        backend.queue_live_settings(integration_time_ms=8.0, averages=4)
        backend.queue_live_stage_move("sample", 22.5)
        backend.queue_live_set_power(9.0)
        backend.queue_live_measure_power()
        backend.queue_live_save(live_directory)
        deadline = time.monotonic() + 2.0
        while not live_directory.exists() or not tuple(live_directory.glob("*.npz")):
            if time.monotonic() > deadline:
                raise AssertionError("Simulated live spectrum was not saved.")
            time.sleep(0.01)
        backend.request_live_stop()
        live_thread.join(timeout=2.0)
        assert not live_thread.is_alive()
        assert live_spectra[-1][0].integration_time_ms == 8.0
        assert live_spectra[-1][0].averages == 4
        assert live_spectra[-1][2]["background_available"] is True
        assert snapshots[-1].beam_power_mw == 9.0
        assert backend.sample_angle_deg == 22.5
        assert snapshots[-1].shutter_closed is True
        assert snapshots[-1].probe_out is True
        with np.load(next(live_directory.glob("*.npz")), allow_pickle=False) as data:
            assert bool(data["simulation"])
            assert all(data[name].dtype != object for name in data.files)

    print("GUI SIMULATION TEST PASSED")


if __name__ == "__main__":
    main()
