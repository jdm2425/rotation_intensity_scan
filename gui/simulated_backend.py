"""Deterministic simulated campaign backend; never imports live drivers."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from queue import Empty, SimpleQueue
from typing import Callable

import numpy as np

from analysis.measurement import Measurement
from data.data_writer import DataWriter
from gui.state import (
    ConnectionState,
    DeviceSnapshot,
    GuiSnapshot,
    LiveViewRequest,
    ScanRequest,
)
from hardware.devices.spectrometer.spectrum import Spectrum


SnapshotCallback = Callable[[GuiSnapshot], None]
MeasurementCallback = Callable[[Measurement, int, int], None]
LogCallback = Callable[[str], None]


class SimulatedCampaignBackend:
    """In-memory fake implementing the first GUI's application operations."""

    DEVICE_NAMES = (
        ("waveplate", "Waveplate stage", "SIM-WAVEPLATE"),
        ("sample", "Sample stage", "SIM-SAMPLE"),
        ("shutter", "Beam shutter", "SIM-SHUTTER"),
        ("spectrometer", "Ocean SR spectrometer", "SIM-OCEAN-SR"),
        ("power_meter_stage", "Power-probe stage", "SIM-PI"),
        ("power_meter", "Ophir power meter", "SIM-OPHIR"),
    )

    def __init__(self) -> None:
        self._device_connections = {
            key: False for key, _, _ in self.DEVICE_NAMES
        }
        self._device_serials = {
            key: identity for key, _, identity in self.DEVICE_NAMES
        }
        self.busy = False
        self.shutter_closed = True
        self.probe_out = True
        self.waveplate_angle_deg = 0.0
        self.sample_angle_deg = 0.0
        self.beam_power_mw: float | None = None
        self._cancel = threading.Event()
        self._live_stop = threading.Event()
        self._live_commands: SimpleQueue[tuple[str, object]] = SimpleQueue()
        self._live_raw_spectrum: Spectrum | None = None
        self._live_display_spectrum: Spectrum | None = None
        self._live_background: Spectrum | None = None
        self._live_background_enabled = False

    @property
    def connected(self) -> bool:
        return all(self._device_connections.values())

    def snapshot(self) -> GuiSnapshot:
        values = {
            "waveplate": f"{self.waveplate_angle_deg:.3f} deg",
            "sample": f"{self.sample_angle_deg:.3f} deg",
            "shutter": "CLOSED" if self.shutter_closed else "OPEN",
            "spectrometer": "Ready" if self.connected else "Not available",
            "power_meter_stage": "OUT" if self.probe_out else "IN",
            "power_meter": (
                "--" if self.beam_power_mw is None else f"{self.beam_power_mw:.3f} mW"
            ),
        }
        return GuiSnapshot(
            devices=tuple(
                DeviceSnapshot(
                    key=key,
                    name=name,
                    identity=self._device_serials[key],
                    connection=(
                        ConnectionState.CONNECTED
                        if self._device_connections[key]
                        else ConnectionState.DISCONNECTED
                    ),
                    value=values[key],
                    detail="Simulated device",
                )
                for key, name, identity in self.DEVICE_NAMES
            ),
            shutter_closed=(
                self.shutter_closed
                if self._device_connections["shutter"]
                else None
            ),
            probe_out=(
                self.probe_out
                if self._device_connections["power_meter_stage"]
                else None
            ),
            beam_power_mw=(
                self.beam_power_mw
                if self._device_connections["power_meter"]
                else None
            ),
            busy=self.busy,
            simulation=True,
        )

    def connect_all(
        self,
        publish: SnapshotCallback,
        serials: dict[str, str] | None = None,
    ) -> None:
        if self.busy:
            raise RuntimeError("Cannot connect while another operation is active.")
        for key, serial in (serials or {}).items():
            self._require_device_key(key)
            serial = str(serial).strip()
            if not serial:
                raise ValueError(f"Serial/identity for {key} must not be empty.")
            self._device_serials[key] = serial
        for key in self._device_connections:
            self._device_connections[key] = True
        self.shutter_closed = True
        self.probe_out = True
        publish(self.snapshot())

    def safe_disconnect(self, publish: SnapshotCallback) -> None:
        self.safe_state(publish)
        for key in self._device_connections:
            self._device_connections[key] = False
        self.beam_power_mw = None
        publish(self.snapshot())

    def connect_device(
        self,
        key: str,
        serial: str,
        publish: SnapshotCallback,
    ) -> None:
        self._require_not_busy()
        self._require_device_key(key)
        serial = str(serial).strip()
        if not serial:
            raise ValueError("Device serial/identity must not be empty.")
        if self._device_connections[key]:
            if self._device_serials[key] != serial:
                raise RuntimeError(
                    f"Disconnect {key} before changing its serial/identity."
                )
            publish(self.snapshot())
            return
        self._device_serials[key] = serial
        self._device_connections[key] = True
        if key == "shutter":
            self.shutter_closed = True
        if key == "power_meter_stage":
            self.probe_out = True
        publish(self.snapshot())

    def disconnect_device(self, key: str, publish: SnapshotCallback) -> None:
        self._require_not_busy()
        self._require_device_key(key)
        if key == "shutter" and not self.probe_out:
            raise RuntimeError(
                "Cannot disconnect the shutter while the power probe is not out."
            )
        if key == "shutter":
            self.shutter_closed = True
        self._device_connections[key] = False
        if key == "power_meter":
            self.beam_power_mw = None
        publish(self.snapshot())

    def safe_state(self, publish: SnapshotCallback) -> None:
        self.shutter_closed = True
        self.probe_out = True
        self.busy = False
        publish(self.snapshot())

    def close_shutter(self, publish: SnapshotCallback) -> None:
        self._require_connected()
        self.shutter_closed = True
        publish(self.snapshot())

    def open_shutter(
        self, publish: SnapshotCallback, *, allow_unverified_probe: bool = False
    ) -> None:
        self._require_connected()
        if not self.probe_out:
            raise RuntimeError("Shutter opening refused: power probe is not verified out.")
        self.shutter_closed = False
        publish(self.snapshot())

    def queue_live_shutter(self, *, open_shutter: bool) -> None:
        self._live_commands.put(("shutter", bool(open_shutter)))

    def move_stage(
        self,
        stage: str,
        position: float,
        publish: SnapshotCallback,
    ) -> None:
        self._require_idle()
        self._perform_stage_move(stage, position)
        publish(self.snapshot())

    def home_rotation_stage(self, stage: str, publish: SnapshotCallback) -> None:
        self._require_idle()
        self.shutter_closed = True
        self._perform_stage_move(stage, 0.0)
        publish(self.snapshot())

    def reference_pi_stage(self, publish: SnapshotCallback) -> None:
        self._require_idle()
        self.shutter_closed = True
        publish(self.snapshot())

    def set_power(self, target_power_mw: float, publish: SnapshotCallback) -> None:
        """Simulate bounded power targeting and finish shutter-closed/probe-out."""

        self._require_idle()
        self._perform_set_power(target_power_mw)
        publish(self.snapshot())

    def measure_power(self, publish: SnapshotCallback) -> float:
        """Simulate one shutter-interlocked probe measurement session."""

        self._require_idle()
        value = self._perform_measure_power()
        publish(self.snapshot())
        return value

    def set_probe(self, *, out: bool, publish: SnapshotCallback) -> None:
        self._require_idle()
        if not self.shutter_closed:
            raise RuntimeError("The shutter must be closed before probe motion.")
        self.probe_out = bool(out)
        publish(self.snapshot())

    def request_cancel(self) -> None:
        self._cancel.set()

    def request_live_stop(self) -> None:
        """Request a stop without waiting for the worker event loop."""

        self._live_stop.set()

    def queue_live_settings(self, *, integration_time_ms: float, averages: int) -> None:
        self._live_commands.put(
            (
                "settings",
                (float(integration_time_ms), int(averages)),
            )
        )

    def queue_live_background_capture(self) -> None:
        self._live_commands.put(("capture_background", None))

    def queue_live_background_enabled(self, enabled: bool) -> None:
        self._live_commands.put(("background_enabled", bool(enabled)))

    def queue_live_save(self, output_directory: Path) -> None:
        self._live_commands.put(("save", Path(output_directory)))

    def queue_live_stage_move(self, stage: str, position: float) -> None:
        self._live_commands.put(("move_stage", (str(stage), float(position))))

    def queue_live_set_power(self, target_power_mw: float) -> None:
        self._live_commands.put(("set_power", float(target_power_mw)))

    def queue_live_measure_power(self) -> None:
        self._live_commands.put(("measure_power", None))

    def run_live_view(
        self,
        request: LiveViewRequest,
        *,
        publish_snapshot: SnapshotCallback,
        publish_spectrum: Callable[[Spectrum, Spectrum, dict], None],
        publish_log: LogCallback,
    ) -> None:
        """Continuously publish synthetic raw and displayed spectra."""

        self._require_idle()
        self.busy = True
        self._live_stop.clear()
        self._clear_live_commands()
        integration_time_ms = float(request.integration_time_ms)
        averages = int(request.averages)
        frame = 0
        publish_snapshot(self.snapshot())
        publish_log("Simulated live spectrometer started.")
        try:
            while not self._live_stop.is_set():
                integration_time_ms, averages = self._process_live_commands(
                    integration_time_ms=integration_time_ms,
                    averages=averages,
                    publish_snapshot=publish_snapshot,
                    publish_log=publish_log,
                )
                raw = self._live_spectrum(
                    integration_time_ms=integration_time_ms,
                    averages=averages,
                    frame=frame,
                )
                self._live_raw_spectrum = raw
                displayed = self._apply_live_background(raw)
                self._live_display_spectrum = displayed
                publish_spectrum(
                    raw,
                    displayed,
                    {
                        "frame": frame,
                        "background_available": self._live_background is not None,
                        "background_enabled": self._live_background_enabled,
                        "saturated": raw.maximum >= request.saturation_level,
                    },
                )
                frame += 1
                time.sleep(request.refresh_interval_s)
        finally:
            self.busy = False
            publish_snapshot(self.snapshot())
            publish_log("Simulated live spectrometer stopped.")

    def _process_live_commands(
        self,
        *,
        integration_time_ms: float,
        averages: int,
        publish_snapshot: SnapshotCallback,
        publish_log: LogCallback,
    ) -> tuple[float, int]:
        while True:
            try:
                command, payload = self._live_commands.get_nowait()
            except Empty:
                break
            if command == "settings":
                integration_time_ms, averages = payload
                if integration_time_ms <= 0 or averages < 1:
                    publish_log("Ignored invalid live acquisition settings.")
                else:
                    publish_log(
                        f"Live settings: {integration_time_ms:g} ms, "
                        f"{averages} average(s)."
                    )
            elif command == "capture_background":
                if self._live_raw_spectrum is None:
                    publish_log("No raw live spectrum is available for background capture.")
                else:
                    self._live_background = self._live_raw_spectrum.copy()
                    self._live_background_enabled = True
                    publish_log("Live background captured and subtraction enabled.")
            elif command == "background_enabled":
                enabled = bool(payload)
                if enabled and self._live_background is None:
                    self._live_background_enabled = False
                    publish_log("Capture a live background before enabling subtraction.")
                else:
                    self._live_background_enabled = enabled
                    publish_log(
                        "Live background subtraction "
                        + ("enabled." if enabled else "disabled.")
                    )
            elif command == "save":
                self._save_live_spectrum(Path(payload), publish_log)
            elif command == "shutter":
                if bool(payload):
                    if not self.probe_out:
                        publish_log("ERROR: Shutter opening refused: probe is not verified out.")
                    else:
                        self.shutter_closed = False
                        publish_log("Simulated shutter opened.")
                else:
                    self.shutter_closed = True
                    publish_log("Simulated shutter closed.")
                publish_snapshot(self.snapshot())
            elif command == "move_stage":
                stage, position = payload
                self._perform_stage_move(stage, position)
                publish_snapshot(self.snapshot())
                publish_log(f"Alignment move: {stage} → {position:g} deg.")
            elif command == "set_power":
                target_power_mw = float(payload)
                self._perform_set_power(target_power_mw)
                publish_snapshot(self.snapshot())
                publish_log(
                    f"Simulated target power set to {target_power_mw:g} mW; "
                    "shutter closed and probe verified out."
                )
            elif command == "measure_power":
                value = self._perform_measure_power()
                publish_snapshot(self.snapshot())
                publish_log(
                    f"Simulated incident power measured: {value:.3f} mW; "
                    "shutter closed and probe verified out."
                )
        return integration_time_ms, averages

    def _perform_stage_move(self, stage: str, position: float) -> None:
        if stage not in {"waveplate", "sample"}:
            raise ValueError(f"Unknown simulated rotation stage: {stage}")
        if not np.isfinite(position):
            raise ValueError("Stage position must be finite.")
        if stage == "waveplate":
            self.waveplate_angle_deg = float(position)
            self.beam_power_mw = self._power_for_waveplate(position)
        else:
            self.sample_angle_deg = float(position)

    def _perform_set_power(self, target_power_mw: float) -> None:
        target = float(target_power_mw)
        if not np.isfinite(target) or target <= 0:
            raise ValueError("Target power must be finite and positive.")
        self.shutter_closed = True
        self.probe_out = False
        self.waveplate_angle_deg = (target - 1.0) / 0.12
        self.beam_power_mw = target
        self.shutter_closed = True
        self.probe_out = True

    def _perform_measure_power(self) -> float:
        self.shutter_closed = True
        self.probe_out = False
        self.shutter_closed = False
        value = self._power_for_waveplate(self.waveplate_angle_deg)
        self.beam_power_mw = value
        self.shutter_closed = True
        self.probe_out = True
        return value

    @staticmethod
    def _power_for_waveplate(angle_deg: float) -> float:
        return max(0.05, 1.0 + 0.12 * float(angle_deg))

    def _live_spectrum(
        self,
        *,
        integration_time_ms: float,
        averages: int,
        frame: int,
    ) -> Spectrum:
        wavelengths = np.linspace(350.0, 850.0, 2048)
        drift = 2.5 * np.sin(frame / 35.0)
        amplitude = 25_000.0 * (integration_time_ms / 10.0)
        peak = amplitude * np.exp(
            -0.5 * ((wavelengths - (525.0 + drift)) / 10.0) ** 2
        )
        secondary = 0.28 * amplitude * np.exp(
            -0.5 * ((wavelengths - 650.0) / 18.0) ** 2
        )
        noise_scale = 160.0 / np.sqrt(averages)
        deterministic_noise = noise_scale * np.sin(
            wavelengths / 3.7 + frame * 0.41
        )
        intensities = np.maximum(
            0.0,
            450.0 * integration_time_ms / 10.0
            + peak
            + secondary
            + deterministic_noise,
        )
        return Spectrum(
            wavelengths=wavelengths,
            intensities=intensities,
            integration_time_ms=integration_time_ms,
            serial="SIM-OCEAN-SR",
            averages=averages,
        )

    def _apply_live_background(self, spectrum: Spectrum) -> Spectrum:
        background = self._live_background
        if not self._live_background_enabled or background is None:
            return spectrum.copy()
        if spectrum.wavelengths.shape != background.wavelengths.shape or not np.allclose(
            spectrum.wavelengths,
            background.wavelengths,
        ):
            self._live_background_enabled = False
            return spectrum.copy()
        scale = spectrum.integration_time_ms / background.integration_time_ms
        displayed = spectrum.copy()
        displayed.intensities = (
            np.asarray(spectrum.intensities, dtype=float)
            - np.asarray(background.intensities, dtype=float) * scale
        )
        return displayed

    def _save_live_spectrum(self, output_directory: Path, publish_log: LogCallback) -> None:
        spectrum = self._live_display_spectrum
        if spectrum is None:
            publish_log("No displayed live spectrum is available to save.")
            return
        output_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = output_directory / f"live_spectrum_{timestamp}.npz"
        np.savez_compressed(
            path,
            wavelengths=np.asarray(spectrum.wavelengths, dtype=float),
            intensities=np.asarray(spectrum.intensities, dtype=float),
            integration_time_ms=np.asarray(spectrum.integration_time_ms, dtype=float),
            serial=np.asarray(spectrum.serial, dtype=str),
            averages=np.asarray(spectrum.averages, dtype=int),
            dark_corrected=np.asarray(spectrum.dark_corrected, dtype=bool),
            nonlinearity_corrected=np.asarray(
                spectrum.nonlinearity_corrected, dtype=bool
            ),
            timestamp=np.asarray(spectrum.timestamp, dtype=float),
            background_applied=np.asarray(
                self._live_background_enabled and self._live_background is not None,
                dtype=bool,
            ),
            simulation=np.asarray(True, dtype=bool),
        )
        publish_log(f"Live spectrum saved: {path}")

    def _clear_live_commands(self) -> None:
        while True:
            try:
                self._live_commands.get_nowait()
            except Empty:
                return

    def run_scan(
        self,
        request: ScanRequest,
        *,
        publish_snapshot: SnapshotCallback,
        publish_measurement: MeasurementCallback,
        publish_log: LogCallback,
    ) -> bool:
        """Run a short deterministic scan and return True if completed."""

        self._require_idle()
        self.busy = True
        self._cancel.clear()
        completed = 0
        publish_snapshot(self.snapshot())
        publish_log(
            f"Simulation started: {request.total_spectra} spectra requested."
        )
        try:
            with DataWriter(
                output_directory=request.output_directory,
                experiment_name=request.experiment_name,
            ) as writer:
                writer.save_metadata(
                    config={
                        "simulation": True,
                        "sample_angles_deg": list(request.sample_angles_deg),
                        "intensity_values": list(request.intensity_values),
                        "intensity_mode": request.intensity_mode,
                        "spectra_per_point": request.spectra_per_point,
                        "integration_time_ms": request.integration_time_ms,
                        "averages": request.averages,
                        "acquire_background": request.acquire_background,
                    },
                    hardware_info={
                        device.key: {
                            "name": device.name,
                            "identity": device.identity,
                            "simulation": True,
                        }
                        for device in self.snapshot().devices
                    },
                    extra_metadata={
                        "simulation": True,
                        "operator_notes": request.notes,
                    },
                )
                if request.acquire_background:
                    writer.save_background(
                        self._background_spectrum(request),
                        name="pre_scan_dark",
                        metadata={
                            "simulation": True,
                            "shutter_state": "closed",
                        },
                    )
                publish_log(f"Saving simulated data to {writer.experiment_directory}")

                for intensity_index, intensity_value in enumerate(
                    request.intensity_values
                ):
                    if request.intensity_mode == "target_power_mw":
                        self.beam_power_mw = float(intensity_value)
                        self.waveplate_angle_deg = 4.0 * intensity_index
                    else:
                        self.waveplate_angle_deg = float(intensity_value)
                        self.beam_power_mw = 1.0 + 0.12 * self.waveplate_angle_deg
                    publish_snapshot(self.snapshot())

                    for sample_angle in request.sample_angles_deg:
                        self.sample_angle_deg = float(sample_angle)
                        for replicate_index in range(
                            1, request.spectra_per_point + 1
                        ):
                            if self._cancel.is_set():
                                publish_log(
                                    "Cancellation accepted before the next spectrum; "
                                    "completed spectra remain saved."
                                )
                                return False
                            self.probe_out = True
                            self.shutter_closed = False
                            measurement = self._measurement(
                                request=request,
                                replicate_index=replicate_index,
                            )
                            self.shutter_closed = True
                            writer.save_result(measurement)
                            completed += 1
                            publish_measurement(
                                measurement,
                                completed,
                                request.total_spectra,
                            )
                            publish_snapshot(self.snapshot())
                            time.sleep(0.025)
            publish_log("Simulation completed successfully.")
            return True
        finally:
            self.shutter_closed = True
            self.probe_out = True
            self.busy = False
            publish_snapshot(self.snapshot())

    def run_calibration(
        self,
        request,
        *,
        publish_snapshot,
        publish_point,
        publish_log,
    ) -> dict:
        from tools.waveplate_power_control import (
            WaveplatePowerPoint,
            _save_scan_csv,
            identify_monotonic_branch,
            plot_waveplate_power_map,
        )
        from experiments.waveplate_calibration import fit_malus_calibration

        self._require_idle()
        self.busy = True
        self._cancel.clear()
        starting_angle = self.waveplate_angle_deg
        directory = Path(request.output_directory) / datetime.now().strftime(
            "simulation_calibration_%Y%m%d_%H%M%S"
        )
        directory.mkdir(parents=True, exist_ok=False)
        points = []
        publish_snapshot(self.snapshot())
        try:
            for index, angle in enumerate(request.angles_deg, start=1):
                if self._cancel.is_set():
                    raise RuntimeError("Calibration cancelled at a safe point.")
                self.waveplate_angle_deg = float(angle)
                power = 4.0 + 0.2 * (float(angle) - request.start_deg)
                points.append(WaveplatePowerPoint(float(angle), power))
                _save_scan_csv(directory / "waveplate_power.csv", points)
                publish_point(float(angle), power, index, len(request.angles_deg))
                publish_log(f"Simulated calibration {index}/{len(request.angles_deg)}.")
            branch = identify_monotonic_branch(
                points, noise_tolerance_mw=request.noise_tolerance_mw
            )
            calibration = fit_malus_calibration(
                [point.angle_deg for point in points],
                [point.power_mw for point in points],
                waveplate_min_deg=branch.start_deg,
                waveplate_max_deg=branch.stop_deg,
                monotonic_direction=branch.direction,
                source=str(directory / "waveplate_power.csv"),
            )
            calibration_path = directory / "malus_calibration.json"
            calibration.save(calibration_path)
            plot_waveplate_power_map(
                points, branch=branch, output_path=directory / "waveplate_power_map.png"
            )
            return {
                "directory": str(directory),
                "calibration_path": str(calibration_path),
                "branch_min_deg": branch.start_deg,
                "branch_max_deg": branch.stop_deg,
                "direction": branch.direction,
                "point_count": len(points),
            }
        finally:
            self.waveplate_angle_deg = starting_angle
            self.shutter_closed = True
            self.probe_out = True
            self.busy = False
            publish_snapshot(self.snapshot())

    @staticmethod
    def _background_spectrum(request: ScanRequest) -> Spectrum:
        wavelengths = np.linspace(350.0, 850.0, 1024)
        return Spectrum(
            wavelengths=wavelengths,
            intensities=np.full_like(wavelengths, 120.0),
            integration_time_ms=request.integration_time_ms,
            serial="SIM-OCEAN-SR",
            averages=request.averages,
        )

    def _measurement(
        self,
        *,
        request: ScanRequest,
        replicate_index: int,
    ) -> Measurement:
        wavelengths = np.linspace(350.0, 850.0, 1024)
        angle_factor = 0.35 + np.cos(np.deg2rad(2 * self.sample_angle_deg)) ** 2
        power = float(self.beam_power_mw or 0.0)
        peak = 475.0 + 0.08 * self.sample_angle_deg
        signal = 700.0 + 2500.0 * angle_factor * max(power, 0.5)
        harmonic = signal * np.exp(-0.5 * ((wavelengths - peak) / 7.0) ** 2)
        ripple = 25.0 * np.sin(wavelengths / 8.0 + replicate_index)
        intensities = np.maximum(0.0, 120.0 + harmonic + ripple)
        spectrum = Spectrum(
            wavelengths=wavelengths,
            intensities=intensities,
            integration_time_ms=request.integration_time_ms,
            serial="SIM-OCEAN-SR",
            averages=request.averages,
        )
        measurement = Measurement(
            timestamp=time.time(),
            waveplate_angle_deg=self.waveplate_angle_deg,
            sample_angle_deg=self.sample_angle_deg,
            power_mw=self.beam_power_mw,
            target_power_mw=(
                self.beam_power_mw
                if request.intensity_mode == "target_power_mw"
                else None
            ),
            spectrum=spectrum,
            metadata={
                "simulation": True,
                "replicate": {
                    "index": replicate_index,
                    "count": request.spectra_per_point,
                },
            },
        )
        measurement.compute_statistics()
        return measurement

    def _require_connected(self) -> None:
        if not self.connected:
            raise RuntimeError("Simulated hardware is not connected.")

    def _require_not_busy(self) -> None:
        if self.busy:
            raise RuntimeError("Another simulated hardware operation is active.")

    def _require_device_key(self, key: str) -> None:
        if key not in self._device_connections:
            raise ValueError(f"Unknown simulated device: {key}")

    def _require_idle(self) -> None:
        self._require_connected()
        if self.busy:
            raise RuntimeError("Another simulated hardware operation is active.")

    def set_operator_settings(self, settings: dict[str, float]) -> None:
        """Accept shared GUI settings; simulation has no motion readback error."""

        return None
