"""Qt worker that owns the simulated backend outside the GUI thread."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from gui.simulated_backend import SimulatedCampaignBackend
from gui.spectrometer_backend import PIReferenceRequired, SpectrometerCampaignBackend
from gui.state import CalibrationRequest, LiveViewRequest, ScanRequest


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

    @Slot()
    def publish_initial_state(self) -> None:
        self.snapshot_changed.emit(self.backend.snapshot())

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
        self._execute(
            "Connect configured devices",
            lambda: self.backend.connect_all(self.snapshot_changed.emit),
        )

    @Slot(object)
    def connect_all_with_serials(self, serials: dict[str, str]) -> None:
        self._execute(
            "Connect configured devices",
            lambda: self.backend.connect_all(
                self.snapshot_changed.emit,
                serials=serials,
            ),
        )

    @Slot()
    def disconnect_all(self) -> None:
        self._execute(
            "Safe disconnect",
            lambda: self.backend.safe_disconnect(self.snapshot_changed.emit),
        )

    @Slot(str, str)
    def connect_device(self, key: str, serial: str) -> None:
        try:
            self.backend.connect_device(
                key,
                serial,
                self.snapshot_changed.emit,
            )
        except PIReferenceRequired as error:
            self.log_message.emit(f"PI REFERENCE REQUIRED: {error}")
            self.pi_reference_required.emit(str(error))
        except Exception as error:
            self.operation_failed.emit(f"Connect {key} failed: {error}")
        else:
            self.log_message.emit(f"Connect {key}: complete.")

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
        self._execute(
            "Reference PI stage",
            self._reference_pi_and_resume_connection,
        )

    def _reference_pi_and_resume_connection(self) -> None:
        self.backend.reference_pi_stage(self.snapshot_changed.emit)
        self.log_message.emit(
            "PI FRF reference verified; resuming configured-device connection."
        )
        self.backend.connect_all(self.snapshot_changed.emit)

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

    @Slot(float)
    def set_power(self, target_power_mw: float) -> None:
        self._execute(
            "Set simulated power",
            lambda: self.backend.set_power(
                target_power_mw,
                self.snapshot_changed.emit,
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
            )
        except Exception as error:
            self.operation_failed.emit(f"Scan failed: {error}")
            self.scan_finished.emit(False)
        else:
            self.scan_finished.emit(completed)

    def request_cancel(self) -> None:
        """Thread-safe immediate flag; callable while the worker loop is busy."""

        self.backend.request_cancel()

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
