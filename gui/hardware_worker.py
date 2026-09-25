"""Qt worker that owns the simulated backend outside the GUI thread."""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from gui.simulated_backend import SimulatedCampaignBackend
from gui.spectrometer_backend import PIReferenceRequired, SpectrometerCampaignBackend
from gui.state import CalibrationRequest, LiveViewRequest, ScanRequest, TargetPowerRequest


class HardwareWorker(QObject):
    """Serialise backend operations and publish immutable updates."""

    snapshot_changed = Signal(object)
    measurement_acquired = Signal(object, int, int)
    log_message = Signal(str)
    operation_failed = Signal(str)
    scan_finished = Signal(bool)
    live_spectrum_acquired = Signal(object, object, object)
    live_finished = Signal()
    mode_changed = Signal(str)
    pi_reference_required = Signal(str)
    calibration_point = Signal(float, float, int, int)
    calibration_finished = Signal(object)
    run_directory_changed = Signal(str)
    connection_attempt_finished = Signal(object)
    IDLE_HEALTH_POLL_INTERVAL_MS = 1000

    def __init__(self) -> None:
        super().__init__()
        # Hardware mode is the campaign default, but construction is inert:
        # real drivers remain lazy until an explicit Connect action.
        self.backend = SpectrometerCampaignBackend()
        self.mode = "hardware"
        self.operator_settings = {
            "rotation_readback_tolerance_deg": 0.05,
            "saturation_warning_counts": 65_535.0,
            "probe_in_position_mm": 12.0,
            "probe_out_position_mm": -12.0,
            "power_measurement_duration_s": 10.0,
            "power_settle_time_s": 3.0,
            "power_poll_interval_s": 0.1,
        }
        self._health_timer: QTimer | None = None
        self._last_health_snapshot = None
        # Every backend path emits through this signal. Keep the comparison
        # cache synchronized with event-driven snapshots as well as timer polls.
        self.snapshot_changed.connect(self._remember_snapshot)

    @Slot(object)
    def _remember_snapshot(self, snapshot) -> None:
        self._last_health_snapshot = snapshot

    @Slot()
    def publish_initial_state(self) -> None:
        snapshot = self.backend.snapshot()
        self._last_health_snapshot = snapshot
        self.snapshot_changed.emit(snapshot)
        if self._health_timer is None:
            self._health_timer = QTimer(self)
            self._health_timer.setInterval(self.IDLE_HEALTH_POLL_INTERVAL_MS)
            self._health_timer.timeout.connect(self.poll_idle_health)
            self._health_timer.start()

    @Slot()
    def poll_idle_health(self) -> None:
        """Publish changed live state while the backend is otherwise idle."""

        if self.backend.busy:
            return
        try:
            poll = getattr(self.backend, "poll_idle_health", None)
            if callable(poll):
                snapshot, losses = poll()
            else:
                snapshot, losses = self.backend.snapshot(), ()
        except Exception as error:
            self.log_message.emit(f"IDLE HEALTH CHECK FAILED: {error}")
            return
        for loss in losses:
            self.log_message.emit(
                "HARDWARE CONNECTION LOST: "
                f"{loss}. No motion command was issued; verify the apparatus safely."
            )
        if snapshot != self._last_health_snapshot:
            self._last_health_snapshot = snapshot
            self.snapshot_changed.emit(snapshot)

    @Slot(str)
    def set_mode(self, mode: str) -> None:
        mode = str(mode).strip().lower()
        if mode not in {"simulation", "hardware"}:
            self.operation_failed.emit(f"Unknown GUI mode: {mode!r}")
            return
        snapshot = self.backend.snapshot()
        if snapshot.busy or snapshot.any_connected:
            self.operation_failed.emit(
                "Disconnect all devices and stop active operations before "
                "changing GUI mode."
            )
            self.mode_changed.emit(self.mode)
            return
        self.backend = (
            SimulatedCampaignBackend()
            if mode == "simulation"
            else SpectrometerCampaignBackend()
        )
        self.mode = mode
        self.backend.set_operator_settings(self.operator_settings)
        self._last_health_snapshot = None
        self.mode_changed.emit(mode)
        self.snapshot_changed.emit(self.backend.snapshot())
        self.log_message.emit(
            "Mode changed to "
            + ("Simulation." if mode == "simulation" else "Hardware — alignment devices.")
        )

    @Slot(object)
    def set_operator_settings(self, settings: dict[str, float]) -> None:
        self.operator_settings = dict(settings)
        self._execute(
            "Apply operator settings",
            lambda: self.backend.set_operator_settings(self.operator_settings),
        )

    @Slot()
    def connect_all(self) -> None:
        self._connect_all_best_effort()

    @Slot(object)
    def connect_all_with_serials(self, serials: dict[str, str]) -> None:
        self._connect_all_best_effort(serials)

    def _connect_all_best_effort(self, serials: dict[str, str] | None = None) -> None:
        try:
            report = self.backend.connect_all(
                self.snapshot_changed.emit,
                serials=serials,
            )
        except Exception as error:
            report = {
                "connected": (),
                "already_connected": (),
                "failures": (("connection_pass", str(error)),),
                "pi_reference_required": None,
            }
            self.operation_failed.emit(f"Connect configured devices failed: {error}")
            try:
                self.snapshot_changed.emit(self.backend.snapshot())
            except Exception:
                pass
        self._publish_connection_report(report)

    def _publish_connection_report(self, report: dict) -> None:
        failures = tuple(report.get("failures", ()))
        for key, message in failures:
            self.log_message.emit(f"CONNECTION FAILED [{key}]: {message}")
        snapshot = report.get("snapshot") or self.backend.snapshot()
        connected_count = sum(
            device.connection.value == "connected" and device.required
            for device in snapshot.devices
        )
        required_count = sum(device.required for device in snapshot.devices)
        self.log_message.emit(
            f"Connection pass finished: {connected_count}/{required_count} "
            "required devices connected. Successful connections were retained."
        )
        self.connection_attempt_finished.emit(report)
        reference_message = report.get("pi_reference_required")
        if reference_message:
            self.log_message.emit(f"PI REFERENCE REQUIRED: {reference_message}")
            self.pi_reference_required.emit(str(reference_message))

    @Slot()
    def disconnect_all(self) -> None:
        self._execute(
            "Safe disconnect",
            lambda: self.backend.safe_disconnect(self.snapshot_changed.emit),
        )

    @Slot(str, str)
    def connect_device(self, key: str, serial: str) -> None:
        report = {
            "connected": (),
            "already_connected": (),
            "failures": (),
            "pi_reference_required": None,
        }
        try:
            self.backend.connect_device(
                key,
                serial,
                self.snapshot_changed.emit,
            )
        except PIReferenceRequired as error:
            report["failures"] = ((key, str(error)),)
            report["pi_reference_required"] = str(error)
        except Exception as error:
            report["failures"] = ((key, str(error)),)
            self.operation_failed.emit(f"Connect {key} failed: {error}")
        else:
            report["connected"] = (key,)
            self.log_message.emit(f"Connect {key}: complete.")
        finally:
            try:
                snapshot = self.backend.snapshot()
                report["snapshot"] = snapshot
                self.snapshot_changed.emit(snapshot)
            except Exception:
                pass
            self.connection_attempt_finished.emit(report)
        reference_message = report.get("pi_reference_required")
        if reference_message:
            self.log_message.emit(f"PI REFERENCE REQUIRED: {reference_message}")
            self.pi_reference_required.emit(str(reference_message))

    @Slot(str)
    def disconnect_device(self, key: str) -> None:
        self._execute(
            f"Disconnect {key}",
            lambda: self.backend.disconnect_device(
                key,
                self.snapshot_changed.emit,
            ),
        )

    @Slot()
    def safe_state(self) -> None:
        self._execute(
            "Safe state",
            lambda: self.backend.safe_state(self.snapshot_changed.emit),
        )

    @Slot()
    def close_shutter(self) -> None:
        self._execute(
            "Close shutter",
            lambda: self.backend.close_shutter(self.snapshot_changed.emit),
        )

    @Slot(bool)
    def open_shutter(self, allow_unverified_probe: bool = False) -> None:
        self._execute(
            "Open shutter",
            lambda: self.backend.open_shutter(
                self.snapshot_changed.emit,
                allow_unverified_probe=bool(allow_unverified_probe),
            ),
        )

    @Slot(float)
    def move_probe_absolute(self, position_mm: float) -> None:
        self._execute(
            "Move PI probe stage",
            lambda: self.backend.move_probe_absolute(
                float(position_mm), self.snapshot_changed.emit
            ),
        )

    @Slot(str)
    def home_rotation_stage(self, stage: str) -> None:
        self._execute(
            f"Home {stage}",
            lambda: self.backend.home_rotation_stage(stage, self.snapshot_changed.emit),
        )

    @Slot()
    def reference_pi_stage(self) -> None:
        try:
            report = self._reference_pi_and_resume_connection()
        except Exception as error:
            self.operation_failed.emit(f"Reference PI stage failed: {error}")
            self.connection_attempt_finished.emit(
                {"connected": (), "failures": (("power_meter_stage", str(error)),)}
            )
        else:
            self.log_message.emit("Reference PI stage: complete.")
            self._publish_connection_report(report)

    def _reference_pi_and_resume_connection(self) -> dict:
        self.backend.reference_pi_stage(self.snapshot_changed.emit)
        self.log_message.emit(
            "PI FRF reference verified; resuming configured-device connection."
        )
        return self.backend.connect_all(self.snapshot_changed.emit)

    @Slot(str, float)
    def move_stage(self, stage: str, position: float) -> None:
        self._execute(
            f"Move {stage}",
            lambda: self.backend.move_stage(
                stage,
                position,
                self.snapshot_changed.emit,
            ),
        )

    @Slot(bool)
    def set_probe_out(self, out: bool) -> None:
        self._execute(
            "Move simulated probe",
            lambda: self.backend.set_probe(
                out=out,
                publish=self.snapshot_changed.emit,
            ),
        )

    @Slot(object)
    def set_power(self, request: float | TargetPowerRequest) -> None:
        self._execute(
            "Set target power",
            lambda: self.backend.set_power(
                request,
                self.snapshot_changed.emit,
                publish_log=self.log_message.emit,
            ),
        )

    @Slot()
    def measure_power(self) -> None:
        try:
            value = self.backend.measure_power(self.snapshot_changed.emit)
        except Exception as error:
            self.operation_failed.emit(f"Measure simulated power failed: {error}")
        else:
            self.log_message.emit(
                f"Simulated incident power measured: {value:.3f} mW."
            )

    @Slot(object)
    def run_scan(self, request: ScanRequest) -> None:
        try:
            completed = self.backend.run_scan(
                request,
                publish_snapshot=self.snapshot_changed.emit,
                publish_measurement=self.measurement_acquired.emit,
                publish_log=self.log_message.emit,
                publish_run_directory=self.run_directory_changed.emit,
            )
        except Exception as error:
            self.operation_failed.emit(f"Scan failed: {error}")
            self.scan_finished.emit(False)
        else:
            self.scan_finished.emit(completed)

    def request_cancel(self) -> None:
        """Thread-safe immediate flag; callable while the worker loop is busy."""

        self.backend.request_cancel()

    def request_pause(self, paused: bool) -> None:
        """Thread-safe pause flag checked only at backend safe points."""

        self.backend.request_pause(bool(paused))

    @Slot(object)
    def run_calibration(self, request: CalibrationRequest) -> None:
        try:
            result = self.backend.run_calibration(
                request,
                publish_snapshot=self.snapshot_changed.emit,
                publish_point=self.calibration_point.emit,
                publish_log=self.log_message.emit,
            )
        except Exception as error:
            self.operation_failed.emit(f"Calibration failed: {error}")
            self.calibration_finished.emit(None)
        else:
            self.calibration_finished.emit(result)

    @Slot(object)
    def run_live_view(self, request: LiveViewRequest) -> None:
        try:
            self.backend.run_live_view(
                request,
                publish_snapshot=self.snapshot_changed.emit,
                publish_spectrum=self.live_spectrum_acquired.emit,
                publish_log=self.log_message.emit,
            )
        except Exception as error:
            self.operation_failed.emit(f"Live spectrometer failed: {error}")
        finally:
            self.live_finished.emit()

    def request_live_stop(self) -> None:
        self.backend.request_live_stop()

    def queue_live_settings(self, integration_time_ms: float, averages: int) -> None:
        self.backend.queue_live_settings(
            integration_time_ms=integration_time_ms,
            averages=averages,
        )

    def queue_live_background_capture(self) -> None:
        self.backend.queue_live_background_capture()

    def queue_live_background_enabled(self, enabled: bool) -> None:
        self.backend.queue_live_background_enabled(enabled)

    def queue_live_save(self, output_directory) -> None:
        self.backend.queue_live_save(output_directory)

    def queue_live_stage_move(self, stage: str, position: float) -> None:
        self.backend.queue_live_stage_move(stage, position)

    def queue_live_set_power(self, target_power_mw: float) -> None:
        self.backend.queue_live_set_power(target_power_mw)

    def queue_live_measure_power(self) -> None:
        self.backend.queue_live_measure_power()

    def queue_live_shutter(self, open_shutter: bool) -> None:
        self.backend.queue_live_shutter(open_shutter=bool(open_shutter))

    def _execute(self, action: str, operation) -> None:
        try:
            operation()
        except PIReferenceRequired as error:
            self.log_message.emit(f"PI REFERENCE REQUIRED: {error}")
            self.pi_reference_required.emit(str(error))
        except Exception as error:
            self.operation_failed.emit(f"{action} failed: {error}")
        else:
            self.log_message.emit(f"{action}: complete.")
