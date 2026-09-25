"""Offscreen hardware-free smoke test for the campaign GUI widgets."""

from __future__ import annotations

from dataclasses import replace
import os
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ROTATION_GUI_DISABLE_SETTINGS"] = "1"

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from gui.main_window import CampaignMainWindow


def main() -> None:
    application = QApplication.instance() or QApplication([])
    window = CampaignMainWindow()
    window.show()
    application.processEvents()

    assert "HARDWARE" in window.windowTitle()
    assert window._mode == "hardware"
    assert window.tabs.count() == 7
    assert window.run_button.isEnabled() is False

    simulation_index = window.mode_selector.findData("simulation")
    window.mode_selector.setCurrentIndex(simulation_index)
    deadline = time.monotonic() + 2.0
    while window._mode != "simulation":
        application.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("Simulation mode transition did not complete.")
        time.sleep(0.01)

    window.connect_button.click()
    assert window._connection_in_progress
    assert "CONNECTION IN PROGRESS" in window.safety_status_group.title()
    assert window.connection_badge.text() == "CONNECTING..."
    assert not window.connect_button.isEnabled()
    window._connect_all_from_fields()
    assert "duplicate connection request" in window.device_log.toPlainText()
    deadline = time.monotonic() + 2.0
    while (
        not window._latest_snapshot
        or not window._latest_snapshot.all_connected
    ):
        application.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("Simulated GUI connection did not complete.")
        time.sleep(0.01)

    assert not window._connection_in_progress
    assert window.safety_status_group.title() == "Persistent safety status"

    assert window.connection_badge.text() == "SIMULATION  CONNECTED"
    assert window.connection_health_text.text() == "ALL CONNECTED"
    assert window.shutter_badge.text() == "SHUTTER  CLOSED"
    assert window.probe_badge.text() == "PROBE  OUT"
    assert window.run_button.isEnabled() is True
    assert window.devices_open_shutter.isEnabled()
    assert window.worker._last_health_snapshot.all_connected
    for key in window.worker.backend._device_connections:
        window.worker.backend._device_connections[key] = False
    deadline = time.monotonic() + 2.5
    while window._latest_snapshot.any_connected:
        application.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("Idle health polling did not detect simulated removal.")
        time.sleep(0.01)
    assert window.connection_health_text.text() == "CONNECTION LOST"
    assert window.connection_badge.text() == "SIMULATION  DISCONNECTED"
    assert all(
        window.device_table.item(row, 1).text() == "DISCONNECTED"
        for row in range(window.device_table.rowCount())
    )
    window._connect_all_from_fields()
    deadline = time.monotonic() + 2.0
    while not window._latest_snapshot.all_connected or window._connection_in_progress:
        application.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("Reconnect after idle health loss did not complete.")
        time.sleep(0.01)
    connected_snapshot = window._latest_snapshot
    spectrometer_row = window._device_table_keys.index("spectrometer")
    connect_widget = window.device_table.cellWidget(spectrometer_row, 5)
    window._show_snapshot(connected_snapshot)
    assert window.device_table.cellWidget(spectrometer_row, 5) is connect_widget
    changed_devices = tuple(
        replace(device, value="25 ms")
        if device.key == "spectrometer"
        else device
        for device in connected_snapshot.devices
    )
    window._show_snapshot(replace(connected_snapshot, devices=changed_devices))
    assert window.device_table.item(spectrometer_row, 3).text() == "25 ms"
    assert window.device_table.cellWidget(spectrometer_row, 5) is connect_widget
    window._show_snapshot(connected_snapshot)

    lost_devices = tuple(
        replace(device, connection=type(device.connection).DISCONNECTED)
        if device.key == "spectrometer"
        else device
        for device in connected_snapshot.devices
    )
    window._scan_running = True
    window._scan_connection_loss_reported = False
    window.worker.backend._cancel.clear()
    window._show_snapshot(replace(connected_snapshot, devices=lost_devices))
    assert window.worker.backend._cancel.is_set()
    assert window._scan_connection_loss_reported
    assert "Ocean SR" in window.run_warning.text()
    window._scan_running = False
    window._show_snapshot(connected_snapshot)
    window._request_shutter(True)
    deadline = time.monotonic() + 2.0
    while window._latest_snapshot.shutter_closed is not False:
        application.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("Simulated shutter did not open.")
        time.sleep(0.01)
    open_snapshot = window._latest_snapshot
    window._mode = "hardware"
    window._show_snapshot(open_snapshot)
    assert window.connection_badge.text() == "HARDWARE  CONNECTED"
    assert window.shutter_badge.text() == "SHUTTER  OPEN"
    assert window.probe_badge.text() == "PROBE  OUT"
    assert window.power_badge.text() == "POWER  NOT MEASURED"
    window._mode = "simulation"
    window._show_snapshot(open_snapshot)
    window._request_shutter(False)
    deadline = time.monotonic() + 2.0
    while window._latest_snapshot.shutter_closed is not True:
        application.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("Simulated shutter did not close.")
        time.sleep(0.01)
    for button in window.findChildren(type(window.run_button)):
        assert button.minimumWidth() >= button.sizeHint().width()

    window.alignment_power_target.setValue(6.0)
    window._alignment_set_power()
    deadline = time.monotonic() + 2.0
    while window._latest_snapshot.beam_power_mw != 6.0:
        application.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("Simulated target-power command did not complete.")
        time.sleep(0.01)
    assert window._latest_snapshot.shutter_closed is True
    assert window._latest_snapshot.probe_out is True

    window.disconnect_device_requested.emit("spectrometer")
    deadline = time.monotonic() + 2.0
    while window._latest_snapshot.all_connected:
        application.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("Individual simulated disconnect did not complete.")
        time.sleep(0.01)
    assert window.connection_health_text.text() == "CONNECTION LOST"
    window.serial_fields["spectrometer"].setText("SIM-REPLACEMENT-SR")
    window._connect_one("spectrometer")
    deadline = time.monotonic() + 2.0
    while not window._latest_snapshot.all_connected or window._connection_in_progress:
        application.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("Individual simulated reconnect did not complete.")
        time.sleep(0.01)
    assert window.connection_health_text.text() == "ALL CONNECTED"
    assert "SIM-REPLACEMENT-SR" in [
        device.identity for device in window._latest_snapshot.devices
    ]
    assert "Requesting connection" in window.device_log.toPlainText()

    class EquivalentYes:
        def __eq__(self, other):
            return other == QMessageBox.StandardButton.Yes

        def __ne__(self, other):
            return not self == other

    original_warning = QMessageBox.warning
    try:
        QMessageBox.warning = staticmethod(lambda *args, **kwargs: EquivalentYes())
        window._offer_pi_reference("Confirmation regression test.")
    finally:
        QMessageBox.warning = original_warning
    assert "Operator approved PI FRF" in window.device_log.toPlainText()

    window.resize(1920, 1080)
    for tab_index in range(window.tabs.count()):
        window.tabs.setCurrentIndex(tab_index)
        application.processEvents()
        issues = window.audit_visible_layout()
        assert not issues, f"Tab {tab_index} layout issues: {issues}"

    window.tabs.setCurrentIndex(0)
    window.resize(1280, 650)
    application.processEvents()
    assert window.devices_scroll.verticalScrollBar().maximum() > 0
    scrollbar = window.devices_scroll.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum())
    application.processEvents()
    assert not window.device_log.visibleRegion().isEmpty()

    window.tabs.setCurrentWidget(window.calibration_page)
    application.processEvents()
    assert window.calibration_canvas.minimumHeight() >= 420
    assert window.calibration_scroll.verticalScrollBar().maximum() > 0
    calibration_scrollbar = window.calibration_scroll.verticalScrollBar()
    calibration_scrollbar.setValue(calibration_scrollbar.maximum() // 2)
    before_scroll = calibration_scrollbar.value()
    before_value = window.calibration_step.value()
    wheel = QWheelEvent(
        QPointF(2, 2), QPointF(2, 2), QPoint(), QPoint(0, -120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate, False,
    )
    QApplication.sendEvent(window.calibration_step, wheel)
    assert window.calibration_step.value() == before_value
    assert calibration_scrollbar.value() > before_scroll
    calibration_scrollbar.setValue(calibration_scrollbar.maximum() // 2)
    before_canvas_scroll = calibration_scrollbar.value()
    canvas_wheel = QWheelEvent(
        QPointF(2, 2), QPointF(2, 2), QPoint(), QPoint(0, -120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate, False,
    )
    QApplication.sendEvent(window.calibration_canvas, canvas_wheel)
    assert calibration_scrollbar.value() > before_canvas_scroll
    calibration_scrollbar.setValue(calibration_scrollbar.maximum())
    application.processEvents()
    assert not window.calibration_canvas.visibleRegion().isEmpty()

    window.resize(900, 650)
    window.tabs.setCurrentWidget(window.scan_setup_page)
    application.processEvents()
    assert window.scan_scroll.verticalScrollBar().maximum() > 0
    assert window.preflight_text.verticalScrollBarPolicy() != (
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    window.scan_scroll.verticalScrollBar().setValue(
        window.scan_scroll.verticalScrollBar().maximum()
    )
    window.scan_scroll.horizontalScrollBar().setValue(
        window.scan_scroll.horizontalScrollBar().maximum()
    )
    application.processEvents()
    assert not window.run_button.visibleRegion().isEmpty()
    assert window.run_button.width() >= window.run_button.sizeHint().width()

    window.tabs.setCurrentWidget(window.alignment_page)
    window.live_start_button.click()
    deadline = time.monotonic() + 3.0
    while window._latest_live_spectrum is None:
        application.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("Simulated live spectrum did not arrive.")
        time.sleep(0.01)
    assert window._latest_live_spectrum.serial == "SIM-OCEAN-SR"
    assert window.live_status.text().startswith("Frame ")
    window.live_stop_button.click()
    deadline = time.monotonic() + 3.0
    while window._live_running:
        application.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("Simulated live view did not stop.")
        time.sleep(0.01)

    with tempfile.TemporaryDirectory(prefix="gui_live_dashboard_") as temporary:
        hwp_index = window.rotation_target.findData("polarization_half_waveplate")
        window.rotation_target.setCurrentIndex(hwp_index)
        assert window._rotation_target_mode == "polarization_half_waveplate"
        assert (
            window.alignment_rotation_target.currentData()
            == "polarization_half_waveplate"
        )
        assert window.devices_sample_move.text() == "Move Polarisation HWP"
        assert window.alignment_sample_move.text() == "Move Polarisation HWP"
        assert window.devices_home_sample.text() == "Home Polarisation HWP"
        assert "HWP mount angle" in window.scan_form.labelForField(
            window.sample_angles
        ).text()
        sample_row = window._device_table_keys.index("sample")
        assert window.device_table.item(sample_row, 0).text() == (
            "Polarisation HWP rotation stage"
        )
        window.sample_definition.setCurrentIndex(
            window.sample_definition.findData("range")
        )
        window.sample_range_start.setValue(0.0)
        window.sample_range_stop.setValue(10.0)
        window.sample_range_step.setValue(10.0)
        window.intensity_values.setText("5")
        window.spectra_per_point.setValue(2)
        window.background.setChecked(False)
        window.output_directory.setText(temporary)
        window.experiment_name.setText("dashboard_test")
        window._update_preflight()
        assert "Rotation target: polarisation half-waveplate" in (
            window.preflight_text.toPlainText()
        )
        assert window.run_button.isEnabled()
        window.run_button.click()
        assert window._scan_running
        assert not window.rotation_target.isEnabled()
        assert not window.alignment_rotation_target.isEnabled()
        assert window.tabs.currentWidget() is window.live_run_page
        assert not window.run_button.isEnabled()
        assert window.run_button.text() == "SCAN IN PROGRESS - START DISABLED"
        assert window.scan_activity_badge.text() == "SCAN  STARTING"
        window._start_scan()
        assert "duplicate scan-start" in window.device_log.toPlainText()
        deadline = time.monotonic() + 4.0
        while window._scan_running:
            application.processEvents()
            if time.monotonic() > deadline:
                raise AssertionError("Dashboard scan did not complete.")
            time.sleep(0.01)
        assert len(window._run_groups) == 2
        assert all(len(items) == 2 for items in window._run_groups.values())
        assert window._dashboard_render_count < 4
        assert window.scan_activity_badge.text() == "SCAN  COMPLETE"
        assert window.run_button.text() == "Run simulated scan"
        assert "Estimated remaining" in window.run_timing.text()
        assert "Achieved" in window.run_power_status.text()
        assert window.run_warning.text() == "No active warnings"
        assert Path(window.run_directory_label.text()).is_dir()
        assert window.scan_axes.get_title().startswith(
            "Live polarisation half-waveplate rotation scan"
        )
        assert window.scan_axes.get_xlabel() == (
            "Polarisation HWP mount angle (deg)"
        )
        assert window.rotation_target.isEnabled()
        assert window.alignment_rotation_target.isEnabled()
        assert window.live_harmonic_selector.currentText().startswith("H5")
        window.live_harmonic_selector.setCurrentIndex(0)
        application.processEvents()
        assert window.scan_axes.get_ylabel() == "Integrated counts"
        assert window.canvas.minimumHeight() >= 820
        assert window.live_run_scroll.verticalScrollBar().maximum() > 0
        window.live_run_scroll.verticalScrollBar().setValue(
            window.live_run_scroll.verticalScrollBar().maximum()
        )
        application.processEvents()
        assert not window.canvas.visibleRegion().isEmpty()
        window._copy_run_status()
        assert "Directory:" in QApplication.clipboard().text()

    window._safe_disconnect_all()
    deadline = time.monotonic() + 2.0
    while window._latest_snapshot.any_connected:
        application.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("Simulated GUI disconnect did not complete.")
        time.sleep(0.01)
    hardware_index = window.mode_selector.findData("hardware")
    window.mode_selector.setCurrentIndex(hardware_index)
    deadline = time.monotonic() + 2.0
    while window._mode != "hardware":
        application.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("Hardware mode transition did not complete.")
        time.sleep(0.01)
    assert "HARDWARE" in window.windowTitle()
    assert window.connect_button.text() == "Connect alignment devices"
    assert window.tabs.isTabEnabled(1)
    assert window.tabs.isTabEnabled(2)
    assert window.tabs.isTabEnabled(3)
    assert window.tabs.isTabEnabled(4)
    assert window.intensity_mode.currentData() == "target_power_mw"
    assert "Connect all configured" in window.run_button.toolTip()
    assert window.tabs.isTabEnabled(5)
    assert {
        device.key for device in window._latest_snapshot.devices if device.available
    } == {
        "waveplate", "sample", "shutter", "spectrometer", "power_meter_stage",
        "power_meter",
    }
    assert window.safe_button.isEnabled() is False
    assert window.live_start_button.isEnabled() is False
    assert window.devices_open_shutter.isEnabled() is False
    assert window.live_refresh.isEnabled() is False
    assert "every spectrum" in window.live_refresh.toolTip()
    assert window.tabs.isTabEnabled(6)
    window.tabs.setCurrentWidget(window.settings_page)
    window.rotation_tolerance_setting.setValue(0.125)
    window.saturation_setting.setValue(60000)
    window.probe_in_setting.setValue(11.5)
    window.probe_out_setting.setValue(-11.5)
    window.power_duration_setting.setValue(8.0)
    window.power_settle_setting.setValue(2.0)
    window._apply_operator_settings()
    assert window._operator_settings["rotation_readback_tolerance_deg"] == 0.125
    assert window._operator_settings["probe_in_position_mm"] == 11.5
    assert window._operator_settings["power_measurement_duration_s"] == 8.0

    window.close()
    application.processEvents()
    assert not window.isVisible()
    print("GUI WIDGET TEST PASSED")


if __name__ == "__main__":
    main()
