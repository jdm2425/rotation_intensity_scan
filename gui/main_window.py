"""Campaign GUI with explicit simulation and capability-limited hardware modes."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QEvent, QSettings, QThread, Qt, Signal
from PySide6.QtGui import QAction, QColor, QCloseEvent, QFont, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from data.data_loader import load_experiment
from gui.hardware_worker import HardwareWorker
from gui.state import (
    CalibrationRequest,
    ConnectionState,
    GuiSnapshot,
    LiveViewRequest,
    ScanRequest,
    parse_number_list,
)
from hardware.config import POWER_METER_STAGE


class CampaignMainWindow(QMainWindow):
    """Operator-facing window for the safe simulated campaign workflow."""

    connect_requested = Signal()
    connect_configuration_requested = Signal(object)
    disconnect_requested = Signal()
    safe_state_requested = Signal()
    close_shutter_requested = Signal()
    open_shutter_requested = Signal(bool)
    move_probe_absolute_requested = Signal(float)
    home_rotation_requested = Signal(str)
    reference_pi_requested = Signal()
    move_stage_requested = Signal(str, float)
    probe_requested = Signal(bool)
    set_power_requested = Signal(float)
    measure_power_requested = Signal()
    scan_requested = Signal(object)
    live_requested = Signal(object)
    connect_device_requested = Signal(str, str)
    disconnect_device_requested = Signal(str)
    mode_requested = Signal(str)
    settings_requested = Signal(object)
    calibration_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings(
            "Imperial College London",
            "Rotation Intensity Campaign",
        )
        self._settings_enabled = os.environ.get(
            "ROTATION_GUI_DISABLE_SETTINGS", ""
        ).strip() not in {"1", "true", "TRUE"}
        self._mode = "hardware"
        self._operator_settings = self._load_operator_settings()
        self.setFont(QFont("Segoe UI", 9))
        self.setWindowTitle("Rotation + Intensity Campaign — SIMULATION")
        self.resize(1380, 900)
        self._latest_snapshot: GuiSnapshot | None = None
        self._scan_running = False
        self._live_running = False
        self._calibration_running = False
        self._latest_live_spectrum = None
        self._ever_fully_connected = False
        self._connection_fault = False
        self.serial_fields: dict[str, QLineEdit] = {}
        self._build_ui()
        self._install_wheel_guards()
        self._start_worker()
        self._apply_style()
        self._ensure_button_text_visible()
        if self._settings_enabled:
            self._restore_window_state()

    def _install_wheel_guards(self) -> None:
        """Prevent accidental wheel edits while preserving page scrolling."""

        for widget_type in (QAbstractSpinBox, QComboBox, QLineEdit):
            for widget in self.findChildren(widget_type):
                widget.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Wheel and isinstance(
            watched, (QAbstractSpinBox, QComboBox, QLineEdit)
        ):
            parent = watched.parentWidget()
            while parent is not None and not isinstance(parent, QScrollArea):
                parent = parent.parentWidget()
            if isinstance(parent, QScrollArea):
                scrollbar = parent.verticalScrollBar()
                pixel_delta = event.pixelDelta().y()
                angle_delta = event.angleDelta().y()
                if pixel_delta:
                    distance = pixel_delta
                else:
                    steps = angle_delta / 120.0
                    distance = int(steps * scrollbar.singleStep() * 3)
                scrollbar.setValue(scrollbar.value() - distance)
            return True
        return super().eventFilter(watched, event)

    def _build_ui(self) -> None:
        fullscreen_action = QAction("Toggle full screen", self)
        fullscreen_action.setShortcut(QKeySequence("F11"))
        fullscreen_action.triggered.connect(self._toggle_fullscreen)
        self.menuBar().addMenu("View").addAction(fullscreen_action)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(self._build_banner())
        layout.addWidget(self._build_safety_header())

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_devices_tab(), "1  Devices")
        self.alignment_page = self._build_alignment_tab()
        self.tabs.addTab(self.alignment_page, "2  Alignment / Live Spectrum")
        self.calibration_page = self._build_calibration_tab()
        self.tabs.addTab(self.calibration_page, "3  Calibration")
        self.scan_setup_page = self._build_scan_tab()
        self.tabs.addTab(self.scan_setup_page, "4  Scan Setup")
        self.live_run_page = self._build_live_tab()
        self.tabs.addTab(self.live_run_page, "5  Live Run")
        self.tabs.addTab(self._build_data_tab(), "6  Saved Data")
        self.settings_page = self._build_settings_tab()
        self.tabs.addTab(self.settings_page, "7  Settings")
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage(
            "Hardware mode selected; no devices connect until explicitly requested."
        )

    def _build_banner(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        self.mode_banner = QLabel()
        self.mode_banner.setObjectName("modeBanner")
        self.mode_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mode_banner.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.mode_banner, 1)
        layout.addWidget(QLabel("Operating mode"))
        self.mode_selector = QComboBox()
        self.mode_selector.addItem("Simulation", "simulation")
        self.mode_selector.addItem("Hardware — alignment devices", "hardware")
        initial_index = self.mode_selector.findData(self._mode)
        if initial_index >= 0:
            self.mode_selector.setCurrentIndex(initial_index)
        self.mode_selector.currentIndexChanged.connect(self._request_mode_change)
        layout.addWidget(self.mode_selector)
        self._update_mode_visuals()
        return container

    def _build_safety_header(self) -> QWidget:
        group = QGroupBox("Persistent safety status")
        layout = QHBoxLayout(group)
        self.connection_badge = QLabel("HARDWARE  DISCONNECTED")
        self.shutter_badge = QLabel("SHUTTER  UNKNOWN")
        self.probe_badge = QLabel("PROBE  UNKNOWN")
        self.power_badge = QLabel("POWER  --")
        for badge in (
            self.connection_badge,
            self.shutter_badge,
            self.probe_badge,
            self.power_badge,
        ):
            badge.setObjectName("statusBadge")
            badge.setMinimumWidth(170)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(badge)
        layout.addStretch()
        self.close_shutter_button = QPushButton("Close shutter")
        self.close_shutter_button.clicked.connect(lambda: self._request_shutter(False))
        layout.addWidget(self.close_shutter_button)
        self.safe_button = QPushButton("STOP / SAFE STATE")
        self.safe_button.setObjectName("safeButton")
        self.safe_button.clicked.connect(self._request_safe_state)
        layout.addWidget(self.safe_button)
        connection_health = QWidget()
        health_layout = QHBoxLayout(connection_health)
        health_layout.setContentsMargins(8, 0, 0, 0)
        self.connection_light = QLabel()
        self.connection_light.setFixedSize(20, 20)
        self.connection_health_text = QLabel("NOT CONNECTED")
        self.connection_health_text.setMinimumWidth(135)
        self.connection_health_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        health_layout.addWidget(self.connection_light)
        health_layout.addWidget(self.connection_health_text)
        layout.addWidget(connection_health)
        self._set_connection_health("unknown", "NOT CONNECTED")
        return group

    def _build_devices_tab(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        self.devices_scroll = QScrollArea()
        self.devices_scroll.setWidgetResizable(True)
        self.devices_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.devices_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        content = QWidget()
        self.calibration_scroll_content = content
        content.setMinimumHeight(920)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        controls = QHBoxLayout()
        self.connect_button = QPushButton("Connect configured devices")
        self.connect_button.setEnabled(False)
        self.connect_button.clicked.connect(self._connect_all_from_fields)
        self.disconnect_button = QPushButton("Safe disconnect")
        self.disconnect_button.clicked.connect(self._safe_disconnect_all)
        controls.addWidget(self.connect_button)
        controls.addWidget(self.disconnect_button)
        controls.addStretch()
        layout.addLayout(controls)

        self.device_table = QTableWidget(0, 7)
        self.device_table.setHorizontalHeaderLabels(
            [
                "Device",
                "Connection",
                "Serial / identity",
                "Live value",
                "Detail",
                "Connect",
                "Disconnect",
            ]
        )
        self.device_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.device_table.setAlternatingRowColors(True)
        self.device_table.setWordWrap(False)
        self.device_table.verticalHeader().setVisible(False)
        header = self.device_table.horizontalHeader()
        for column in range(5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.device_table.setMinimumHeight(260)
        layout.addWidget(self.device_table, 3)

        manual = QGroupBox("Safe manual controls — simulation")
        grid = QGridLayout(manual)
        self.waveplate_position = self._angle_box()
        self.sample_position = self._angle_box()
        grid.addWidget(QLabel("Waveplate target (deg)"), 0, 0)
        grid.addWidget(self.waveplate_position, 0, 1)
        waveplate_move = QPushButton("Move waveplate")
        waveplate_move.clicked.connect(
            lambda: self.move_stage_requested.emit(
                "waveplate", self.waveplate_position.value()
            )
        )
        grid.addWidget(waveplate_move, 0, 2)
        grid.addWidget(QLabel("Sample target (deg)"), 1, 0)
        grid.addWidget(self.sample_position, 1, 1)
        sample_move = QPushButton("Move sample")
        sample_move.clicked.connect(
            lambda: self.move_stage_requested.emit(
                "sample", self.sample_position.value()
            )
        )
        grid.addWidget(sample_move, 1, 2)
        insert_probe = QPushButton("Insert probe safely")
        insert_probe.clicked.connect(lambda: self.probe_requested.emit(False))
        retract_probe = QPushButton("Retract and verify probe")
        retract_probe.clicked.connect(lambda: self.probe_requested.emit(True))
        grid.addWidget(insert_probe, 2, 1)
        grid.addWidget(retract_probe, 2, 2)
        self.devices_open_shutter = QPushButton("Open shutter")
        self.devices_close_shutter = QPushButton("Close shutter")
        self.devices_open_shutter.clicked.connect(lambda: self._request_shutter(True))
        self.devices_close_shutter.clicked.connect(lambda: self._request_shutter(False))
        grid.addWidget(self.devices_open_shutter, 3, 1)
        grid.addWidget(self.devices_close_shutter, 3, 2)
        self.devices_pi_target = self._pi_position_box()
        self.devices_pi_move = QPushButton("Move PI stage")
        self.devices_pi_move.clicked.connect(
            lambda: self._request_pi_move(self.devices_pi_target.value())
        )
        grid.addWidget(QLabel("PI target (mm)"), 4, 0)
        grid.addWidget(self.devices_pi_target, 4, 1)
        grid.addWidget(self.devices_pi_move, 4, 2)
        self.devices_reference_pi = QPushButton("Reference / home PI stage")
        self.devices_reference_pi.clicked.connect(self._request_pi_reference)
        self.devices_home_waveplate = QPushButton("Home waveplate")
        self.devices_home_sample = QPushButton("Home sample")
        self.devices_home_waveplate.clicked.connect(
            lambda: self._request_rotation_home("waveplate")
        )
        self.devices_home_sample.clicked.connect(
            lambda: self._request_rotation_home("sample")
        )
        grid.addWidget(self.devices_reference_pi, 5, 1, 1, 2)
        grid.addWidget(self.devices_home_waveplate, 6, 1)
        grid.addWidget(self.devices_home_sample, 6, 2)
        self.manual_hardware_buttons = (
            waveplate_move,
            sample_move,
            insert_probe,
            retract_probe,
        )
        self.manual_stage_buttons = (waveplate_move, sample_move)
        self.manual_probe_buttons = (insert_probe, retract_probe)
        note = QLabel(
            "The real implementation will route probe motion through the existing "
            "shutter interlock. Unrestricted PI motion will not be a routine control."
        )
        note.setWordWrap(True)
        grid.addWidget(note, 7, 0, 1, 3)
        layout.addWidget(manual)

        diagnostics = QGroupBox("Connection and error log")
        diagnostics_layout = QVBoxLayout(diagnostics)
        self.device_log = QPlainTextEdit()
        self.device_log.setReadOnly(True)
        self.device_log.setMaximumBlockCount(2000)
        self.device_log.setPlaceholderText(
            "Connection attempts, state changes, and actionable errors appear here."
        )
        self.device_log.setMinimumHeight(130)
        diagnostics_layout.addWidget(self.device_log)
        clear_log = QPushButton("Clear device log")
        clear_log.clicked.connect(self.device_log.clear)
        diagnostics_layout.addWidget(clear_log, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addWidget(diagnostics, 2)
        self.devices_scroll.setWidget(content)
        page_layout.addWidget(self.devices_scroll)
        return page

    def _build_alignment_tab(self) -> QWidget:
        page = QWidget()
        outer = QHBoxLayout(page)

        controls = QGroupBox("Live spectrometer controls — simulation")
        form = QFormLayout(controls)
        self._configure_form(form)
        self.live_integration_time = QDoubleSpinBox()
        self.live_integration_time.setRange(0.01, 60_000.0)
        self.live_integration_time.setDecimals(3)
        self.live_integration_time.setValue(10.0)
        self.live_integration_time.setSuffix(" ms")
        self.live_averages = QSpinBox()
        self.live_averages.setRange(1, 1000)
        self.live_averages.setValue(1)
        self.live_refresh = QDoubleSpinBox()
        self.live_refresh.setRange(0.02, 5.0)
        self.live_refresh.setValue(0.1)
        self.live_refresh.setSuffix(" s")
        self.live_autoscale = QCheckBox("Autoscale vertical axis")
        self.live_autoscale.setChecked(True)
        self.live_x_min = QLineEdit()
        self.live_x_min.setPlaceholderText("automatic")
        self.live_x_max = QLineEdit()
        self.live_x_max.setPlaceholderText("automatic")
        self.live_y_min = QLineEdit()
        self.live_y_min.setPlaceholderText("automatic")
        self.live_y_max = QLineEdit()
        self.live_y_max.setPlaceholderText("automatic")
        self.live_output = QLineEdit(
            str(Path("results/live_spectrometer").resolve())
        )
        output_row = QWidget()
        output_layout = QHBoxLayout(output_row)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.addWidget(self.live_output)
        output_browse = QPushButton("Browse…")
        output_browse.clicked.connect(self._browse_live_output)
        output_layout.addWidget(output_browse)
        form.addRow("Integration time", self.live_integration_time)
        form.addRow("Internal averages", self.live_averages)
        self.live_refresh_label = QLabel("Refresh interval")
        form.addRow(self.live_refresh_label, self.live_refresh)
        form.addRow("Scaling", self.live_autoscale)
        form.addRow("X minimum (nm)", self.live_x_min)
        form.addRow("X maximum (nm)", self.live_x_max)
        form.addRow("Y minimum (counts)", self.live_y_min)
        form.addRow("Y maximum (counts)", self.live_y_max)
        form.addRow("Manual save directory", output_row)

        self.live_start_button = QPushButton("Start simulated live view")
        self.live_start_button.setObjectName("runButton")
        self.live_start_button.clicked.connect(self._start_live_view)
        self.live_stop_button = QPushButton("Pause live view")
        self.live_stop_button.setEnabled(False)
        self.live_stop_button.clicked.connect(self._stop_live_view)
        form.addRow(self.live_start_button, self.live_stop_button)

        self.live_capture_background = QPushButton("Capture / replace background")
        self.live_capture_background.setEnabled(False)
        self.live_capture_background.clicked.connect(
            lambda: self.worker.queue_live_background_capture()
        )
        self.live_background_enabled = QCheckBox("Subtract captured background")
        self.live_background_enabled.setEnabled(False)
        self.live_background_enabled.toggled.connect(
            lambda enabled: self.worker.queue_live_background_enabled(enabled)
        )
        self.live_save_button = QPushButton("Save displayed spectrum")
        self.live_save_button.setEnabled(False)
        self.live_save_button.clicked.connect(
            lambda: self.worker.queue_live_save(Path(self.live_output.text()))
        )
        form.addRow("Background", self.live_capture_background)
        form.addRow("Subtraction", self.live_background_enabled)
        form.addRow("Manual snapshot", self.live_save_button)
        self.live_status = QLabel("Live view stopped")
        self.live_status.setWordWrap(True)
        form.addRow("Status", self.live_status)
        note = QLabel(
            "For alignment, the displayed spectrum may be background-subtracted, "
            "but background capture never overwrites raw scan data."
        )
        note.setWordWrap(True)
        form.addRow(note)
        alignment_hardware = QGroupBox("Motion and incident power")
        self.alignment_hardware_group = alignment_hardware
        hardware_form = QFormLayout(alignment_hardware)
        self._configure_form(hardware_form)
        self.alignment_waveplate_target = self._angle_box()
        self.alignment_sample_target = self._angle_box()
        self.alignment_power_target = QDoubleSpinBox()
        self.alignment_power_target.setRange(0.001, 100_000.0)
        self.alignment_power_target.setDecimals(3)
        self.alignment_power_target.setValue(5.0)
        self.alignment_power_target.setSuffix(" mW")
        waveplate_button = QPushButton("Move waveplate")
        waveplate_button.clicked.connect(
            lambda: self._alignment_move(
                "waveplate", self.alignment_waveplate_target.value()
            )
        )
        sample_button = QPushButton("Move sample")
        sample_button.clicked.connect(
            lambda: self._alignment_move(
                "sample", self.alignment_sample_target.value()
            )
        )
        set_power_button = QPushButton("Set target power")
        set_power_button.clicked.connect(self._alignment_set_power)
        measure_power_button = QPushButton("Measure incident power")
        self.alignment_measure_power_button = measure_power_button
        self.alignment_set_power_button = set_power_button
        measure_power_button.clicked.connect(self._alignment_measure_power)
        hardware_form.addRow(self.alignment_waveplate_target, waveplate_button)
        hardware_form.addRow(self.alignment_sample_target, sample_button)
        hardware_form.addRow(self.alignment_power_target, set_power_button)
        hardware_form.addRow("Power measurement", measure_power_button)
        self.alignment_open_shutter = QPushButton("Open shutter")
        self.alignment_close_shutter = QPushButton("Close shutter")
        self.alignment_open_shutter.clicked.connect(lambda: self._request_shutter(True))
        self.alignment_close_shutter.clicked.connect(lambda: self._request_shutter(False))
        shutter_controls = QWidget()
        shutter_layout = QHBoxLayout(shutter_controls)
        shutter_layout.setContentsMargins(0, 0, 0, 0)
        shutter_layout.addWidget(self.alignment_open_shutter)
        shutter_layout.addWidget(self.alignment_close_shutter)
        hardware_form.addRow("Beam shutter", shutter_controls)
        self.alignment_pi_target = self._pi_position_box()
        self.alignment_pi_move = QPushButton("Move PI stage")
        self.alignment_pi_move.clicked.connect(
            lambda: self._request_pi_move(self.alignment_pi_target.value())
        )
        hardware_form.addRow(self.alignment_pi_target, self.alignment_pi_move)
        self.alignment_reference_pi = QPushButton("Reference / home PI stage")
        self.alignment_reference_pi.clicked.connect(self._request_pi_reference)
        self.alignment_home_waveplate = QPushButton("Home waveplate")
        self.alignment_home_sample = QPushButton("Home sample")
        self.alignment_home_waveplate.clicked.connect(
            lambda: self._request_rotation_home("waveplate")
        )
        self.alignment_home_sample.clicked.connect(
            lambda: self._request_rotation_home("sample")
        )
        home_controls = QWidget()
        home_layout = QHBoxLayout(home_controls)
        home_layout.setContentsMargins(0, 0, 0, 0)
        home_layout.addWidget(self.alignment_home_waveplate)
        home_layout.addWidget(self.alignment_home_sample)
        hardware_form.addRow("Rotation homing", home_controls)
        hardware_form.addRow("PI referencing", self.alignment_reference_pi)
        self.alignment_hardware_buttons = (
            waveplate_button,
            sample_button,
            set_power_button,
            measure_power_button,
        )
        self.alignment_stage_buttons = (waveplate_button, sample_button)
        self.alignment_power_buttons = (set_power_button, measure_power_button)
        self.alignment_hardware_status = QLabel(
            "Waveplate --  |  Sample --  |  Measured power --"
        )
        self.alignment_hardware_status.setWordWrap(True)
        hardware_form.addRow("Current state", self.alignment_hardware_status)
        interlock_note = QLabel(
            "Power operations simulate shutter closure, probe insertion, "
            "measurement/feedback, retraction, and final shutter closure."
        )
        interlock_note.setWordWrap(True)
        hardware_form.addRow(interlock_note)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(controls)
        left_layout.addWidget(alignment_hardware)
        left_layout.addStretch()
        left_panel.setMinimumWidth(460)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        left_scroll.setWidget(left_panel)
        left_scroll.setMinimumWidth(490)
        outer.addWidget(left_scroll, 2)

        plot_group = QGroupBox("Alignment spectrum")
        plot_layout = QVBoxLayout(plot_group)
        self.alignment_figure = Figure(figsize=(9, 6), tight_layout=True)
        self.alignment_axes = self.alignment_figure.add_subplot(111)
        self.alignment_axes.set_xlabel("Wavelength (nm)")
        self.alignment_axes.set_ylabel("Counts")
        self.alignment_axes.set_title("Start live view to display a spectrum")
        self.alignment_canvas = FigureCanvasQTAgg(self.alignment_figure)
        plot_layout.addWidget(self.alignment_canvas)
        outer.addWidget(plot_group, 5)

        self.live_integration_time.valueChanged.connect(self._queue_live_settings)
        self.live_averages.valueChanged.connect(self._queue_live_settings)
        for field in (
            self.live_x_min,
            self.live_x_max,
            self.live_y_min,
            self.live_y_max,
        ):
            field.editingFinished.connect(self._redraw_alignment)
        self.live_autoscale.toggled.connect(self._redraw_alignment)
        return page

    def _build_calibration_tab(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        self.calibration_scroll = QScrollArea()
        self.calibration_scroll.setWidgetResizable(True)
        self.calibration_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.calibration_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        title = QLabel("Guided waveplate-power calibration")
        title.setFont(self._section_font())
        layout.addWidget(title)
        explanation = QLabel(
            "Campaign workflow: enter a reviewed angular interval → acquire a "
            "power map → inspect the proposed monotonic branch → review the "
            "Malus fit → approve it for target-power scans."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        form_group = QGroupBox("Calibration bounds")
        form = QFormLayout(form_group)
        self._configure_form(form)
        self.calibration_start = self._angle_box()
        self.calibration_start.setValue(75.0)
        self.calibration_stop = self._angle_box()
        self.calibration_stop.setValue(114.0)
        self.calibration_step = QDoubleSpinBox()
        self.calibration_step.setRange(0.01, 30.0)
        self.calibration_step.setValue(1.0)
        self.calibration_step.setSuffix(" deg")
        self.calibration_noise = QDoubleSpinBox()
        self.calibration_noise.setRange(0.0, 20.0)
        self.calibration_noise.setDecimals(3)
        self.calibration_noise.setValue(0.05)
        self.calibration_noise.setSuffix(" mW")
        self.calibration_output = QLineEdit(
            str(Path("results/waveplate_calibration").resolve())
        )
        form.addRow("Reviewed start", self.calibration_start)
        form.addRow("Reviewed stop", self.calibration_stop)
        form.addRow("Step", self.calibration_step)
        form.addRow("Monotonic noise tolerance", self.calibration_noise)
        form.addRow("Output directory", self.calibration_output)
        layout.addWidget(form_group)
        self.calibration_summary = QLabel()
        self.calibration_summary.setWordWrap(True)
        self.calibration_summary.setObjectName("notice")
        layout.addWidget(self.calibration_summary)
        self.calibration_run_button = QPushButton("Run simulated calibration")
        self.calibration_run_button.clicked.connect(self._start_calibration)
        layout.addWidget(self.calibration_run_button)
        self.calibration_figure = Figure(figsize=(7, 3), tight_layout=True)
        self.calibration_axes = self.calibration_figure.add_subplot(111)
        self.calibration_canvas = FigureCanvasQTAgg(self.calibration_figure)
        self.calibration_canvas.setMinimumHeight(420)
        self.calibration_canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        layout.addWidget(self.calibration_canvas)
        layout.addSpacing(20)
        self._calibration_angles: list[float] = []
        self._calibration_powers: list[float] = []
        for widget in (
            self.calibration_start, self.calibration_stop, self.calibration_step,
            self.calibration_noise,
        ):
            widget.valueChanged.connect(self._update_calibration_summary)
        self.calibration_output.textChanged.connect(self._update_calibration_summary)
        self._update_calibration_summary()
        self.calibration_scroll.setWidget(content)
        page_layout.addWidget(self.calibration_scroll)
        return page

    def _build_scan_tab(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        self.scan_scroll = QScrollArea()
        self.scan_scroll.setWidgetResizable(True)
        self.scan_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.scan_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        content = QWidget()
        self.scan_scroll_content = content
        content.setMinimumSize(1240, 820)
        outer = QHBoxLayout(content)
        outer.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        form_group = QGroupBox("Campaign scan definition")
        form_group.setMinimumWidth(720)
        form = QFormLayout(form_group)
        self._configure_form(form)
        self.sample_angles = QLineEdit("0 10 20")
        self.intensity_mode = QComboBox()
        self.intensity_mode.addItem("Target power (mW)", "target_power_mw")
        self.intensity_mode.addItem("Waveplate angle (deg)", "waveplate_angle_deg")
        self.intensity_values = QLineEdit("5 7.5 10")
        self.target_branch_min = self._angle_box()
        self.target_branch_min.setValue(0.0)
        self.target_branch_max = self._angle_box()
        self.target_branch_max.setValue(10.0)
        self.target_direction = QComboBox()
        self.target_direction.addItem("Increasing power", "increasing")
        self.target_direction.addItem("Decreasing power", "decreasing")
        self.target_tolerance = QDoubleSpinBox()
        self.target_tolerance.setRange(0.001, 20.0)
        self.target_tolerance.setDecimals(3)
        self.target_tolerance.setValue(0.2)
        self.target_tolerance.setSuffix(" mW")
        self.target_iterations = QSpinBox()
        self.target_iterations.setRange(1, 50)
        self.target_iterations.setValue(8)
        self.target_minimum_step = QDoubleSpinBox()
        self.target_minimum_step.setRange(0.001, 10.0)
        self.target_minimum_step.setDecimals(3)
        self.target_minimum_step.setValue(0.02)
        self.target_minimum_step.setSuffix(" deg")
        self.power_calibration = QLineEdit()
        self.power_calibration.setPlaceholderText("Optional malus_calibration.json")
        self.spectra_per_point = QSpinBox()
        self.spectra_per_point.setRange(1, 1000)
        self.spectra_per_point.setValue(10)
        self.integration_time = QDoubleSpinBox()
        self.integration_time.setRange(0.001, 600_000.0)
        self.integration_time.setValue(10.0)
        self.integration_time.setSuffix(" ms")
        self.averages = QSpinBox()
        self.averages.setRange(1, 1000)
        self.averages.setValue(1)
        self.background = QCheckBox("Acquire shutter-closed pre-scan background")
        self.background.setChecked(True)
        self.experiment_name = QLineEdit("campaign_scan")
        self.output_directory = QLineEdit(str(Path("results").resolve()))
        self.output_directory.setMinimumWidth(420)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_output)
        output_row = QWidget()
        output_layout = QHBoxLayout(output_row)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.addWidget(self.output_directory)
        output_layout.addWidget(browse)
        self.notes = QTextEdit()
        self.notes.setMaximumHeight(80)
        form.addRow("Sample angles (deg)", self.sample_angles)
        form.addRow("Intensity coordinate", self.intensity_mode)
        form.addRow("Intensity values", self.intensity_values)
        form.addRow("Target branch minimum", self.target_branch_min)
        form.addRow("Target branch maximum", self.target_branch_max)
        form.addRow("Branch direction", self.target_direction)
        form.addRow("Target tolerance", self.target_tolerance)
        form.addRow("Maximum feedback iterations", self.target_iterations)
        form.addRow("Minimum feedback angle step", self.target_minimum_step)
        form.addRow("Optional power calibration", self.power_calibration)
        form.addRow("Independent spectra per point", self.spectra_per_point)
        form.addRow("Integration time", self.integration_time)
        form.addRow("Internal averages", self.averages)
        form.addRow("Background", self.background)
        form.addRow("Experiment name", self.experiment_name)
        form.addRow("Output directory", output_row)
        form.addRow("Notes", self.notes)
        outer.addWidget(form_group, 3)

        preflight = QGroupBox("Preflight")
        preflight.setMinimumWidth(470)
        preflight_layout = QVBoxLayout(preflight)
        self.preflight_text = QPlainTextEdit()
        self.preflight_text.setReadOnly(True)
        self.preflight_text.setMinimumHeight(420)
        self.preflight_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        preflight_layout.addWidget(self.preflight_text, 1)
        validate = QPushButton("Validate and update summary")
        validate.clicked.connect(self._update_preflight)
        preflight_layout.addWidget(validate)
        preflight_layout.addStretch()
        self.run_button = QPushButton("Run simulated scan")
        self.run_button.setObjectName("runButton")
        self.run_button.clicked.connect(self._start_scan)
        preflight_layout.addWidget(self.run_button)
        outer.addWidget(preflight, 2)
        self.sample_angles.textChanged.connect(self._update_preflight)
        self.intensity_mode.currentIndexChanged.connect(self._update_preflight)
        self.intensity_values.textChanged.connect(self._update_preflight)
        self.target_branch_min.valueChanged.connect(self._update_preflight)
        self.target_branch_max.valueChanged.connect(self._update_preflight)
        self.target_direction.currentIndexChanged.connect(self._update_preflight)
        self.target_tolerance.valueChanged.connect(self._update_preflight)
        self.target_iterations.valueChanged.connect(self._update_preflight)
        self.target_minimum_step.valueChanged.connect(self._update_preflight)
        self.power_calibration.textChanged.connect(self._update_preflight)
        self.spectra_per_point.valueChanged.connect(self._update_preflight)
        self.integration_time.valueChanged.connect(self._update_preflight)
        self.averages.valueChanged.connect(self._update_preflight)
        self.background.toggled.connect(self._update_preflight)
        self.experiment_name.textChanged.connect(self._update_preflight)
        self.output_directory.textChanged.connect(self._update_preflight)
        self._update_preflight()
        self._update_calibration_summary()
        self.scan_scroll.setWidget(content)
        page_layout.addWidget(self.scan_scroll)
        return page

    def _build_live_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        top = QHBoxLayout()
        self.run_status = QLabel("No scan running")
        self.run_status.setFont(self._section_font())
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.cancel_button = QPushButton("Cancel after current safe point")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_scan)
        top.addWidget(self.run_status)
        top.addWidget(self.progress, 1)
        top.addWidget(self.cancel_button)
        layout.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.figure = Figure(figsize=(8, 5), tight_layout=True)
        self.spectrum_axes = self.figure.add_subplot(211)
        self.scan_axes = self.figure.add_subplot(212)
        self.spectrum_axes.set_title("Latest spectrum")
        self.spectrum_axes.set_xlabel("Wavelength (nm)")
        self.spectrum_axes.set_ylabel("Counts")
        self.scan_axes.set_title("Completed scan points (quick look)")
        self.scan_axes.set_xlabel("Sample angle (deg)")
        self.scan_axes.set_ylabel("Integrated counts")
        self.canvas = FigureCanvasQTAgg(self.figure)
        splitter.addWidget(self.canvas)
        self.event_log = QPlainTextEdit()
        self.event_log.setReadOnly(True)
        self.event_log.setMaximumBlockCount(2000)
        splitter.addWidget(self.event_log)
        splitter.setSizes([900, 350])
        layout.addWidget(splitter, 1)
        self._quick_x: list[float] = []
        self._quick_y: list[float] = []
        return page

    def _build_data_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("Inspect a saved experiment")
        title.setFont(self._section_font())
        layout.addWidget(title)
        row = QHBoxLayout()
        self.data_path = QLineEdit()
        browse = QPushButton("Choose experiment directory…")
        browse.clicked.connect(self._browse_experiment)
        load = QPushButton("Load summary")
        load.clicked.connect(self._load_summary)
        row.addWidget(self.data_path, 1)
        row.addWidget(browse)
        row.addWidget(load)
        layout.addLayout(row)
        self.data_summary = QPlainTextEdit()
        self.data_summary.setReadOnly(True)
        layout.addWidget(self.data_summary)
        return page

    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("Operator settings")
        title.setFont(self._section_font())
        layout.addWidget(title)
        explanation = QLabel(
            "These settings affect validation and display warnings. Hardware identity, "
            "shutter mapping, motion limits, homing, and PI driver tolerance remain locked "
            "in reviewed project configuration."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        group = QGroupBox("Validated persistent settings")
        form = QFormLayout(group)
        self._configure_form(form)
        self.rotation_tolerance_setting = QDoubleSpinBox()
        self.rotation_tolerance_setting.setRange(0.001, 5.0)
        self.rotation_tolerance_setting.setDecimals(3)
        self.rotation_tolerance_setting.setSingleStep(0.01)
        self.rotation_tolerance_setting.setSuffix(" deg")
        self.rotation_tolerance_setting.setValue(
            self._operator_settings["rotation_readback_tolerance_deg"]
        )
        self.rotation_tolerance_setting.setToolTip(
            "Maximum absolute difference between requested and live stage position."
        )
        self.saturation_setting = QDoubleSpinBox()
        self.saturation_setting.setRange(1.0, 1_000_000.0)
        self.saturation_setting.setDecimals(0)
        self.saturation_setting.setSuffix(" counts")
        self.saturation_setting.setValue(
            self._operator_settings["saturation_warning_counts"]
        )
        self.probe_in_setting = self._pi_position_box()
        self.probe_out_setting = self._pi_position_box()
        self.probe_in_setting.setValue(self._operator_settings["probe_in_position_mm"])
        self.probe_out_setting.setValue(self._operator_settings["probe_out_position_mm"])
        self.power_duration_setting = QDoubleSpinBox()
        self.power_duration_setting.setRange(0.1, 600.0)
        self.power_duration_setting.setValue(self._operator_settings["power_measurement_duration_s"])
        self.power_duration_setting.setSuffix(" s")
        self.power_settle_setting = QDoubleSpinBox()
        self.power_settle_setting.setRange(0.0, 120.0)
        self.power_settle_setting.setValue(self._operator_settings["power_settle_time_s"])
        self.power_settle_setting.setSuffix(" s")
        self.power_poll_setting = QDoubleSpinBox()
        self.power_poll_setting.setRange(0.01, 10.0)
        self.power_poll_setting.setValue(self._operator_settings["power_poll_interval_s"])
        self.power_poll_setting.setSuffix(" s")
        form.addRow("Rotation readback tolerance", self.rotation_tolerance_setting)
        form.addRow("Saturation warning threshold", self.saturation_setting)
        form.addRow("Probe insertion position", self.probe_in_setting)
        form.addRow("Probe retraction position", self.probe_out_setting)
        form.addRow("Power measurement duration", self.power_duration_setting)
        form.addRow("Power sensor settling time", self.power_settle_setting)
        form.addRow("Power polling interval", self.power_poll_setting)
        buttons = QWidget()
        button_layout = QHBoxLayout(buttons)
        button_layout.setContentsMargins(0, 0, 0, 0)
        apply_button = QPushButton("Apply and remember")
        apply_button.clicked.connect(self._apply_operator_settings)
        reset_button = QPushButton("Restore safe defaults")
        reset_button.clicked.connect(self._reset_operator_settings)
        button_layout.addWidget(apply_button)
        button_layout.addWidget(reset_button)
        button_layout.addStretch()
        form.addRow(buttons)
        layout.addWidget(group)
        audit = QPlainTextEdit()
        audit.setReadOnly(True)
        audit.setPlainText(
            "Reviewed but intentionally not exposed here:\n"
            "• hardware serial defaults and model assignments\n"
            "• shutter state mapping (0 open, 1 closed)\n"
            "• rotation-stage velocity, driver timeout, and homing behaviour\n"
            "• PI travel limits, velocity, and driver position tolerance\n"
            "• Ophir wavelength/range selection, status filtering, and safety ceiling\n\n"
            "Per-run acquisition, scan, plotting, and output settings remain on their "
            "relevant workflow tabs."
        )
        layout.addWidget(audit, 1)
        return page

    def _load_operator_settings(self) -> dict[str, float]:
        defaults = {
            "rotation_readback_tolerance_deg": 0.05,
            "saturation_warning_counts": 65_535.0,
            "probe_in_position_mm": 12.0,
            "probe_out_position_mm": -12.0,
            "power_measurement_duration_s": 10.0,
            "power_settle_time_s": 3.0,
            "power_poll_interval_s": 0.1,
        }
        if not self._settings_enabled:
            return defaults
        loaded = {}
        for key, default in defaults.items():
            try:
                loaded[key] = float(self.settings.value(f"operator/{key}", default))
            except (TypeError, ValueError):
                loaded[key] = default
        if not 0.001 <= loaded["rotation_readback_tolerance_deg"] <= 5.0:
            loaded["rotation_readback_tolerance_deg"] = defaults[
                "rotation_readback_tolerance_deg"
            ]
        if not 1.0 <= loaded["saturation_warning_counts"] <= 1_000_000.0:
            loaded["saturation_warning_counts"] = defaults["saturation_warning_counts"]
        lower, upper = -12.0, 12.0
        if not lower <= loaded["probe_in_position_mm"] <= upper:
            loaded["probe_in_position_mm"] = defaults["probe_in_position_mm"]
        if not lower <= loaded["probe_out_position_mm"] <= upper:
            loaded["probe_out_position_mm"] = defaults["probe_out_position_mm"]
        if np.isclose(loaded["probe_in_position_mm"], loaded["probe_out_position_mm"], atol=0.1):
            loaded["probe_in_position_mm"] = defaults["probe_in_position_mm"]
            loaded["probe_out_position_mm"] = defaults["probe_out_position_mm"]
        if not 0.1 <= loaded["power_measurement_duration_s"] <= 600.0:
            loaded["power_measurement_duration_s"] = defaults["power_measurement_duration_s"]
        if not 0.0 <= loaded["power_settle_time_s"] <= 120.0:
            loaded["power_settle_time_s"] = defaults["power_settle_time_s"]
        if not 0.01 <= loaded["power_poll_interval_s"] <= 10.0:
            loaded["power_poll_interval_s"] = defaults["power_poll_interval_s"]
        return loaded

    def _apply_operator_settings(self) -> None:
        if np.isclose(
            self.probe_in_setting.value(),
            self.probe_out_setting.value(),
            rtol=0.0,
            atol=float(POWER_METER_STAGE.position_tolerance_mm),
        ):
            self._show_error(
                "Probe insertion and retraction positions must be distinct by more "
                "than the configured PI tolerance."
            )
            return
        positions_changed = (
            self.probe_in_setting.value()
            != self._operator_settings["probe_in_position_mm"]
            or self.probe_out_setting.value()
            != self._operator_settings["probe_out_position_mm"]
        )
        if positions_changed and self._settings_enabled:
            answer = QMessageBox.warning(
                self,
                "Confirm probe configuration",
                "Changing probe insertion/retraction positions changes safety "
                "classification and automatic probe movement targets. Confirm these "
                "positions have been physically checked on this setup.\n\nApply them?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._operator_settings = {
            "rotation_readback_tolerance_deg": self.rotation_tolerance_setting.value(),
            "saturation_warning_counts": self.saturation_setting.value(),
            "probe_in_position_mm": self.probe_in_setting.value(),
            "probe_out_position_mm": self.probe_out_setting.value(),
            "power_measurement_duration_s": self.power_duration_setting.value(),
            "power_settle_time_s": self.power_settle_setting.value(),
            "power_poll_interval_s": self.power_poll_setting.value(),
        }
        if self._settings_enabled:
            for key, value in self._operator_settings.items():
                self.settings.setValue(f"operator/{key}", value)
        self.settings_requested.emit(dict(self._operator_settings))
        self._log("Operator settings applied and remembered.")

    def _reset_operator_settings(self) -> None:
        self.rotation_tolerance_setting.setValue(0.05)
        self.saturation_setting.setValue(65_535.0)
        self.probe_in_setting.setValue(12.0)
        self.probe_out_setting.setValue(-12.0)
        self.power_duration_setting.setValue(10.0)
        self.power_settle_setting.setValue(3.0)
        self.power_poll_setting.setValue(0.1)
        self._apply_operator_settings()

    def _start_worker(self) -> None:
        self.worker_thread = QThread(self)
        self.worker = HardwareWorker()
        self.worker.moveToThread(self.worker_thread)
        self.connect_requested.connect(self.worker.connect_all)
        self.connect_configuration_requested.connect(
            self.worker.connect_all_with_serials
        )
        self.disconnect_requested.connect(self.worker.disconnect_all)
        self.connect_device_requested.connect(self.worker.connect_device)
        self.disconnect_device_requested.connect(self.worker.disconnect_device)
        self.mode_requested.connect(self.worker.set_mode)
        self.settings_requested.connect(self.worker.set_operator_settings)
        self.safe_state_requested.connect(self.worker.safe_state)
        self.close_shutter_requested.connect(self.worker.close_shutter)
        self.open_shutter_requested.connect(self.worker.open_shutter)
        self.move_probe_absolute_requested.connect(self.worker.move_probe_absolute)
        self.home_rotation_requested.connect(self.worker.home_rotation_stage)
        self.reference_pi_requested.connect(self.worker.reference_pi_stage)
        self.move_stage_requested.connect(self.worker.move_stage)
        self.probe_requested.connect(self.worker.set_probe_out)
        self.set_power_requested.connect(self.worker.set_power)
        self.measure_power_requested.connect(self.worker.measure_power)
        self.scan_requested.connect(self.worker.run_scan)
        self.calibration_requested.connect(self.worker.run_calibration)
        self.live_requested.connect(self.worker.run_live_view)
        self.worker.snapshot_changed.connect(self._show_snapshot)
        self.worker.measurement_acquired.connect(self._show_measurement)
        self.worker.log_message.connect(self._log)
        self.worker.operation_failed.connect(self._show_error)
        self.worker.scan_finished.connect(self._scan_finished)
        self.worker.live_spectrum_acquired.connect(self._show_live_spectrum)
        self.worker.live_finished.connect(self._live_finished)
        self.worker.mode_changed.connect(self._mode_changed)
        self.worker.pi_reference_required.connect(self._offer_pi_reference)
        self.worker.calibration_point.connect(self._show_calibration_point)
        self.worker.calibration_finished.connect(self._calibration_finished)
        self.worker_thread.started.connect(self.worker.publish_initial_state)
        self.worker_thread.start()
        self.settings_requested.emit(dict(self._operator_settings))

    def _request_mode_change(self, _index: int) -> None:
        requested = str(self.mode_selector.currentData())
        if requested == self._mode:
            return
        snapshot = self._latest_snapshot
        if snapshot is not None and (snapshot.busy or snapshot.any_connected):
            self._reset_mode_selector()
            self._show_error(
                "Disconnect all devices and stop active operations before changing mode."
            )
            return
        self.mode_selector.setEnabled(False)
        self.mode_requested.emit(requested)

    def _mode_changed(self, mode: str) -> None:
        self._mode = str(mode)
        self.serial_fields.clear()
        self._ever_fully_connected = False
        self._connection_fault = False
        self._reset_mode_selector()
        self._update_mode_visuals()

    def _reset_mode_selector(self) -> None:
        self.mode_selector.blockSignals(True)
        index = self.mode_selector.findData(self._mode)
        if index >= 0:
            self.mode_selector.setCurrentIndex(index)
        self.mode_selector.blockSignals(False)
        snapshot = self._latest_snapshot
        self.mode_selector.setEnabled(
            snapshot is None or (not snapshot.busy and not snapshot.any_connected)
        )

    def _update_mode_visuals(self) -> None:
        hardware = self._mode == "hardware"
        if hardware:
            self.setWindowTitle("Rotation + Intensity Campaign — HARDWARE: ALIGNMENT")
            self.mode_banner.setText(
                "HARDWARE MODE — Ocean SR, rotation stages, and shutter-close are enabled; "
                "PI/Ophir, guarded calibration, angle scans, and bounded target-power scans are enabled"
            )
            self.mode_banner.setStyleSheet(
                "background: #8a1717; color: white; padding: 9px; "
                "font-weight: 700; border-radius: 4px;"
            )
            self.statusBar().showMessage(
                "Hardware mode: connection and manual alignment controls access physical devices."
            )
        else:
            self.setWindowTitle("Rotation + Intensity Campaign — SIMULATION")
            self.mode_banner.setText(
                "SIMULATION MODE — synthetic devices and spectra only; "
                "physical hardware is not imported or connected"
            )
            self.mode_banner.setStyleSheet(
                "background: #17324d; color: white; padding: 9px; "
                "font-weight: 700; border-radius: 4px;"
            )
            self.statusBar().showMessage("Simulation mode: no real devices can connect.")
        if hasattr(self, "tabs"):
            self.live_refresh_label.setText(
                "Refresh rate" if hardware else "Refresh interval"
            )
            self.live_refresh.setEnabled(not hardware)
            self.live_refresh.setToolTip(
                "Hardware live view publishes every spectrum as soon as acquisition finishes."
                if hardware
                else "Delay between synthetic spectra."
            )
            # Calibration remains simulation-only. Angle-controlled Scan Setup
            # and Live Run are available in hardware mode.
            self.tabs.setTabEnabled(2, True)
            self.tabs.setTabEnabled(3, True)
            self.tabs.setTabEnabled(4, True)
            self.run_button.setText(
                "Run guarded hardware scan" if hardware else "Run simulated scan"
            )
            self.calibration_run_button.setText(
                "Run guarded hardware calibration"
                if hardware
                else "Run simulated calibration"
            )
            self.connect_button.setText(
                "Connect alignment devices" if hardware else "Connect configured devices"
            )
            self.live_start_button.setText(
                "Start Ocean SR live view" if hardware else "Start simulated live view"
            )
            for button in self.manual_hardware_buttons + self.alignment_hardware_buttons:
                button.setEnabled(not hardware)
            self.alignment_hardware_group.setEnabled(True)
            if hardware:
                for button in self.manual_stage_buttons + self.alignment_stage_buttons:
                    button.setEnabled(True)
                for button in self.manual_probe_buttons + self.alignment_power_buttons:
                    button.setEnabled(False)
                self.alignment_power_target.setEnabled(False)
            else:
                self.alignment_power_target.setEnabled(True)
            self.safe_button.setEnabled(True)
            self._ensure_button_text_visible()

    def _request_from_form(self) -> ScanRequest:
        return ScanRequest(
            sample_angles_deg=parse_number_list(
                self.sample_angles.text(), field_name="Sample angles"
            ),
            intensity_values=parse_number_list(
                self.intensity_values.text(), field_name="Intensity values"
            ),
            intensity_mode=str(self.intensity_mode.currentData()),
            spectra_per_point=self.spectra_per_point.value(),
            integration_time_ms=self.integration_time.value(),
            averages=self.averages.value(),
            acquire_background=self.background.isChecked(),
            output_directory=Path(self.output_directory.text()).expanduser(),
            experiment_name=self.experiment_name.text().strip(),
            notes=self.notes.toPlainText(),
            waveplate_min_deg=self.target_branch_min.value(),
            waveplate_max_deg=self.target_branch_max.value(),
            monotonic_direction=str(self.target_direction.currentData()),
            target_tolerance_mw=self.target_tolerance.value(),
            target_maximum_iterations=self.target_iterations.value(),
            target_minimum_angle_step_deg=self.target_minimum_step.value(),
            power_calibration_path=(
                Path(self.power_calibration.text()).expanduser()
                if self.power_calibration.text().strip()
                else None
            ),
        )

    def _calibration_request(self) -> CalibrationRequest:
        return CalibrationRequest(
            start_deg=self.calibration_start.value(),
            stop_deg=self.calibration_stop.value(),
            step_deg=self.calibration_step.value(),
            noise_tolerance_mw=self.calibration_noise.value(),
            output_directory=Path(self.calibration_output.text()).expanduser(),
        )

    def _update_calibration_summary(self) -> None:
        try:
            request = self._calibration_request()
        except ValueError as error:
            self.calibration_summary.setText(f"Invalid calibration: {error}")
            self.calibration_run_button.setEnabled(False)
            return
        duration = len(request.angles_deg) * (
            self._operator_settings["power_measurement_duration_s"]
            + self._operator_settings["power_settle_time_s"]
        )
        self.calibration_summary.setText(
            f"{len(request.angles_deg)} bounded waveplate positions; estimated power "
            f"sampling/settling time {duration / 60.0:.1f} min plus motion. "
            "The probe remains inserted during mapping and the waveplate returns "
            "to its starting position. Every trace is saved."
        )
        connected_keys = {
            device.key
            for device in (self._latest_snapshot.devices if self._latest_snapshot else ())
            if device.connection is ConnectionState.CONNECTED
        }
        connected = {"waveplate", "shutter", "power_meter_stage", "power_meter"}.issubset(
            connected_keys
        )
        idle = bool(self._latest_snapshot and not self._latest_snapshot.busy)
        self.calibration_run_button.setEnabled(
            connected and idle and not self._calibration_running
        )

    def _start_calibration(self) -> None:
        self._update_calibration_summary()
        if not self.calibration_run_button.isEnabled():
            return
        request = self._calibration_request()
        if self._mode == "hardware":
            answer = QMessageBox.warning(
                self,
                "Start waveplate calibration",
                f"This will keep the PI probe inserted while moving the waveplate "
                f"through {len(request.angles_deg)} reviewed positions from "
                f"{request.start_deg:g} to {request.stop_deg:g} deg and opening the "
                "shutter for every power trace. Confirm the interval is optically "
                "and mechanically safe and an operator is present. The shutter will "
                "begin and end closed. Start calibration?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._calibration_running = True
        self._calibration_angles.clear()
        self._calibration_powers.clear()
        self.calibration_axes.clear()
        self.calibration_run_button.setEnabled(False)
        self.calibration_requested.emit(request)

    def _show_calibration_point(
        self, angle: float, power: float, completed: int, total: int
    ) -> None:
        self._calibration_angles.append(angle)
        self._calibration_powers.append(power)
        self.calibration_axes.clear()
        self.calibration_axes.plot(
            self._calibration_angles, self._calibration_powers, marker="o"
        )
        self.calibration_axes.set_xlabel("Waveplate angle (deg)")
        self.calibration_axes.set_ylabel("Power (mW)")
        self.calibration_axes.set_title(f"Calibration point {completed} of {total}")
        self.calibration_canvas.draw_idle()

    def _calibration_finished(self, result) -> None:
        self._calibration_running = False
        if result:
            self.target_branch_min.setValue(float(result["branch_min_deg"]))
            self.target_branch_max.setValue(float(result["branch_max_deg"]))
            direction_index = self.target_direction.findData(result["direction"])
            if direction_index >= 0:
                self.target_direction.setCurrentIndex(direction_index)
            self.power_calibration.setText(str(result["calibration_path"]))
            self._log(
                "Calibration complete; recommended branch and calibration file "
                "copied into Scan Setup."
            )
        self._update_calibration_summary()

    def _update_preflight(self) -> bool:
        try:
            request = self._request_from_form()
        except ValueError as error:
            self.preflight_text.setPlainText(f"Invalid configuration:\n{error}")
            self.run_button.setEnabled(False)
            return False
        coordinate = (
            "target powers (mW)"
            if request.intensity_mode == "target_power_mw"
            else "waveplate angles (deg)"
        )
        hardware = self._mode == "hardware"
        unsupported_target = False
        safety_text = (
            "Hardware scan will measure power once per waveplate block, save every "
            "raw trace and spectrum immediately, and end with the shutter closed."
            if hardware
            else "Simulation will end with the shutter closed and probe out."
        )
        if hardware and request.intensity_mode == "target_power_mw":
            safety_text += (
                f"\n\nFeedback is bounded to the reviewed "
                f"[{request.waveplate_min_deg:g}, {request.waveplate_max_deg:g}] deg "
                f"{request.monotonic_direction} branch with +/-"
                f"{request.target_tolerance_mw:g} mW tolerance."
            )
        power_traces = len(request.intensity_values) * (
            4 + request.target_maximum_iterations
            if request.intensity_mode == "target_power_mw"
            else 1
        )
        power_seconds = power_traces * (
            self._operator_settings["power_measurement_duration_s"]
            + self._operator_settings["power_settle_time_s"]
        )
        detector_seconds = (
            request.total_spectra
            * request.integration_time_ms
            * request.averages
            / 1000.0
        )
        identities = ""
        if hardware and self._latest_snapshot:
            identities = "\nDevices: " + ", ".join(
                f"{device.key}={device.identity}" for device in self._latest_snapshot.devices
            )
        self.preflight_text.setPlainText(
            f"{len(request.sample_angles_deg)} sample angles\n"
            f"{len(request.intensity_values)} {coordinate}\n"
            f"{request.spectra_per_point} independent spectra per point\n"
            f"{request.total_spectra} spectra total\n\n"
            f"Estimated acquisition/settling time: at least "
            f"{(power_seconds + detector_seconds) / 60.0:.1f} min plus motion "
            f"({power_traces} maximum power traces).\n"
            f"Configured PI probe: in {self._operator_settings['probe_in_position_mm']:g} mm, "
            f"out {self._operator_settings['probe_out_position_mm']:g} mm."
            f"{identities}\n\n"
            f"{safety_text}\n"
            f"Every completed spectrum will be saved under:\n{request.output_directory}"
        )
        connected = bool(self._latest_snapshot and self._latest_snapshot.all_connected)
        idle = bool(self._latest_snapshot and not self._latest_snapshot.busy)
        self.run_button.setEnabled(
            connected and idle and not self._scan_running and not unsupported_target
        )
        if not connected:
            self.run_button.setToolTip("Connect all configured scan devices first.")
        elif not idle or self._scan_running:
            self.run_button.setToolTip("Wait for the active operation to finish.")
        else:
            self.run_button.setToolTip("")
        return not unsupported_target

    def _start_scan(self) -> None:
        if not self._update_preflight():
            return
        request = self._request_from_form()
        if not self._latest_snapshot or not self._latest_snapshot.all_connected:
            self._show_error("Connect all configured devices before starting a scan.")
            return
        if self._mode == "hardware":
            answer = QMessageBox.warning(
                self,
                "Start hardware scan",
                "This scan will move both rotation stages, insert and retract the PI "
                "power probe, open the laser shutter for power and spectrum acquisition, "
                "and save data incrementally. Confirm the requested angles are safe, the "
                "optical path is clear, and an operator is present.\n\nThe shutter will "
                "begin and end closed. Start the scan?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._scan_running = True
        self._quick_x.clear()
        self._quick_y.clear()
        self.progress.setRange(0, request.total_spectra)
        self.progress.setValue(0)
        self.run_status.setText(
            "Hardware scan running" if self._mode == "hardware" else "Simulated scan running"
        )
        self.cancel_button.setEnabled(True)
        self.run_button.setEnabled(False)
        self.tabs.setCurrentWidget(self.live_run_page)
        self.scan_requested.emit(request)

    def _cancel_scan(self) -> None:
        self.worker.request_cancel()
        self.cancel_button.setEnabled(False)
        self._log("Cancellation requested; waiting for the next safe point.")

    def _request_safe_state(self) -> None:
        self.worker.request_cancel()
        if self._scan_running:
            self._log("Cancellation requested for active scan/motion.")
        if self._live_running:
            self.worker.request_live_stop()
        self.safe_state_requested.emit()

    def _request_shutter(self, open_shutter: bool) -> None:
        override = False
        if open_shutter and not (
            self._latest_snapshot and self._latest_snapshot.probe_out is True
        ):
            if self._live_running:
                self._show_error(
                    "Stop live spectrum acquisition before overriding the probe-out "
                    "shutter interlock."
                )
                return
            answer = QMessageBox.warning(
                self,
                "Unsafe shutter override",
                "The power probe is not live-verified out. Opening the shutter may "
                "expose the probe, sample, or personnel to the beam. Confirm the "
                "optical path manually.\n\nOpen the shutter anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            override = True
        if self._live_running:
            self.worker.queue_live_shutter(open_shutter)
        elif open_shutter:
            self.open_shutter_requested.emit(override)
        else:
            self.close_shutter_requested.emit()

    def _request_pi_move(self, position_mm: float) -> None:
        if self._live_running:
            self._show_error("Stop live acquisition before moving the PI stage.")
            return
        answer = QMessageBox.warning(
            self,
            "Confirm PI stage movement",
            f"The shutter will be closed and verified before moving the PI stage "
            f"to {position_mm:.4f} mm. Confirm the path is mechanically clear.\n\n"
            "Proceed with movement?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.move_probe_absolute_requested.emit(float(position_mm))

    def _request_pi_reference(self) -> None:
        self._offer_pi_reference(
            "Manual PI reference requested. The stage will move to its optical "
            "reference switch."
        )

    def _offer_pi_reference(self, reason: str) -> None:
        answer = QMessageBox.warning(
            self,
            "Reference PI stage",
            f"{reason}\n\nThe shutter will be closed and verified. The PI stage may "
            "travel substantially toward its reference switch. Confirm the full path "
            "is clear and remain at the apparatus.\n\nStart referencing?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._log("Operator approved PI FRF reference-switch workflow.")
            self.reference_pi_requested.emit()
        else:
            self._log("PI referencing was required/offered but not approved.")

    def _request_rotation_home(self, stage: str) -> None:
        answer = QMessageBox.warning(
            self,
            f"Home {stage} stage",
            f"The shutter will be closed and verified, then the {stage} stage will "
            "run its hardware homing routine. Confirm cables and mounts can traverse "
            "the full homing path.\n\nStart homing?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._log(f"Operator approved {stage} hardware homing.")
            self.home_rotation_requested.emit(stage)

    def _alignment_move(self, stage: str, position: float) -> None:
        connected = bool(
            self._latest_snapshot
            and any(
                device.key == stage
                and device.connection is ConnectionState.CONNECTED
                for device in self._latest_snapshot.devices
            )
        )
        if not connected:
            self._show_error(f"Connect the {stage} stage before moving it.")
            return
        if self._live_running:
            self.worker.queue_live_stage_move(stage, position)
        else:
            self.move_stage_requested.emit(stage, position)

    def _alignment_set_power(self) -> None:
        if not self._require_alignment_connection():
            return
        target = self.alignment_power_target.value()
        if self._live_running:
            self.worker.queue_live_set_power(target)
        else:
            self.set_power_requested.emit(target)

    def _alignment_measure_power(self) -> None:
        if not self._require_alignment_connection():
            return
        if self._live_running:
            self.worker.queue_live_measure_power()
        else:
            self.measure_power_requested.emit()

    def _require_alignment_connection(self) -> bool:
        if self._latest_snapshot and self._latest_snapshot.all_connected:
            return True
        self._show_error("Connect the simulated hardware before alignment control.")
        return False

    def _start_live_view(self) -> None:
        if not self._latest_snapshot or not self._latest_snapshot.all_connected:
            self._show_error(
                "Connect the simulated hardware before starting live view."
            )
            return
        if self._latest_snapshot.busy:
            self._show_error("Another simulated hardware operation is active.")
            return
        request = LiveViewRequest(
            integration_time_ms=self.live_integration_time.value(),
            averages=self.live_averages.value(),
            refresh_interval_s=self.live_refresh.value(),
            saturation_level=self._operator_settings["saturation_warning_counts"],
            output_directory=Path(self.live_output.text()).expanduser(),
        )
        self._live_running = True
        self.live_start_button.setEnabled(False)
        self.live_stop_button.setEnabled(True)
        self.live_capture_background.setEnabled(True)
        self.live_save_button.setEnabled(True)
        self.live_status.setText(
            "Streaming Ocean SR spectra as fast as acquisition allows…"
            if self._mode == "hardware"
            else "Streaming synthetic spectra…"
        )
        self.live_requested.emit(request)

    def _stop_live_view(self) -> None:
        self.worker.request_live_stop()
        self.live_stop_button.setEnabled(False)
        self.live_capture_background.setEnabled(False)
        self.live_background_enabled.setEnabled(False)
        self.live_save_button.setEnabled(False)
        self.live_status.setText("Stopping after the current acquisition…")

    def _live_finished(self) -> None:
        self._live_running = False
        self.live_stop_button.setEnabled(False)
        connected = bool(self._latest_snapshot and self._latest_snapshot.all_connected)
        probe_safe = bool(
            self._mode != "hardware"
            or (self._latest_snapshot and self._latest_snapshot.probe_out is True)
        )
        self.live_start_button.setEnabled(connected and probe_safe)
        self.live_status.setText("Live view stopped")

    def _queue_live_settings(self) -> None:
        if self._live_running:
            self.worker.queue_live_settings(
                self.live_integration_time.value(),
                self.live_averages.value(),
            )

    def _show_live_spectrum(self, raw, displayed, metadata: dict) -> None:
        self._latest_live_spectrum = displayed
        available = bool(metadata.get("background_available"))
        enabled = bool(metadata.get("background_enabled"))
        self.live_background_enabled.blockSignals(True)
        self.live_background_enabled.setChecked(enabled)
        self.live_background_enabled.setEnabled(available)
        self.live_background_enabled.blockSignals(False)
        saturation = "SATURATED" if metadata.get("saturated") else "OK"
        self.live_status.setText(
            f"Frame {metadata.get('frame', 0) + 1}  |  "
            f"Peak {raw.maximum:.0f} counts  |  {saturation}  |  "
            f"Background {'ON' if enabled else 'OFF'}"
        )
        self._redraw_alignment()

    def _redraw_alignment(self) -> None:
        spectrum = self._latest_live_spectrum
        if spectrum is None:
            return
        self.alignment_axes.clear()
        self.alignment_axes.plot(
            spectrum.wavelengths,
            spectrum.intensities,
            lw=1.2,
            color="#1769aa",
        )
        self.alignment_axes.set_xlabel("Wavelength (nm)")
        self.alignment_axes.set_ylabel("Counts")
        self.alignment_axes.set_title(
            f"{'Ocean SR' if self._mode == 'hardware' else 'Simulated Ocean SR'} — "
            f"{spectrum.integration_time_ms:g} ms, "
            f"{spectrum.averages} average(s)"
        )
        try:
            x_limits = self._optional_limits(self.live_x_min, self.live_x_max)
            y_limits = self._optional_limits(self.live_y_min, self.live_y_max)
        except ValueError as error:
            self.statusBar().showMessage(str(error), 4000)
            return
        if x_limits is not None:
            self.alignment_axes.set_xlim(*x_limits)
        if not self.live_autoscale.isChecked() and y_limits is not None:
            self.alignment_axes.set_ylim(*y_limits)
        self.alignment_axes.grid(True, alpha=0.25)
        self.alignment_canvas.draw_idle()

    def _show_snapshot(self, snapshot: GuiSnapshot) -> None:
        self._latest_snapshot = snapshot
        hardware = self._mode == "hardware"
        if snapshot.all_connected:
            self._ever_fully_connected = True
            self._connection_fault = False
        self.connection_badge.setText(
            ("ALIGNMENT  CONNECTED" if hardware else "HARDWARE  CONNECTED")
            if snapshot.all_connected
            else ("ALIGNMENT  PARTIAL" if hardware else "HARDWARE  PARTIAL")
            if snapshot.any_connected
            else ("ALIGNMENT  DISCONNECTED" if hardware else "HARDWARE  DISCONNECTED")
        )
        self.shutter_badge.setText("SHUTTER  NOT ENABLED" if hardware else (
            "SHUTTER  CLOSED"
            if snapshot.shutter_closed is True
            else "SHUTTER  OPEN"
            if snapshot.shutter_closed is False
            else "SHUTTER  UNKNOWN"
        ))
        self.probe_badge.setText("PROBE  NOT ENABLED" if hardware else (
            "PROBE  OUT"
            if snapshot.probe_out is True
            else "PROBE  NOT OUT"
            if snapshot.probe_out is False
            else "PROBE  UNKNOWN"
        ))
        self.power_badge.setText("POWER  NOT ENABLED" if hardware else (
            "POWER  --"
            if snapshot.beam_power_mw is None
            else f"POWER  {snapshot.beam_power_mw:.3f} mW"
        ))
        waveplate_value = next(
            (
                device.value
                for device in snapshot.devices
                if device.key == "waveplate"
            ),
            "--",
        )
        sample_value = next(
            (device.value for device in snapshot.devices if device.key == "sample"),
            "--",
        )
        power_value = (
            "--"
            if snapshot.beam_power_mw is None
            else f"{snapshot.beam_power_mw:.3f} mW"
        )
        self.alignment_hardware_status.setText(
            f"Waveplate {waveplate_value}  |  Sample {sample_value}  |  "
            f"Measured power {power_value}"
        )
        connection_colour = (
            "safe"
            if snapshot.all_connected
            else "danger"
            if self._ever_fully_connected or self._connection_fault
            else "warning"
            if snapshot.any_connected
            else "unknown"
        )
        self._colour_badge(self.connection_badge, connection_colour)
        if snapshot.all_connected:
            self._set_connection_health("safe", "ALL CONNECTED")
        elif self._ever_fully_connected or self._connection_fault:
            self._set_connection_health("danger", "CONNECTION LOST")
        elif snapshot.any_connected:
            self._set_connection_health("warning", "PARTIAL")
        else:
            self._set_connection_health("unknown", "NOT CONNECTED")
        self._colour_badge(
            self.shutter_badge,
            "safe" if snapshot.shutter_closed is True else "danger",
        )
        self._colour_badge(
            self.probe_badge, "safe" if snapshot.probe_out is True else "warning"
        )
        self.device_table.setRowCount(len(snapshot.devices))
        for row, device in enumerate(snapshot.devices):
            connection_text = (
                device.connection.value.upper() if device.available else "DISABLED"
            )
            values = (
                device.name,
                connection_text,
                device.value,
                device.detail,
            )
            for column, value in enumerate(values):
                actual_column = column if column < 2 else column + 1
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if actual_column == 1:
                    item.setForeground(
                        QColor("#1b7f3a")
                        if device.connection is ConnectionState.CONNECTED
                        else QColor("#666666")
                    )
                self.device_table.setItem(row, actual_column, item)
            serial_field = self.serial_fields.get(device.key)
            if serial_field is None:
                remembered = (
                    str(
                        self.settings.value(
                            self._serial_setting_key(device.key),
                            device.identity,
                        )
                    )
                    if self._settings_enabled
                    else device.identity
                )
                serial_field = QLineEdit(remembered)
                serial_field.setMinimumWidth(150)
                serial_field.setToolTip(
                    "Device identity. Disconnect before changing the identity "
                    "of a connected device."
                )
                serial_field.editingFinished.connect(
                    lambda key=device.key, field=serial_field: self._remember_serial(
                        key, field.text()
                    )
                )
                self.serial_fields[device.key] = serial_field
            self.device_table.setCellWidget(row, 2, serial_field)
            serial_field.setEnabled(
                device.available
                and device.connection is not ConnectionState.CONNECTED
                and not snapshot.busy
            )
            connect = QPushButton("Connect")
            connect.setEnabled(
                device.connection is not ConnectionState.CONNECTED
                and device.available
                and not snapshot.busy
            )
            connect.clicked.connect(
                lambda checked=False, key=device.key: self._connect_one(key)
            )
            disconnect = QPushButton("Disconnect")
            disconnect.setEnabled(
                device.connection is ConnectionState.CONNECTED
                and not snapshot.busy
            )
            disconnect.clicked.connect(
                lambda checked=False, key=device.key: self._disconnect_one(key)
            )
            self.device_table.setCellWidget(row, 5, connect)
            self.device_table.setCellWidget(row, 6, disconnect)
            self.device_table.setRowHeight(row, 42)
        self.connect_button.setEnabled(not snapshot.all_connected and not snapshot.busy)
        self.disconnect_button.setEnabled(snapshot.any_connected and not snapshot.busy)
        shutter_connected = any(
            device.key == "shutter"
            and device.connection is ConnectionState.CONNECTED
            for device in snapshot.devices
        )
        self.close_shutter_button.setEnabled(shutter_connected)
        can_request_open = bool(shutter_connected and not snapshot.busy)
        for button in (self.devices_open_shutter, self.alignment_open_shutter):
            button.setEnabled(can_request_open or self._live_running)
            button.setToolTip(
                "Opens directly when probe-out is verified; otherwise requires a warning override."
            )
        for button in (self.devices_close_shutter, self.alignment_close_shutter):
            button.setEnabled(shutter_connected)
        connected_keys = {
            device.key for device in snapshot.devices
            if device.connection is ConnectionState.CONNECTED
        }
        pi_connected = "power_meter_stage" in {
            device.key
            for device in snapshot.devices
            if device.connection is ConnectionState.CONNECTED
        }
        for button in (self.devices_pi_move, self.alignment_pi_move):
            button.setEnabled(pi_connected and not snapshot.busy)
        power_meter_connected = "power_meter" in connected_keys
        self.alignment_measure_power_button.setEnabled(
            (not hardware)
            or (
                shutter_connected
                and pi_connected
                and power_meter_connected
                and not snapshot.busy
                and not self._live_running
            )
        )
        if hardware:
            self.alignment_set_power_button.setEnabled(False)
        for button in (self.devices_reference_pi, self.alignment_reference_pi):
            button.setEnabled(pi_connected and not snapshot.busy)
        for button in (self.devices_home_waveplate, self.alignment_home_waveplate):
            button.setEnabled("waveplate" in connected_keys and not snapshot.busy)
        for button in (self.devices_home_sample, self.alignment_home_sample):
            button.setEnabled("sample" in connected_keys and not snapshot.busy)
        if hardware:
            for button in self.manual_probe_buttons:
                button.setEnabled(pi_connected and not snapshot.busy)
        if hardware:
            connected_keys = {
                device.key
                for device in snapshot.devices
                if device.connection is ConnectionState.CONNECTED
            }
            for button in (self.manual_stage_buttons[0], self.alignment_stage_buttons[0]):
                button.setEnabled("waveplate" in connected_keys and not snapshot.busy)
            for button in (self.manual_stage_buttons[1], self.alignment_stage_buttons[1]):
                button.setEnabled("sample" in connected_keys and not snapshot.busy)
            self.safe_button.setEnabled(bool(connected_keys))
        self.live_start_button.setEnabled(
            snapshot.all_connected
            and (not hardware or snapshot.probe_out is True)
            and not snapshot.busy
            and not self._live_running
        )
        if hardware and snapshot.probe_out is not True:
            self.live_start_button.setToolTip(
                "Move the PI probe to the configured retraction position before acquisition."
            )
        else:
            self.live_start_button.setToolTip("")
        self._ensure_button_text_visible()
        self._reset_mode_selector()
        self._update_preflight()
        self._update_calibration_summary()

    def _connect_one(self, key: str) -> None:
        serial = self.serial_fields[key].text().strip()
        self._remember_serial(key, serial)
        self._log(f"Requesting connection to {key} using identity {serial!r}.")
        self.connect_device_requested.emit(key, serial)

    def _connect_all_from_fields(self) -> None:
        serials = {
            key: field.text().strip()
            for key, field in self.serial_fields.items()
        }
        empty = sorted(key for key, value in serials.items() if not value)
        if empty:
            self._show_error(
                "Serial/identity fields must not be empty: " + ", ".join(empty)
            )
            return
        for key, serial in serials.items():
            self._remember_serial(key, serial)
        self._log(
            "Requesting connection to the Ocean SR."
            if self._mode == "hardware"
            else "Requesting connection to all configured simulated devices."
        )
        self.connect_configuration_requested.emit(serials)

    def _disconnect_one(self, key: str) -> None:
        self._log(f"Requesting safe disconnect of {key}.")
        self.disconnect_device_requested.emit(key)

    def _safe_disconnect_all(self) -> None:
        self._log(
            "Requesting Ocean SR disconnect."
            if self._mode == "hardware"
            else "Requesting safe disconnect of the complete simulated stack."
        )
        self._ever_fully_connected = False
        self._connection_fault = False
        self.disconnect_requested.emit()

    def _remember_serial(self, key: str, serial: str) -> None:
        if self._settings_enabled:
            self.settings.setValue(self._serial_setting_key(key), str(serial).strip())

    def _serial_setting_key(self, key: str) -> str:
        return f"devices/{self._mode}/{key}/serial"

    def _show_measurement(self, measurement, completed: int, total: int) -> None:
        spectrum = measurement.spectrum
        self.spectrum_axes.clear()
        self.spectrum_axes.plot(spectrum.wavelengths, spectrum.intensities, lw=1.2)
        self.spectrum_axes.set_title(
            f"Latest: sample {measurement.sample_angle_deg:.2f} deg, "
            f"power {measurement.power_mw:.3f} mW"
        )
        self.spectrum_axes.set_xlabel("Wavelength (nm)")
        self.spectrum_axes.set_ylabel("Counts")
        self._quick_x.append(measurement.sample_angle_deg)
        self._quick_y.append(float(measurement.integrated_counts or 0.0))
        self.scan_axes.clear()
        self.scan_axes.scatter(self._quick_x, self._quick_y, s=18)
        self.scan_axes.set_title("Completed scan points (quick look)")
        self.scan_axes.set_xlabel("Sample angle (deg)")
        self.scan_axes.set_ylabel("Integrated counts")
        self.canvas.draw_idle()
        self.progress.setValue(completed)
        self.run_status.setText(f"Spectrum {completed} of {total}")

    def _scan_finished(self, completed: bool) -> None:
        self._scan_running = False
        self.cancel_button.setEnabled(False)
        self.run_status.setText(
            ("Hardware scan complete" if self._mode == "hardware" else "Simulation complete")
            if completed
            else "Scan cancelled safely"
        )
        self._update_preflight()

    def _show_error(self, message: str) -> None:
        if any(
            word in message.lower()
            for word in ("connect", "hardware", "move verification")
        ):
            self._connection_fault = True
            self._set_connection_health("danger", "OPERATION ERROR")
        self._log(f"ERROR: {message}")
        QMessageBox.critical(self, "Campaign GUI", message)

    def _log(self, message: str) -> None:
        if str(message).startswith("ERROR:"):
            self._connection_fault = True
            self._set_connection_health("danger", "OPERATION ERROR")
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"{timestamp}  {message}"
        self.event_log.appendPlainText(entry)
        self.device_log.appendPlainText(entry)

    def _browse_output(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Choose output directory", self.output_directory.text()
        )
        if directory:
            self.output_directory.setText(directory)
            self._update_preflight()

    def _browse_live_output(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Choose live-spectrum save directory", self.live_output.text()
        )
        if directory:
            self.live_output.setText(directory)

    def _browse_experiment(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Choose saved experiment", str(Path("results").resolve())
        )
        if directory:
            self.data_path.setText(directory)

    def _load_summary(self) -> None:
        try:
            dataset = load_experiment(Path(self.data_path.text()))
        except Exception as error:
            self._show_error(f"Could not load experiment: {error}")
            return
        summary = dataset.summary()
        lines = [f"{key}: {value}" for key, value in summary.items()]
        if dataset.measurements:
            latest = dataset.measurements[-1]
            lines.extend(
                [
                    "",
                    f"Last sample angle: {latest.sample_angle_deg:g} deg",
                    f"Last waveplate angle: {latest.waveplate_angle_deg:g} deg",
                    f"Last achieved power: {latest.power_mw}",
                ]
            )
        self.data_summary.setPlainText("\n".join(lines))

    @staticmethod
    def _angle_box() -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(-360_000.0, 360_000.0)
        box.setDecimals(4)
        box.setSuffix(" deg")
        return box

    @staticmethod
    def _pi_position_box() -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(
            float(POWER_METER_STAGE.application_min_mm),
            float(POWER_METER_STAGE.application_max_mm),
        )
        box.setDecimals(4)
        box.setSingleStep(0.1)
        box.setSuffix(" mm")
        return box

    @staticmethod
    def _configure_form(form: QFormLayout) -> None:
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

    @staticmethod
    def _optional_limits(
        minimum_field: QLineEdit,
        maximum_field: QLineEdit,
    ) -> tuple[float, float] | None:
        minimum_text = minimum_field.text().strip()
        maximum_text = maximum_field.text().strip()
        if not minimum_text and not maximum_text:
            return None
        if not minimum_text or not maximum_text:
            raise ValueError("Both lower and upper plot limits are required.")
        minimum = float(minimum_text)
        maximum = float(maximum_text)
        if not np.isfinite(minimum) or not np.isfinite(maximum) or maximum <= minimum:
            raise ValueError("Plot limits must be finite with upper > lower.")
        return minimum, maximum

    @staticmethod
    def _section_font() -> QFont:
        font = QApplication.font()
        font.setPointSize(font.pointSize() + 3)
        font.setBold(True)
        return font

    @staticmethod
    def _colour_badge(label: QLabel, state: str) -> None:
        colours = {
            "safe": ("#d9f3df", "#155b2b"),
            "warning": ("#fff0c2", "#755400"),
            "danger": ("#ffd9d9", "#8a1717"),
            "unknown": ("#e8e8e8", "#555555"),
        }
        background, foreground = colours[state]
        label.setStyleSheet(
            f"background: {background}; color: {foreground}; padding: 8px; "
            "border-radius: 4px; font-weight: 700;"
        )

    def _set_connection_health(self, state: str, text: str) -> None:
        colours = {
            "safe": "#1f9d55",
            "warning": "#e0a100",
            "danger": "#d12f2f",
            "unknown": "#8a929a",
        }
        colour = colours[state]
        self.connection_light.setStyleSheet(
            f"background: {colour}; border: 2px solid #ffffff; "
            "border-radius: 10px;"
        )
        self.connection_health_text.setText(text)
        self.connection_health_text.setStyleSheet(
            f"color: {colour}; font-weight: 800;"
        )

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background: #f4f6f8; }
            QGroupBox { font-weight: 600; border: 1px solid #c7ccd1;
                        border-radius: 6px; margin-top: 10px; padding-top: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QPushButton { padding: 7px 12px; }
            #safeButton { background: #b42318; color: white; font-weight: 700; }
            #runButton { background: #1769aa; color: white; font-weight: 700;
                         padding: 12px; }
            #notice { background: #fff0c2; color: #5e4700; padding: 12px;
                      border-radius: 4px; }
            """
        )

    def _ensure_button_text_visible(self) -> None:
        """Reserve the full label width under Windows display scaling."""

        for button in self.findChildren(QPushButton):
            button.setSizePolicy(
                QSizePolicy.Policy.MinimumExpanding,
                QSizePolicy.Policy.Fixed,
            )
            button.setMinimumWidth(max(button.minimumWidth(), button.sizeHint().width() + 18))
            button.setMinimumHeight(max(button.minimumHeight(), 34))
        for field in self.findChildren(QLineEdit):
            field.setMinimumHeight(max(field.minimumHeight(), field.sizeHint().height()))
        for box in self.findChildren(QSpinBox):
            box.setMinimumHeight(max(box.minimumHeight(), box.sizeHint().height()))
        for box in self.findChildren(QDoubleSpinBox):
            box.setMinimumHeight(max(box.minimumHeight(), box.sizeHint().height()))
        for combo in self.findChildren(QComboBox):
            combo.setMinimumHeight(max(combo.minimumHeight(), combo.sizeHint().height()))

    def audit_visible_layout(self) -> list[str]:
        """Return actionable geometry problems for the currently visible tab."""

        issues: list[str] = []
        for button in self.findChildren(QPushButton):
            if button.isVisible() and button.width() < button.sizeHint().width():
                issues.append(f"Button text clipped: {button.text()!r}")
        for field in self.findChildren(QLineEdit):
            if field.isVisible() and field.height() < field.sizeHint().height():
                issues.append(
                    f"Text field clipped: {field.placeholderText() or field.objectName()!r}"
                )
        if self.connection_light.isVisible() and self.connection_light.visibleRegion().isEmpty():
            issues.append("Connection-health light is not visible.")
        if self.tabs.currentWidget() is self.alignment_page:
            if self.alignment_canvas.width() < 320 or self.alignment_canvas.height() < 240:
                issues.append("Alignment plot is too small for reliable use.")
        if self.tabs.currentWidget() is self.live_run_page:
            if self.canvas.width() < 320 or self.canvas.height() < 240:
                issues.append("Live-run plot is too small for reliable use.")
        return issues

    def _restore_window_state(self) -> None:
        geometry = self.settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        tab_index = int(self.settings.value("window/tab_index", 0))
        if 0 <= tab_index < self.tabs.count():
            self.tabs.setCurrentIndex(tab_index)
        if self.settings.value("window/maximized", False, type=bool):
            self.showMaximized()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showMaximized()
        else:
            self.showFullScreen()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._scan_running:
            self.worker.request_cancel()
        if self._live_running:
            self.worker.request_live_stop()
        self.worker_thread.quit()
        if not self.worker_thread.wait(3000):
            QMessageBox.warning(
                self,
                "Campaign GUI",
                "The simulation worker did not stop promptly. The window will remain open.",
            )
            event.ignore()
            return
        if self._settings_enabled:
            self.settings.setValue("window/geometry", self.saveGeometry())
            self.settings.setValue("window/tab_index", self.tabs.currentIndex())
            self.settings.setValue("window/maximized", self.isMaximized())
        event.accept()
