"""Spectrometer-only campaign backend with lazy real-driver construction."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from queue import Empty, SimpleQueue
import threading
import time
from typing import Callable, Protocol
from uuid import uuid4

import numpy as np

from acquisition.acquisition import Acquisition
from analysis.measurement import Measurement
from data.data_writer import DataWriter
from data.power_measurement import PowerMeasurementAttempt
from experiments.power_targeting import TargetPowerController
from experiments.waveplate_calibration import MalusLawCalibration
from gui.state import ConnectionState, DeviceSnapshot, GuiSnapshot, LiveViewRequest
from hardware.config import POWER_METER, POWER_METER_STAGE, SAMPLE_STAGE, SHUTTER, SPECTROMETER, WAVEPLATE
from hardware.devices.spectrometer.spectrum import Spectrum


class SpectrometerProtocol(Protocol):
    serial: str
    integration_time_ms: float

    @property
    def connected(self) -> bool: ...

    def connect(self) -> None: ...

    def disconnect(self) -> None: ...

    def set_integration_time(self, integration_time_ms: float) -> None: ...

    def acquire(self, *, averages: int = 1) -> Spectrum: ...


class RotationStageProtocol(Protocol):
    serial: str
    connected: bool
    position: float
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def move_to(self, angle_deg: float) -> None: ...
    def stop(self) -> None: ...


class ShutterProtocol(Protocol):
    serial: str
    connected: bool
    is_closed: bool
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def close(self) -> None: ...
    def open(self) -> None: ...


class PIStageProtocol(Protocol):
    serial: str
    connected: bool
    position_mm: float
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def prepare_for_closed_loop(self): ...
    def move_absolute_mm(self, target_position_mm: float): ...
    def halt(self) -> None: ...
    def refresh_snapshot(self): ...
    def reference_to_switch(self, **kwargs): ...


class PowerMeterProtocol(Protocol):
    connected: bool
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def acquire_trace(self, duration_s: float, *, poll_interval_s: float): ...
    def info(self) -> dict: ...


class PIReferenceRequired(RuntimeError):
    """PI connected successfully but requires an operator-approved FRF move."""


class SpectrometerCampaignBackend:
    """Own the staged subset of real hardware enabled in the campaign GUI."""

    ROTATION_READBACK_TOLERANCE_DEG = 0.05

    DEVICE_NAMES = (
        ("waveplate", "Waveplate stage"),
        ("sample", "Sample stage"),
        ("shutter", "Beam shutter"),
        ("spectrometer", "Ocean SR spectrometer"),
        ("power_meter_stage", "Power-probe stage"),
        ("power_meter", "Ophir power meter"),
    )

    def __init__(
        self,
        *,
        spectrometer_factory: Callable[[str, float], SpectrometerProtocol] | None = None,
        stage_factory: Callable[[str, str, float | None], RotationStageProtocol] | None = None,
        shutter_factory: Callable[[str, str], ShutterProtocol] | None = None,
        pi_stage_factory: Callable[[str], PIStageProtocol] | None = None,
        power_meter_factory: Callable[[str], PowerMeterProtocol] | None = None,
        default_serial: str = SPECTROMETER.serial,
        rotation_readback_tolerance_deg: float = ROTATION_READBACK_TOLERANCE_DEG,
        power_trace_directory: Path = Path("results/power_measurements"),
    ) -> None:
        self.rotation_readback_tolerance_deg = self._validate_rotation_tolerance(
            rotation_readback_tolerance_deg
        )
        self.serials = {
            "waveplate": WAVEPLATE.serial,
            "sample": SAMPLE_STAGE.serial,
            "shutter": SHUTTER.serial,
            "spectrometer": str(default_serial),
            "power_meter_stage": POWER_METER_STAGE.serial,
            "power_meter": POWER_METER.controller_serial,
        }
        self.busy = False
        self._spectrometer_factory = spectrometer_factory or self._make_ocean_sr
        self._stage_factory = stage_factory or self._make_rotation_stage
        self._shutter_factory = shutter_factory or self._make_shutter
        self._pi_stage_factory = pi_stage_factory or self._make_pi_stage
        self._power_meter_factory = power_meter_factory or self._make_power_meter
        self._spectrometer: SpectrometerProtocol | None = None
        self._stages: dict[str, RotationStageProtocol] = {}
        self._shutter: ShutterProtocol | None = None
        self._pi_stage: PIStageProtocol | None = None
        self._power_meter: PowerMeterProtocol | None = None
        self._beam_power_mw: float | None = None
        self.power_trace_directory = Path(power_trace_directory)
        self.power_measurement_duration_s = 10.0
        self.power_settle_time_s = 3.0
        self.power_poll_interval_s = 0.1
        self.probe_in_position_mm = float(POWER_METER_STAGE.in_position_mm)
        self.probe_out_position_mm = float(POWER_METER_STAGE.out_position_mm)
        self.probe_position_tolerance_mm = float(POWER_METER_STAGE.position_tolerance_mm)
        self._live_stop = threading.Event()
        self._live_commands: SimpleQueue[tuple[str, object]] = SimpleQueue()
        self._raw_spectrum: Spectrum | None = None
        self._display_spectrum: Spectrum | None = None
        self._background: Spectrum | None = None
        self._background_enabled = False
        self._motion_cancel = threading.Event()

    @staticmethod
    def _make_ocean_sr(serial: str, integration_time_ms: float):
        # Importing this module initialises SeaBreeze, so keep it behind the
        # explicit operator connection action rather than GUI startup/mode change.
        from hardware.devices.spectrometer.ocean_sr import OceanSR

        return OceanSR(
            serial=serial,
            integration_time_ms=integration_time_ms,
        )

    @staticmethod
    def _make_rotation_stage(serial: str, name: str, maximum_velocity: float | None):
        from hardware.devices.rotation import RotationStage
        return RotationStage(
            serial=serial, name=name, maximum_velocity_deg_s=maximum_velocity
        )

    @staticmethod
    def _make_shutter(serial: str, name: str):
        from hardware.devices.shutter import BeamShutter
        return BeamShutter(serial=serial, name=name)

    @staticmethod
    def _make_pi_stage(serial: str):
        from dataclasses import replace
        from hardware.devices.linear import PILinearStage
        return PILinearStage.from_project_config(
            replace(POWER_METER_STAGE, serial=str(serial))
        )

    @staticmethod
    def _make_power_meter(serial: str):
        from hardware.devices.power_meter import OphirJunoPowerMeter
        return OphirJunoPowerMeter(
            controller_serial=str(serial),
            sensor_serial=POWER_METER.sensor_serial,
            wavelength_name=">800",
            fixed_range_name="30.0mW",
            name=POWER_METER.name,
        )

    @property
    def serial(self) -> str:
        return self.serials["spectrometer"]

    def set_operator_settings(self, settings: dict[str, float]) -> None:
        self.rotation_readback_tolerance_deg = self._validate_rotation_tolerance(
            settings["rotation_readback_tolerance_deg"]
        )
        in_position = float(settings["probe_in_position_mm"])
        out_position = float(settings["probe_out_position_mm"])
        lower = float(POWER_METER_STAGE.application_min_mm)
        upper = float(POWER_METER_STAGE.application_max_mm)
        if not lower <= in_position <= upper or not lower <= out_position <= upper:
            raise ValueError(f"Probe positions must be within [{lower}, {upper}] mm.")
        if np.isclose(in_position, out_position, rtol=0.0, atol=self.probe_position_tolerance_mm):
            raise ValueError("Probe insertion and retraction positions must be distinct.")
        self.probe_in_position_mm = in_position
        self.probe_out_position_mm = out_position
        self.power_measurement_duration_s = float(settings["power_measurement_duration_s"])
        self.power_settle_time_s = float(settings["power_settle_time_s"])
        self.power_poll_interval_s = float(settings["power_poll_interval_s"])
        if self.power_measurement_duration_s <= 0 or self.power_settle_time_s < 0:
            raise ValueError("Power duration must be positive and settling non-negative.")
        if self.power_poll_interval_s <= 0:
            raise ValueError("Power polling interval must be positive.")

    @property
    def connected(self) -> bool:
        return bool(self._spectrometer and self._spectrometer.connected)

    def snapshot(self) -> GuiSnapshot:
        devices = []
        for key, name in self.DEVICE_NAMES:
            available = key in self.serials
            connected = self._device_connected(key)
            devices.append(
                DeviceSnapshot(
                    key=key,
                    name=name,
                    connection=(
                        ConnectionState.CONNECTED
                        if connected
                        else ConnectionState.DISCONNECTED
                    ),
                    identity=self.serials[key] if available else "Not enabled",
                    value=(
                        f"{self._current_integration_time():g} ms"
                        if key == "spectrometer" and connected
                        else f"{self._stages[key].position:.4f} deg"
                        if key in self._stages and connected
                        else f"{self._pi_stage.position_mm:.4f} mm"
                        if key == "power_meter_stage" and connected
                        else f"{self._beam_power_mw:.6g} mW"
                        if key == "power_meter" and connected and self._beam_power_mw is not None
                        else "CLOSED"
                        if key == "shutter" and connected and self._shutter_closed()
                        else "--"
                    ),
                    detail=(
                        f"Enabled; sensor {POWER_METER.sensor_serial}; >800; 30.0mW"
                        if key == "power_meter" and available
                        else "Enabled hardware milestone"
                        if available
                        else "Disabled until its dedicated commissioning milestone"
                    ),
                    available=available,
                    required=available,
                )
            )
        return GuiSnapshot(
            devices=tuple(devices),
            shutter_closed=self._shutter_closed() if self._device_connected("shutter") else None,
            probe_out=self._probe_out_state(),
            beam_power_mw=self._beam_power_mw,
            busy=self.busy,
            simulation=False,
        )

    def connect_all(self, publish, serials: dict[str, str] | None = None) -> None:
        requested = serials or {}
        connected_here = []
        try:
            for key in ("shutter", "power_meter_stage", "power_meter", "waveplate", "sample", "spectrometer"):
                if not self._device_connected(key):
                    self.connect_device(key, requested.get(key, self.serials[key]), publish)
                    connected_here.append(key)
        except PIReferenceRequired:
            # Keep the PI controller and already established shutter interlock
            # connected so the approved recovery workflow can proceed safely.
            raise
        except Exception:
            for key in reversed(connected_here):
                try:
                    self._disconnect_device(key)
                except Exception:
                    pass
            publish(self.snapshot())
            raise

    def connect_device(self, key: str, serial: str, publish) -> None:
        if key not in self.serials:
            raise RuntimeError(
                f"{key} is disabled in the alignment-hardware milestone."
            )
        if self.busy:
            raise RuntimeError("Cannot connect while live acquisition is active.")
        serial = str(serial).strip()
        if not serial:
            raise ValueError(f"{key} serial/identity must not be empty.")
        if self._device_connected(key):
            if serial != self.serials[key]:
                raise RuntimeError(
                    f"Disconnect {key} before changing its serial/identity."
                )
            publish(self.snapshot())
            return
        self.serials[key] = serial
        if key == "spectrometer":
            device = self._spectrometer_factory(serial, 10.0)
        elif key == "shutter":
            device = self._shutter_factory(serial, SHUTTER.name)
        elif key == "power_meter_stage":
            device = self._pi_stage_factory(serial)
        elif key == "power_meter":
            device = self._power_meter_factory(serial)
        else:
            config = WAVEPLATE if key == "waveplate" else SAMPLE_STAGE
            device = self._stage_factory(serial, config.name, config.maximum_velocity_deg_s)
        try:
            device.connect()
            if key == "shutter":
                device.close()
                if not device.is_closed:
                    raise RuntimeError("Shutter did not verify closed after connection.")
            elif key == "power_meter_stage":
                snapshot = device.refresh_snapshot()
                if snapshot.referenced is not True:
                    self._pi_stage = device
                    publish(self.snapshot())
                    raise PIReferenceRequired(
                        "PI axis 1 connected but is not referenced. An operator-approved "
                        "reference-switch move is required."
                    )
                device.prepare_for_closed_loop()
        except Exception:
            if key == "power_meter_stage" and self._pi_stage is device:
                raise
            try:
                device.disconnect()
            except Exception:
                pass
            raise
        if key == "spectrometer":
            self._spectrometer = device
        elif key == "shutter":
            self._shutter = device
        elif key == "power_meter_stage":
            self._pi_stage = device
        elif key == "power_meter":
            self._power_meter = device
        else:
            self._stages[key] = device
        publish(self.snapshot())

    def disconnect_device(self, key: str, publish) -> None:
        if key not in self.serials:
            raise RuntimeError(f"{key} is not owned by this hardware milestone.")
        if self.busy:
            raise RuntimeError("Stop live acquisition before disconnecting.")
        self._disconnect_device(key)
        publish(self.snapshot())

    def safe_disconnect(self, publish) -> None:
        if self.busy:
            raise RuntimeError("Stop live acquisition before disconnecting.")
        self.safe_state(publish)
        for key in ("spectrometer", "sample", "waveplate", "power_meter", "power_meter_stage", "shutter"):
            self._disconnect_device(key)
        publish(self.snapshot())

    def safe_state(self, publish) -> None:
        self.request_live_stop()
        if self._shutter and self._shutter.connected:
            self._shutter.close()
            if not self._shutter.is_closed:
                raise RuntimeError("Shutter close command could not be verified.")
        for stage in self._stages.values():
            if stage.connected:
                stage.stop()
        if self._pi_stage and self._pi_stage.connected:
            self._pi_stage.halt()
        publish(self.snapshot())

    def close_shutter(self, publish) -> None:
        if not self._shutter or not self._shutter.connected:
            raise RuntimeError("Beam shutter is not connected.")
        self._shutter.close()
        if not self._shutter.is_closed:
            raise RuntimeError("Shutter close command could not be verified.")
        publish(self.snapshot())

    def open_shutter(self, publish, *, allow_unverified_probe: bool = False) -> None:
        if not self._shutter or not self._shutter.connected:
            raise RuntimeError("Beam shutter is not connected.")
        if self.busy and allow_unverified_probe:
            raise RuntimeError(
                "Unsafe shutter override is refused during live acquisition."
            )
        if self.snapshot().probe_out is not True and not allow_unverified_probe:
            raise RuntimeError(
                "Shutter opening refused: the power probe is not live-verified out."
            )
        self._shutter.open()
        if self._shutter.is_closed:
            raise RuntimeError("Shutter open command could not be verified.")
        publish(self.snapshot())

    def move_stage(self, stage: str, position: float, publish) -> None:
        if stage not in {"waveplate", "sample"} or stage not in self._stages:
            raise RuntimeError(f"{stage} rotation stage is not connected.")
        if not self._shutter or not self._shutter.connected:
            raise RuntimeError("Connect the shutter before commanding stage motion.")
        self._shutter.close()
        if not self._shutter.is_closed:
            raise RuntimeError("Stage motion refused because shutter-closed was not verified.")
        self._stages[stage].move_to(float(position))
        observed = float(self._stages[stage].position)
        publish(self.snapshot())
        if not np.isfinite(observed) or not np.isclose(
            observed,
            float(position),
            rtol=0.0,
            atol=self.rotation_readback_tolerance_deg,
        ):
            raise RuntimeError(
                f"{stage} move verification failed: requested {float(position):.4f} deg, "
                f"but live position readback is {observed:.4f} deg. Check that the "
                "mount is connected to its controller before retrying. "
                f"Tolerance is {self.rotation_readback_tolerance_deg:g} deg."
            )

    def home_rotation_stage(self, stage: str, publish) -> None:
        if stage not in self._stages:
            raise RuntimeError(f"{stage} rotation stage is not connected.")
        self.close_shutter(lambda snapshot: None)
        self._stages[stage].home()
        observed = float(self._stages[stage].position)
        publish(self.snapshot())
        if not np.isfinite(observed) or not np.isclose(
            observed, 0.0, rtol=0.0, atol=self.rotation_readback_tolerance_deg
        ):
            raise RuntimeError(
                f"{stage} home verification failed: live position is {observed:.4f} deg."
            )

    def reference_pi_stage(self, publish) -> None:
        if not self._pi_stage or not self._pi_stage.connected:
            raise RuntimeError("PI stage is not connected.")
        self.close_shutter(lambda snapshot: None)
        self._motion_cancel.clear()
        self._pi_stage.reference_to_switch(
            cancel_requested=self._motion_cancel.is_set
        )
        self._pi_stage.prepare_for_closed_loop()
        publish(self.snapshot())

    def set_probe(self, *, out: bool, publish) -> None:
        target = self.probe_out_position_mm if out else self.probe_in_position_mm
        self.move_probe_absolute(target, publish)

    def move_probe_absolute(self, position_mm: float, publish) -> None:
        if self.busy:
            raise RuntimeError("Stop live acquisition before moving the PI stage.")
        if not self._pi_stage or not self._pi_stage.connected:
            raise RuntimeError("PI power-probe stage is not connected.")
        self.close_shutter(lambda snapshot: None)
        self._pi_stage.move_absolute_mm(float(position_mm))
        publish(self.snapshot())

    def set_power(self, target_power_mw: float, publish) -> None:
        raise RuntimeError("Power control is disabled in alignment hardware mode.")

    def measure_power(self, publish) -> float:
        if not self._shutter or not self._shutter.connected:
            raise RuntimeError("Beam shutter is not connected.")
        if not self._pi_stage or not self._pi_stage.connected:
            raise RuntimeError("PI probe stage is not connected.")
        if not self._power_meter or not self._power_meter.connected:
            raise RuntimeError("Ophir power meter is not connected.")
        if self.busy:
            raise RuntimeError("Another hardware operation is active.")
        from hardware.power_probe import RetractablePowerProbe
        self.busy = True
        publish(self.snapshot())
        try:
            probe = RetractablePowerProbe(
                shutter=self._shutter,
                insertion_stage=self._pi_stage,
                power_meter=self._power_meter,
                in_position_mm=self.probe_in_position_mm,
                out_position_mm=self.probe_out_position_mm,
                position_tolerance_mm=self.probe_position_tolerance_mm,
            )
            trace = probe.acquire_trace(
                duration_s=self.power_measurement_duration_s,
                settle_time_s=self.power_settle_time_s,
                poll_interval_s=self.power_poll_interval_s,
            )
            self._save_power_trace(trace)
            statistics = trace.statistics
            unsafe_samples = [sample for sample in trace.samples if not sample.valid_for_statistics]
            positive_mw = [
                float(sample.power_w) * 1000.0
                for sample in trace.samples
                if sample.power_w is not None and np.isfinite(sample.power_w) and sample.power_w > 0
            ]
            if unsafe_samples:
                raise RuntimeError(
                    f"Ophir trace contains {len(unsafe_samples)} unsafe/invalid sample(s); "
                    "no mean power was accepted. Raw trace was saved."
                )
            if positive_mw and max(positive_mw) > 20.0:
                raise RuntimeError(
                    f"Ophir raw sample {max(positive_mw):.6g} mW exceeds the 20 mW "
                    "campaign ceiling. Raw trace was saved."
                )
            mean = statistics.arithmetic_mean_power_mw
            if mean is None:
                raise RuntimeError("Ophir trace has no valid positive samples; raw trace was saved.")
            self._beam_power_mw = float(mean)
            return self._beam_power_mw
        finally:
            self.busy = False
            publish(self.snapshot())

    def run_scan(
        self,
        request,
        *,
        publish_snapshot,
        publish_measurement,
        publish_log,
    ) -> bool:
        """Run one guarded, angle-controlled scan using the connected devices."""

        missing = [key for key, _ in self.DEVICE_NAMES if not self._device_connected(key)]
        if missing:
            raise RuntimeError("Connect all scan devices first: " + ", ".join(missing))
        if self.busy:
            raise RuntimeError("Another hardware operation is active.")
        if self._probe_out_state() is not True:
            raise RuntimeError(
                "Scan refused: the PI power probe is not live-verified at its "
                "configured retraction position."
            )

        spectrometer = self._require_spectrometer()
        assert self._shutter is not None
        self.busy = True
        self._motion_cancel.clear()
        completed = 0
        publish_snapshot(self.snapshot())
        acquisition = Acquisition(
            spectrometer=spectrometer,
            shutter=self._shutter,
            before_open=self._require_probe_out_for_acquisition,
        )
        try:
            spectrometer.set_integration_time(float(request.integration_time_ms))
            with DataWriter(
                output_directory=request.output_directory,
                experiment_name=request.experiment_name,
            ) as writer:
                writer.save_metadata(
                    config={
                        "simulation": False,
                        "sample_angles_deg": list(request.sample_angles_deg),
                        "waveplate_angles_deg": list(request.intensity_values),
                        "intensity_mode": request.intensity_mode,
                        "spectra_per_point": request.spectra_per_point,
                        "integration_time_ms": request.integration_time_ms,
                        "averages": request.averages,
                        "acquire_background": request.acquire_background,
                        "power_measurement_duration_s": self.power_measurement_duration_s,
                        "power_settle_time_s": self.power_settle_time_s,
                        "power_poll_interval_s": self.power_poll_interval_s,
                        "maximum_allowed_power_mw": 20.0,
                        "waveplate_min_deg": request.waveplate_min_deg,
                        "waveplate_max_deg": request.waveplate_max_deg,
                        "monotonic_direction": request.monotonic_direction,
                        "target_tolerance_mw": request.target_tolerance_mw,
                        "target_maximum_iterations": request.target_maximum_iterations,
                        "target_minimum_angle_step_deg": request.target_minimum_angle_step_deg,
                        "power_calibration_path": request.power_calibration_path,
                    },
                    hardware_info={
                        device.key: {
                            "name": device.name,
                            "identity": device.identity,
                            "detail": device.detail,
                        }
                        for device in self.snapshot().devices
                    },
                    extra_metadata={
                        "simulation": False,
                        "operator_notes": request.notes,
                        "gui_scan": True,
                    },
                )
                publish_log(f"Saving hardware scan to {writer.experiment_directory}")
                if request.acquire_background:
                    background = acquisition.acquire_dark(averages=request.averages)
                    self._validate_spectrum(background)
                    writer.save_background(
                        background,
                        name="pre_scan_dark",
                        metadata={"shutter_state": "closed", "simulation": False},
                    )
                    publish_log("Shutter-closed pre-scan background saved.")

                for intensity_value in request.intensity_values:
                    if self._motion_cancel.is_set():
                        publish_log("Cancellation accepted before the next intensity block.")
                        return False
                    target_power_mw = None
                    if request.intensity_mode == "target_power_mw":
                        target_power_mw = float(intensity_value)
                        waveplate_angle, attempt, trace = self._target_power_block(
                            request=request,
                            target_power_mw=target_power_mw,
                            writer=writer,
                            publish_snapshot=publish_snapshot,
                            publish_log=publish_log,
                        )
                    else:
                        waveplate_angle = float(intensity_value)
                        self.move_stage("waveplate", waveplate_angle, publish_snapshot)
                        attempt, trace = self._persist_scan_power_attempt(
                            waveplate_angle=waveplate_angle,
                            writer=writer,
                        )
                    statistics = trace.statistics
                    self._beam_power_mw = statistics.arithmetic_mean_power_mw
                    publish_log(
                        f"Waveplate {waveplate_angle:g} deg: incident power "
                        f"{self._beam_power_mw:.6g} mW; raw trace saved."
                    )
                    publish_snapshot(self.snapshot())

                    for sample_angle in request.sample_angles_deg:
                        self.move_stage("sample", sample_angle, publish_snapshot)
                        for replicate_index in range(1, request.spectra_per_point + 1):
                            if self._motion_cancel.is_set():
                                publish_log(
                                    "Cancellation accepted before the next spectrum; "
                                    "completed measurements remain saved."
                                )
                                return False
                            spectrum = acquisition.acquire(averages=request.averages)
                            self._validate_spectrum(spectrum)
                            measurement = Measurement(
                                timestamp=time.time(),
                                waveplate_angle_deg=float(waveplate_angle),
                                sample_angle_deg=float(sample_angle),
                                power_mw=statistics.arithmetic_mean_power_mw,
                                target_power_mw=target_power_mw,
                                power_std_mw=statistics.population_standard_deviation_mw,
                                power_rms_mw=statistics.absolute_root_mean_square_power_mw,
                                power_measurement_duration_s=trace.elapsed_duration_s,
                                power_measurement_id=attempt.attempt_id,
                                power_trace_id=trace.trace_id,
                                power_measurement_status=attempt.status,
                                power_valid_sample_count=statistics.valid_sample_count,
                                power_total_sample_count=statistics.total_sample_count,
                                power_trace=trace,
                                spectrum=spectrum,
                                metadata={
                                    "replicate": {
                                        "index": replicate_index,
                                        "count": request.spectra_per_point,
                                    },
                                    "gui_scan": True,
                                },
                            )
                            measurement.compute_statistics()
                            writer.save_result(measurement)
                            completed += 1
                            publish_measurement(measurement, completed, request.total_spectra)
                            publish_snapshot(self.snapshot())
            publish_log("Hardware waveplate-angle scan completed successfully.")
            return True
        finally:
            if self._shutter and self._shutter.connected:
                self._shutter.close()
            self.busy = False
            publish_snapshot(self.snapshot())

    def _persist_scan_power_attempt(
        self,
        *,
        waveplate_angle: float,
        writer,
        trace_source=None,
    ):
        attempt_id = str(uuid4())
        attempted_at = time.time()
        try:
            attempt, trace = self._acquire_scan_power_trace(
                waveplate_angle,
                attempt_id=attempt_id,
                attempted_at=attempted_at,
                trace_source=trace_source,
            )
        except Exception as error:
            failed = PowerMeasurementAttempt(
                attempt_id=attempt_id,
                attempted_at_unix_s=attempted_at,
                waveplate_angle_deg=float(waveplate_angle),
                cadence="per_intensity",
                status="failed",
                fundamental_wavelength_nm=2000.0,
                error=str(error),
                maximum_allowed_power_mw=20.0,
                metadata={"source": "campaign_gui"},
            )
            writer.save_power_attempt(failed)
            raise RuntimeError(
                "Incident-power acquisition failed; the failed attempt was saved "
                "and no spectrum was acquired: " + str(error)
            ) from error
        writer.save_power_attempt(attempt, trace=trace)
        if attempt.status != "measured":
            raise RuntimeError(
                f"Incident-power safety check failed at waveplate "
                f"{waveplate_angle:g} deg: {attempt.error} Raw trace and failed "
                "attempt were saved; no spectrum was acquired."
            )
        return attempt, trace

    def _target_power_block(
        self,
        *,
        request,
        target_power_mw: float,
        writer,
        publish_snapshot,
        publish_log,
    ):
        from hardware.power_probe import RetractablePowerProbe

        assert self._shutter is not None
        assert self._pi_stage is not None
        assert self._power_meter is not None
        probe = RetractablePowerProbe(
            shutter=self._shutter,
            insertion_stage=self._pi_stage,
            power_meter=self._power_meter,
            in_position_mm=self.probe_in_position_mm,
            out_position_mm=self.probe_out_position_mm,
            position_tolerance_mm=self.probe_position_tolerance_mm,
        )
        final: dict[str, object] = {}
        calibration = (
            None
            if request.power_calibration_path is None
            else MalusLawCalibration.load(request.power_calibration_path)
        )
        with probe.measurement_session() as session:
            def measure(angle: float) -> float:
                if self._motion_cancel.is_set():
                    raise RuntimeError("Target-power scan cancelled during feedback.")
                session.prepare_for_motion()
                self.move_stage("waveplate", angle, publish_snapshot)
                attempt, trace = self._persist_scan_power_attempt(
                    waveplate_angle=angle,
                    writer=writer,
                    trace_source=session,
                )
                final["attempt"] = attempt
                final["trace"] = trace
                mean = trace.statistics.arithmetic_mean_power_mw
                assert mean is not None
                publish_log(f"Feedback: {angle:g} deg -> {mean:.6g} mW.")
                return float(mean)

            controller = TargetPowerController(
                measure_power_at_angle=measure,
                waveplate_min_deg=request.waveplate_min_deg,
                waveplate_max_deg=request.waveplate_max_deg,
                monotonic_direction=request.monotonic_direction,
                tolerance_mw=request.target_tolerance_mw,
                maximum_iterations=request.target_maximum_iterations,
                minimum_angle_step_deg=request.target_minimum_angle_step_deg,
                calibration=calibration,
            )
            result = controller.set_target(target_power_mw)
        if self._probe_out_state() is not True:
            raise RuntimeError("Target feedback ended without verified probe retraction.")
        publish_log(
            f"Target {target_power_mw:g} mW reached at {result.waveplate_angle_deg:g} "
            f"deg: {result.achieved_power_mw:.6g} mW."
        )
        return float(result.waveplate_angle_deg), final["attempt"], final["trace"]

    def _acquire_scan_power_trace(
        self,
        waveplate_angle: float,
        *,
        attempt_id: str,
        attempted_at: float,
        trace_source=None,
    ):
        """Acquire and validate the one trace shared by an intensity block."""

        from hardware.power_probe import RetractablePowerProbe

        assert self._shutter is not None
        assert self._pi_stage is not None
        assert self._power_meter is not None
        if trace_source is None:
            trace_source = RetractablePowerProbe(
                shutter=self._shutter,
                insertion_stage=self._pi_stage,
                power_meter=self._power_meter,
                in_position_mm=self.probe_in_position_mm,
                out_position_mm=self.probe_out_position_mm,
                position_tolerance_mm=self.probe_position_tolerance_mm,
            )
        trace = trace_source.acquire_trace(
            duration_s=self.power_measurement_duration_s,
            settle_time_s=self.power_settle_time_s,
            poll_interval_s=self.power_poll_interval_s,
        )
        invalid_count = sum(not sample.valid_for_statistics for sample in trace.samples)
        positive_mw = [
            float(sample.power_w) * 1000.0
            for sample in trace.samples
            if sample.power_w is not None
            and np.isfinite(sample.power_w)
            and sample.power_w > 0
        ]
        error = None
        status = "measured"
        if invalid_count:
            error = f"Trace contains {invalid_count} unsafe/invalid sample(s)."
            status = "unsafe_meter_status"
        elif positive_mw and max(positive_mw) > 20.0:
            error = f"Raw sample {max(positive_mw):.6g} mW exceeds 20 mW ceiling."
            status = "over_limit"
        elif trace.statistics.arithmetic_mean_power_mw is None:
            error = "Trace contains no valid positive power samples."
            status = "invalid"
        attempt = PowerMeasurementAttempt(
            attempt_id=attempt_id,
            attempted_at_unix_s=attempted_at,
            waveplate_angle_deg=float(waveplate_angle),
            cadence="per_intensity",
            status=status,
            fundamental_wavelength_nm=2000.0,
            trace_id=trace.trace_id,
            error=error,
            maximum_allowed_power_mw=20.0,
            metadata={"source": "campaign_gui"},
        )
        return attempt, trace

    def _require_probe_out_for_acquisition(self) -> None:
        if self._probe_out_state() is not True:
            raise RuntimeError(
                "Spectrum acquisition refused: power probe is not live-verified out."
            )

    def request_cancel(self) -> None:
        self._motion_cancel.set()

    def run_calibration(
        self,
        request,
        *,
        publish_snapshot,
        publish_point,
        publish_log,
    ) -> dict:
        """Map a reviewed waveplate interval and save a recommended branch."""

        from hardware.power_probe import RetractablePowerProbe
        from tools.waveplate_power_control import (
            WaveplatePowerPoint,
            _save_scan_csv,
            identify_monotonic_branch,
            plot_waveplate_power_map,
        )
        from experiments.waveplate_calibration import fit_malus_calibration

        for key in ("waveplate", "shutter", "power_meter_stage", "power_meter"):
            if not self._device_connected(key):
                raise RuntimeError(f"Calibration requires connected {key}.")
        if self.busy:
            raise RuntimeError("Another hardware operation is active.")
        assert self._shutter is not None
        assert self._pi_stage is not None
        assert self._power_meter is not None
        stage = self._stages["waveplate"]
        starting_angle = float(stage.position)
        run_directory = Path(request.output_directory) / datetime.now().strftime(
            "calibration_%Y%m%d_%H%M%S"
        )
        run_directory.mkdir(parents=True, exist_ok=False)
        trace_directory = run_directory / "power_measurements"
        points = []
        self.busy = True
        self._motion_cancel.clear()
        publish_snapshot(self.snapshot())
        probe = RetractablePowerProbe(
            shutter=self._shutter,
            insertion_stage=self._pi_stage,
            power_meter=self._power_meter,
            in_position_mm=self.probe_in_position_mm,
            out_position_mm=self.probe_out_position_mm,
            position_tolerance_mm=self.probe_position_tolerance_mm,
        )
        try:
            with probe.measurement_session() as session:
                for index, angle in enumerate(request.angles_deg, start=1):
                    if self._motion_cancel.is_set():
                        raise RuntimeError("Calibration cancelled at a safe point.")
                    session.prepare_for_motion()
                    self.move_stage("waveplate", angle, publish_snapshot)
                    trace = session.acquire_trace(
                        duration_s=self.power_measurement_duration_s,
                        settle_time_s=self.power_settle_time_s,
                        poll_interval_s=self.power_poll_interval_s,
                    )
                    old_directory = self.power_trace_directory
                    try:
                        self.power_trace_directory = trace_directory
                        self._save_power_trace(trace)
                    finally:
                        self.power_trace_directory = old_directory
                    invalid = sum(not sample.valid_for_statistics for sample in trace.samples)
                    positive = [sample.power_mw for sample in trace.samples if sample.power_mw]
                    mean = trace.statistics.arithmetic_mean_power_mw
                    if invalid or mean is None or (positive and max(positive) > 20.0):
                        raise RuntimeError(
                            f"Unsafe power trace at {angle:g} deg; raw trace was saved."
                        )
                    points.append(WaveplatePowerPoint(float(angle), float(mean)))
                    _save_scan_csv(run_directory / "waveplate_power.csv", points)
                    publish_point(float(angle), float(mean), index, len(request.angles_deg))
                    publish_log(f"Calibration {index}/{len(request.angles_deg)}: {angle:g} deg -> {mean:.6g} mW.")
            branch = identify_monotonic_branch(
                points, noise_tolerance_mw=request.noise_tolerance_mw
            )
            calibration = fit_malus_calibration(
                [point.angle_deg for point in points],
                [point.power_mw for point in points],
                waveplate_min_deg=branch.start_deg,
                waveplate_max_deg=branch.stop_deg,
                monotonic_direction=branch.direction,
                source=str(run_directory / "waveplate_power.csv"),
            )
            calibration_path = run_directory / "malus_calibration.json"
            calibration.save(calibration_path)
            plot_path = run_directory / "waveplate_power_map.png"
            plot_waveplate_power_map(points, branch=branch, output_path=plot_path)
            result = {
                "directory": str(run_directory),
                "calibration_path": str(calibration_path),
                "branch_min_deg": branch.start_deg,
                "branch_max_deg": branch.stop_deg,
                "direction": branch.direction,
                "point_count": len(points),
            }
            with (run_directory / "gui_calibration_summary.json").open(
                "w", encoding="utf-8"
            ) as file:
                json.dump(result, file, indent=2)
            publish_log(f"Calibration saved: {run_directory}")
            return result
        finally:
            try:
                self.close_shutter(lambda snapshot: None)
                self.move_stage("waveplate", starting_angle, lambda snapshot: None)
            finally:
                self.busy = False
                publish_snapshot(self.snapshot())

    def request_live_stop(self) -> None:
        self._live_stop.set()

    def queue_live_settings(self, *, integration_time_ms: float, averages: int) -> None:
        self._live_commands.put(
            ("settings", (float(integration_time_ms), int(averages)))
        )

    def queue_live_background_capture(self) -> None:
        self._live_commands.put(("capture_background", None))

    def queue_live_background_enabled(self, enabled: bool) -> None:
        self._live_commands.put(("background_enabled", bool(enabled)))

    def queue_live_save(self, output_directory: Path) -> None:
        self._live_commands.put(("save", Path(output_directory)))

    def queue_live_stage_move(self, stage: str, position: float) -> None:
        self._live_commands.put(("stage_move", (str(stage), float(position))))

    def queue_live_set_power(self, target_power_mw: float) -> None:
        self._live_commands.put(("unsupported", "Power setting"))

    def queue_live_measure_power(self) -> None:
        self._live_commands.put(("unsupported", "Power measurement"))

    def queue_live_shutter(self, *, open_shutter: bool) -> None:
        self._live_commands.put(("shutter", bool(open_shutter)))

    def run_live_view(
        self,
        request: LiveViewRequest,
        *,
        publish_snapshot,
        publish_spectrum,
        publish_log,
    ) -> None:
        spectrometer = self._require_spectrometer()
        if self._probe_out_state() is not True:
            raise RuntimeError(
                "Live spectrum acquisition refused: power probe is not "
                "live-verified at the configured retraction position."
            )
        if self.busy:
            raise RuntimeError("Another spectrometer operation is active.")
        self.busy = True
        self._live_stop.clear()
        self._clear_commands()
        integration_time_ms = float(request.integration_time_ms)
        averages = int(request.averages)
        frame = 0
        publish_snapshot(self.snapshot())
        publish_log(f"Ocean SR live view started ({self.serial}).")
        try:
            spectrometer.set_integration_time(integration_time_ms)
            while not self._live_stop.is_set():
                integration_time_ms, averages = self._process_commands(
                    spectrometer=spectrometer,
                    integration_time_ms=integration_time_ms,
                    averages=averages,
                    publish_log=publish_log,
                )
                raw = spectrometer.acquire(averages=averages)
                self._validate_spectrum(raw)
                self._raw_spectrum = raw
                displayed = self._apply_background(raw)
                self._display_spectrum = displayed
                publish_spectrum(
                    raw,
                    displayed,
                    {
                        "frame": frame,
                        "background_available": self._background is not None,
                        "background_enabled": self._background_enabled,
                        "saturated": raw.maximum >= request.saturation_level,
                    },
                )
                frame += 1
                # acquire() blocks until the detector frame is available. Do
                # not add a second GUI delay: publish every frame immediately.
        except Exception:
            # Treat acquisition/configuration failure as connection loss. Close
            # the handle before reporting the final disconnected snapshot.
            self._disconnect_spectrometer()
            raise
        finally:
            self.busy = False
            publish_snapshot(self.snapshot())
            publish_log("Ocean SR live view stopped.")

    def _process_commands(
        self,
        *,
        spectrometer: SpectrometerProtocol,
        integration_time_ms: float,
        averages: int,
        publish_log,
    ) -> tuple[float, int]:
        while True:
            try:
                command, payload = self._live_commands.get_nowait()
            except Empty:
                break
            if command == "settings":
                candidate_time, candidate_averages = payload
                if candidate_time <= 0 or candidate_averages < 1:
                    publish_log("Ignored invalid live acquisition settings.")
                else:
                    spectrometer.set_integration_time(candidate_time)
                    integration_time_ms = candidate_time
                    averages = candidate_averages
                    publish_log(
                        f"Ocean SR settings: {integration_time_ms:g} ms, "
                        f"{averages} average(s)."
                    )
            elif command == "capture_background":
                if self._raw_spectrum is None:
                    publish_log("No raw spectrum is available for background capture.")
                else:
                    self._background = self._raw_spectrum.copy()
                    self._background_enabled = True
                    publish_log("Live background captured and subtraction enabled.")
            elif command == "background_enabled":
                enabled = bool(payload)
                if enabled and self._background is None:
                    self._background_enabled = False
                    publish_log("Capture a background before enabling subtraction.")
                else:
                    self._background_enabled = enabled
            elif command == "save":
                self._save_displayed_spectrum(Path(payload), publish_log)
            elif command == "stage_move":
                stage, position = payload
                try:
                    self.move_stage(stage, position, lambda snapshot: None)
                except Exception as error:
                    publish_log(f"ERROR: {error}")
                else:
                    publish_log(
                        f"{stage} move verified at "
                        f"{self._stages[stage].position:.4f} deg."
                    )
            elif command == "shutter":
                try:
                    action = self.open_shutter if bool(payload) else self.close_shutter
                    action(lambda snapshot: None)
                except Exception as error:
                    publish_log(f"ERROR: {error}")
                else:
                    publish_log("Shutter opened." if payload else "Shutter closed.")
            elif command == "unsupported":
                publish_log(f"{payload} is disabled in spectrometer-only mode.")
        return integration_time_ms, averages

    def _apply_background(self, spectrum: Spectrum) -> Spectrum:
        background = self._background
        if not self._background_enabled or background is None:
            return spectrum.copy()
        if spectrum.wavelengths.shape != background.wavelengths.shape or not np.allclose(
            spectrum.wavelengths,
            background.wavelengths,
        ):
            self._background_enabled = False
            return spectrum.copy()
        corrected = spectrum.copy()
        corrected.intensities = np.asarray(spectrum.intensities, dtype=float) - (
            np.asarray(background.intensities, dtype=float)
            * spectrum.integration_time_ms
            / background.integration_time_ms
        )
        return corrected

    def _save_displayed_spectrum(self, output_directory: Path, publish_log) -> None:
        spectrum = self._display_spectrum
        if spectrum is None:
            publish_log("No displayed spectrum is available to save.")
            return
        output_directory.mkdir(parents=True, exist_ok=True)
        path = output_directory / (
            "live_spectrum_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".npz"
        )
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
            background_applied=np.asarray(self._background_enabled, dtype=bool),
            simulation=np.asarray(False, dtype=bool),
        )
        publish_log(f"Live spectrum saved: {path}")

    def _disconnect_spectrometer(self) -> None:
        spectrometer = self._spectrometer
        if spectrometer is None:
            return
        try:
            spectrometer.disconnect()
        finally:
            self._spectrometer = None

    def _disconnect_device(self, key: str) -> None:
        if key == "spectrometer":
            self._disconnect_spectrometer()
        elif key == "shutter":
            shutter = self._shutter
            if shutter is not None:
                try:
                    if shutter.connected:
                        shutter.close()
                finally:
                    shutter.disconnect()
                    self._shutter = None
        elif key == "power_meter_stage":
            stage = self._pi_stage
            if stage is not None:
                try:
                    if stage.connected and self._shutter and self._shutter.connected:
                        self.close_shutter(lambda snapshot: None)
                        stage.move_absolute_mm(self.probe_out_position_mm)
                    elif stage.connected:
                        stage.halt()
                finally:
                    stage.disconnect()
                    self._pi_stage = None
        elif key == "power_meter":
            meter = self._power_meter
            if meter is not None:
                meter.disconnect()
                self._power_meter = None
                self._beam_power_mw = None
        else:
            stage = self._stages.pop(key, None)
            if stage is not None:
                try:
                    if stage.connected:
                        stage.stop()
                finally:
                    stage.disconnect()

    def _device_connected(self, key: str) -> bool:
        if key == "spectrometer":
            return self.connected
        if key == "shutter":
            return bool(self._shutter and self._shutter.connected)
        if key == "power_meter_stage":
            return bool(self._pi_stage and self._pi_stage.connected)
        if key == "power_meter":
            return bool(self._power_meter and self._power_meter.connected)
        return bool(key in self._stages and self._stages[key].connected)

    def _shutter_closed(self) -> bool:
        return bool(self._shutter and self._shutter.connected and self._shutter.is_closed)

    def _probe_out_state(self) -> bool | None:
        if not self._pi_stage or not self._pi_stage.connected:
            return None
        position = float(self._pi_stage.position_mm)
        if np.isclose(position, self.probe_out_position_mm, rtol=0.0, atol=self.probe_position_tolerance_mm):
            return True
        return False

    def _save_power_trace(self, trace) -> Path:
        directory = self.power_trace_directory
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"power_trace_{trace.trace_id}.npz"
        np.savez_compressed(
            path,
            raw_values=np.asarray([str(sample.raw_value) for sample in trace.samples], dtype=str),
            raw_timestamps=np.asarray([str(sample.raw_timestamp) for sample in trace.samples], dtype=str),
            raw_statuses=np.asarray([str(sample.raw_status) for sample in trace.samples], dtype=str),
            power_w=np.asarray([
                np.nan if sample.power_w is None else float(sample.power_w)
                for sample in trace.samples
            ], dtype=float),
            valid_for_statistics=np.asarray([
                bool(sample.valid_for_statistics) for sample in trace.samples
            ], dtype=bool),
            requested_duration_s=np.asarray(trace.requested_duration_s, dtype=float),
            elapsed_duration_s=np.asarray(trace.elapsed_duration_s, dtype=float),
            trace_id=np.asarray(trace.trace_id, dtype=str),
            device_serial=np.asarray(trace.device_serial or "", dtype=str),
            sensor_serial=np.asarray(trace.sensor_serial or "", dtype=str),
            wavelength_option=np.asarray(trace.wavelength_option or "", dtype=str),
            range_option=np.asarray(trace.range_option or "", dtype=str),
        )
        return path

    def _require_spectrometer(self) -> SpectrometerProtocol:
        if not self.connected or self._spectrometer is None:
            raise RuntimeError("Ocean SR spectrometer is not connected.")
        return self._spectrometer

    def _current_integration_time(self) -> float:
        if self._spectrometer is None:
            return 0.0
        return float(self._spectrometer.integration_time_ms)

    @staticmethod
    def _validate_spectrum(spectrum: Spectrum) -> None:
        wavelengths = np.asarray(spectrum.wavelengths)
        intensities = np.asarray(spectrum.intensities)
        if wavelengths.ndim != 1 or intensities.ndim != 1:
            raise ValueError("Ocean SR spectrum arrays must be one-dimensional.")
        if wavelengths.shape != intensities.shape or wavelengths.size == 0:
            raise ValueError("Ocean SR spectrum arrays must be non-empty and matching.")
        if not np.all(np.isfinite(wavelengths)) or not np.all(np.isfinite(intensities)):
            raise ValueError("Ocean SR spectrum contains non-finite values.")

    def _clear_commands(self) -> None:
        while True:
            try:
                self._live_commands.get_nowait()
            except Empty:
                return

    @staticmethod
    def _validate_rotation_tolerance(value: float) -> float:
        value = float(value)
        if not np.isfinite(value) or not 0.001 <= value <= 5.0:
            raise ValueError(
                "Rotation readback tolerance must be between 0.001 and 5 degrees."
            )
        return value
