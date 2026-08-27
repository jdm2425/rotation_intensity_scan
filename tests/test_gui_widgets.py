"""Offscreen hardware-free smoke test for the campaign GUI widgets."""

from __future__ import annotations

import os
import time

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

    window.connect_requested.emit()
    deadline = time.monotonic() + 2.0
    while (
        not window._latest_snapshot
        or not window._latest_snapshot.all_connected
    ):
        application.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("Simulated GUI connection did not complete.")
        time.sleep(0.01)

    assert window.connection_badge.text() == "HARDWARE  CONNECTED"
    assert window.connection_health_text.text() == "ALL CONNECTED"
    assert window.shutter_badge.text() == "SHUTTER  CLOSED"
    assert window.probe_badge.text() == "PROBE  OUT"
    assert window.run_button.isEnabled() is True
    assert window.devices_open_shutter.isEnabled()
    window._request_shutter(True)
    deadline = time.monotonic() + 2.0
    while window._latest_snapshot.shutter_closed is not False:
        application.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("Simulated shutter did not open.")
        time.sleep(0.01)
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
    while not window._latest_snapshot.all_connected:
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
