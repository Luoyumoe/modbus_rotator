from __future__ import annotations

from typing import Any

from PySide6.QtCore import QProcess, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QDoubleSpinBox,
    QDockWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import ConfigStore
from ..integrations.com0com import Com0ComManager
from ..motion import MotionPlanner
from .compass import CompassWidget


class MainWindow(QMainWindow):
    integration_log = Signal(str)

    def __init__(self, config_store: ConfigStore, worker: Any, planner: MotionPlanner, services: Any | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config_store = config_store
        self.worker = worker
        self.planner = planner
        self.services = services
        self.setWindowTitle("Modbus Rotator")
        self.resize(1100, 760)
        self._build_ui()
        self._connect_worker()
        self._refresh_from_config()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        header = QHBoxLayout()
        self.connection_label = QLabel("OFFLINE")
        self.connection_label.setObjectName("connectionLabel")
        header.addWidget(QLabel("MODBUS ROTATOR"))
        header.addStretch()
        self.debug_toggle = QPushButton("Debug terminal")
        self.debug_toggle.setCheckable(True)
        header.addWidget(self.debug_toggle)
        header.addWidget(self.connection_label)
        outer.addLayout(header)

        body = QHBoxLayout()
        self.compass = CompassWidget()
        body.addWidget(self.compass, 2)
        side = QVBoxLayout()
        self.current_label = QLabel("000.0 deg")
        self.current_label.setObjectName("currentAngle")
        side.addWidget(QLabel("CURRENT AZIMUTH"))
        side.addWidget(self.current_label)
        self.target_label = QLabel("Target: --")
        side.addWidget(self.target_label)
        presets = QGridLayout()
        for index, (name, angle) in enumerate(
            (("N", 0), ("NE", 45), ("E", 90), ("SE", 135), ("S", 180), ("SW", 225), ("W", 270), ("NW", 315), ("EU", 320), ("NA", 35), ("JA", 65), ("OC", 150))
        ):
            button = QPushButton(name)
            button.setToolTip(f"Set target {angle} degrees")
            button.clicked.connect(lambda _checked=False, value=angle: self.submit_target(value))
            presets.addWidget(button, index // 4, index % 4)
        side.addLayout(presets)
        stop_button = QPushButton("STOP")
        stop_button.setObjectName("stopButton")
        stop_button.clicked.connect(self.stop_motion)
        side.addWidget(stop_button)
        side.addStretch()
        body.addLayout(side, 1)
        outer.addLayout(body, 1)

        self.tabs = QTabWidget()
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setWidget(self._settings_page())
        self.tabs.addTab(settings_scroll, "Settings")
        outer.addWidget(self.tabs)
        self.debug_dock = QDockWidget("Debug terminal", self)
        self.debug_dock.setObjectName("debugDock")
        self.debug_dock.setWidget(self._debug_page())
        self.debug_dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.debug_dock)
        self.debug_dock.hide()
        self.debug_toggle.toggled.connect(self.debug_dock.setVisible)
        self.debug_dock.visibilityChanged.connect(self.debug_toggle.setChecked)
        status = QHBoxLayout()
        self.run_status = QLabel("STOPPED")
        self.temperature_label = QLabel("Temp --")
        self.limit_label = QLabel("Limits")
        self.s0_indicator = self._indicator("S0")
        self.s1_indicator = self._indicator("S1")
        self.s2_indicator = self._indicator("S2")
        status.addWidget(self.run_status)
        status.addWidget(self.temperature_label)
        status.addWidget(self.limit_label)
        status.addWidget(self.s0_indicator)
        status.addWidget(self.s1_indicator)
        status.addWidget(self.s2_indicator)
        status.addStretch()
        outer.addLayout(status)

    def _settings_page(self) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        cfg = self.config_store.config
        self.port_edit = QLineEdit(cfg.serial_port)
        layout.addRow("Serial port", self.port_edit)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.baud_combo.setCurrentText(str(cfg.baudrate))
        layout.addRow("Baudrate", self.baud_combo)
        self.slave_spin = QSpinBox(); self.slave_spin.setRange(1, 247); self.slave_spin.setValue(cfg.slave_id)
        layout.addRow("Slave ID", self.slave_spin)
        self.timeout_spin = QDoubleSpinBox(); self.timeout_spin.setRange(0.1, 10); self.timeout_spin.setSingleStep(0.1); self.timeout_spin.setValue(cfg.timeout_s)
        layout.addRow("Timeout (s)", self.timeout_spin)
        self.span_spin = QDoubleSpinBox(); self.span_spin.setRange(1, 450); self.span_spin.setValue(cfg.rotation_span_deg)
        self.stop_point_spin = QDoubleSpinBox(); self.stop_point_spin.setRange(-720, 720); self.stop_point_spin.setValue(cfg.stop_point_deg)
        layout.addRow("Rotation span", self.span_spin)
        layout.addRow("Stop point", self.stop_point_spin)
        self.calibrate_angle = QDoubleSpinBox()
        self.calibrate_angle.setRange(0.0, 359.9)
        self.calibrate_angle.setDecimals(1)
        self.calibrate_angle.setSuffix(" deg")
        calibrate_row = QHBoxLayout()
        calibrate_row.addWidget(self.calibrate_angle)
        calibrate_button = QPushButton("Calibrate current position")
        calibrate_button.clicked.connect(self._calibrate_current)
        north_button = QPushButton("Return north")
        north_button.clicked.connect(lambda: self.submit_target(0.0))
        calibrate_row.addWidget(calibrate_button)
        calibrate_row.addWidget(north_button)
        layout.addRow("Azimuth calibration", calibrate_row)
        self.simulate_check = QCheckBox("Simulation backend")
        self.simulate_check.setChecked(cfg.simulate)
        layout.addRow(self.simulate_check)
        registers = cfg.registers
        self.f08_spin = self._register_spin(registers.smoothing_f08)
        self.f04_spin = self._register_spin(registers.max_frequency_f04)
        self.f05_spin = self._register_spin(registers.min_frequency_f05)
        self.p2_spin = self._register_spin(registers.forward_speed_p2)
        self.p4_spin = self._register_spin(registers.reverse_speed_p4)
        self.f13_spin = self._register_spin(registers.soft_stop_f13)
        self.f14_spin = self._register_spin(registers.enable_f14)
        layout.addRow("F-08 smoothing", self.f08_spin)
        layout.addRow("F-04 max frequency", self.f04_spin)
        layout.addRow("F-05 min frequency", self.f05_spin)
        layout.addRow("P-2 forward speed", self.p2_spin)
        layout.addRow("P-4 reverse speed", self.p4_spin)
        layout.addRow("F-13 soft stop", self.f13_spin)
        layout.addRow("F-14 enable", self.f14_spin)
        self.stop_trigger_spin = self._register_spin(registers.stop_trigger)
        self.forward_trigger_spin = self._register_spin(registers.forward_trigger)
        self.reverse_trigger_spin = self._register_spin(registers.reverse_trigger)
        layout.addRow("Stop trigger", self.stop_trigger_spin)
        layout.addRow("Forward trigger", self.forward_trigger_spin)
        layout.addRow("Reverse trigger", self.reverse_trigger_spin)
        network = cfg.network
        self.n1mm_check = QCheckBox("N1MM UDP")
        self.n1mm_check.setChecked(network.n1mm_enabled)
        self.n1mm_host = QLineEdit(network.n1mm_host)
        self.n1mm_port = self._port_spin(network.n1mm_port)
        layout.addRow(self.n1mm_check, self.n1mm_host)
        layout.addRow("N1MM port", self.n1mm_port)
        self.hamlib_check = QCheckBox("Hamlib rotctld")
        self.hamlib_check.setChecked(network.hamlib_enabled)
        self.hamlib_host = QLineEdit(network.hamlib_host)
        self.hamlib_port = self._port_spin(network.hamlib_port)
        layout.addRow(self.hamlib_check, self.hamlib_host)
        layout.addRow("Hamlib port", self.hamlib_port)
        self.gs232_check = QCheckBox("GS-232B")
        self.gs232_check.setChecked(network.gs232_enabled)
        self.gs232_port = QLineEdit(network.gs232_port)
        self.gs232_baudrate = self._port_spin(network.gs232_baudrate)
        layout.addRow(self.gs232_check, self.gs232_port)
        layout.addRow("GS-232 baud", self.gs232_baudrate)
        network_buttons = QHBoxLayout()
        self.network_apply_button = QPushButton("Apply network services")
        self.network_apply_button.clicked.connect(self._apply_network_services)
        self.network_stop_button = QPushButton("Stop network services")
        self.network_stop_button.clicked.connect(self._stop_network_services)
        network_buttons.addWidget(self.network_apply_button)
        network_buttons.addWidget(self.network_stop_button)
        layout.addRow(network_buttons)
        self.com0com_manager = Com0ComManager()
        self.com0com_status = QLabel("com0com status unknown")
        com0com_buttons = QHBoxLayout()
        check_com0com = QPushButton("Check com0com")
        check_com0com.clicked.connect(self._check_com0com)
        create_pair = QPushButton("Create COM10/COM11")
        create_pair.clicked.connect(self._create_com0com_pair)
        com0com_buttons.addWidget(check_com0com)
        com0com_buttons.addWidget(create_pair)
        layout.addRow(self.com0com_status)
        layout.addRow(com0com_buttons)
        self.com0com_process = QProcess(self)
        self.com0com_process.finished.connect(self._com0com_finished)
        self.com0com_process.errorOccurred.connect(self._com0com_error)
        self.apply_safety_button = QPushButton("Apply safety parameters")
        self.apply_safety_button.clicked.connect(lambda: self.worker.submit("apply_safety_parameters"))
        layout.addRow(self.apply_safety_button)
        save_button = QPushButton("Save settings")
        save_button.clicked.connect(self.save_settings)
        layout.addRow(save_button)
        return page

    @staticmethod
    def _register_spin(value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, 65535)
        spin.setValue(int(value))
        return spin

    @staticmethod
    def _port_spin(value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(1, 65535)
        spin.setValue(int(value))
        return spin

    @staticmethod
    def _indicator(name: str) -> QLabel:
        indicator = QLabel(f"{name} OFF")
        indicator.setProperty("active", False)
        indicator.setMinimumWidth(55)
        return indicator

    def _debug_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.debug_log = QPlainTextEdit(); self.debug_log.setReadOnly(True)
        layout.addWidget(self.debug_log)
        row = QHBoxLayout()
        self.register_address = QLineEdit("0x0002")
        self.register_value = QLineEdit("0")
        read_button = QPushButton("Read register")
        read_button.clicked.connect(self._debug_read)
        write_button = QPushButton("Write register")
        write_button.clicked.connect(self._debug_write)
        trigger_button = QPushButton("Test trigger")
        trigger_button.clicked.connect(self._debug_trigger)
        row.addWidget(self.register_address); row.addWidget(self.register_value); row.addWidget(read_button); row.addWidget(write_button); row.addWidget(trigger_button)
        layout.addLayout(row)
        return page

    def _connect_worker(self) -> None:
        self.compass.azimuthClicked.connect(self.submit_target)
        self.integration_log.connect(self.debug_log.appendPlainText)
        if hasattr(self.worker, "telemetry"):
            self.worker.telemetry.connect(self._on_telemetry)
            self.worker.online_changed.connect(self._on_online)
            self.worker.error.connect(self._on_worker_error)
            if hasattr(self.worker, "command_result"):
                self.worker.command_result.connect(self._on_command_result)

    def _refresh_from_config(self) -> None:
        angle = self.planner.display_angle_deg
        self.current_label.setText(f"{angle:05.1f} deg")
        self.compass.set_angles(angle)

    def submit_target(self, angle: float) -> None:
        plan = self.planner.plan(angle)
        if not plan.accepted:
            self.debug_log.appendPlainText(f"Motion rejected: {plan.reason}")
            return
        self.target_label.setText(f"Target: {angle % 360.0:05.1f} deg")
        if hasattr(self.worker, "submit"):
            registers = self.config_store.config.registers
            self.worker.submit(
                "move_degrees",
                plan.distance_deg,
                plan.direction,
                stop_trigger=registers.stop_trigger,
                forward_trigger=registers.forward_trigger,
                reverse_trigger=registers.reverse_trigger,
            )
        self.planner.mark_motion_started(plan)
        self.compass.set_angles(self.planner.display_angle_deg, angle)

    def stop_motion(self) -> None:
        if hasattr(self.worker, "request_stop"):
            self.worker.request_stop(self.config_store.config.registers.stop_trigger)
        self.planner.motion_running = False
        self.run_status.setText("STOPPED")

    def save_settings(self) -> None:
        self.config_store.update(
            serial_port=self.port_edit.text().strip(),
            baudrate=int(self.baud_combo.currentText()),
            slave_id=self.slave_spin.value(),
            timeout_s=self.timeout_spin.value(),
            rotation_span_deg=self.span_spin.value(),
            stop_point_deg=self.stop_point_spin.value(),
            simulate=self.simulate_check.isChecked(),
            registers={
                "smoothing_f08": self.f08_spin.value(),
                "max_frequency_f04": self.f04_spin.value(),
                "min_frequency_f05": self.f05_spin.value(),
                "forward_speed_p2": self.p2_spin.value(),
                "reverse_speed_p4": self.p4_spin.value(),
                "soft_stop_f13": self.f13_spin.value(),
                "enable_f14": self.f14_spin.value(),
                "stop_trigger": self.stop_trigger_spin.value(),
                "forward_trigger": self.forward_trigger_spin.value(),
                "reverse_trigger": self.reverse_trigger_spin.value(),
            },
        )
        self.planner.set_limits(self.span_spin.value(), self.stop_point_spin.value())
        self.debug_log.appendPlainText("Settings saved; serial and simulation changes apply after restart")

    def _debug_read(self) -> None:
        try:
            address = int(self.register_address.text(), 0)
        except ValueError:
            self.debug_log.appendPlainText("Invalid register address")
            return
        self.worker.submit("read_u16", address)

    def _debug_write(self) -> None:
        try:
            address = int(self.register_address.text(), 0)
            value = int(self.register_value.text(), 0)
        except ValueError:
            self.debug_log.appendPlainText("Invalid register value")
            return
        self.worker.submit("write_u16", address, value)

    def _debug_trigger(self) -> None:
        try:
            value = int(self.register_value.text(), 0)
        except ValueError:
            self.debug_log.appendPlainText("Invalid trigger value")
            return
        self.worker.submit("write_u16", 0x0102, value)
        self.debug_log.appendPlainText(f"Trigger 0x0102 = {value}")

    @Slot(object)
    def _on_command_result(self, result: Any) -> None:
        name, value = result
        self.debug_log.appendPlainText(f"{name}: {value!r}")

    def _stop_network_services(self) -> None:
        if self.services is not None:
            self.services.stop_all()
        self.debug_log.appendPlainText("Network services stopped")

    def _apply_network_services(self) -> None:
        network = self.config_store.config.network
        self.config_store.update(
            network={
                "n1mm_enabled": self.n1mm_check.isChecked(),
                "n1mm_host": self.n1mm_host.text().strip() or "127.0.0.1",
                "n1mm_port": self.n1mm_port.value(),
                "hamlib_enabled": self.hamlib_check.isChecked(),
                "hamlib_host": self.hamlib_host.text().strip() or "127.0.0.1",
                "hamlib_port": self.hamlib_port.value(),
                "gs232_enabled": self.gs232_check.isChecked(),
                "gs232_port": self.gs232_port.text().strip(),
                "gs232_baudrate": self.gs232_baudrate.value(),
            }
        )
        if self.services is None:
            return
        self.services.stop_all()
        if network.n1mm_enabled:
            self.services.start_n1mm(network.n1mm_host, network.n1mm_port)
        if network.hamlib_enabled:
            self.services.start_hamlib(network.hamlib_host, network.hamlib_port)
        if network.gs232_enabled and network.gs232_port:
            self.services.start_gs232(network.gs232_port, network.gs232_baudrate, self.integration_log.emit)
        self.debug_log.appendPlainText("Network services applied")

    @Slot(str)
    def _on_worker_error(self, message: str) -> None:
        self.debug_log.appendPlainText(f"ERROR {message}")

    def _calibrate_current(self) -> None:
        self.planner.calibrate_current(self.calibrate_angle.value())
        self.config_store.update_coordinates(
            hardware_coord_deg=self.planner.hardware_coord_deg,
            software_offset_deg=self.planner.software_offset_deg,
            true_azimuth_deg=self.planner.true_azimuth_deg,
            last_true_azimuth_deg=self.planner.true_azimuth_deg,
        )
        self.current_label.setText(f"{self.planner.display_angle_deg:05.1f} deg")
        self.compass.set_angles(self.planner.display_angle_deg)

    def _check_com0com(self) -> None:
        status = self.com0com_manager.status()
        self.com0com_status.setText(status.message)

    def _create_com0com_pair(self) -> None:
        status = self.com0com_manager.status()
        self.com0com_status.setText(status.message)
        if not status.can_create or status.executable is None:
            return
        self.com0com_process.start(str(status.executable), ["install", "PortName=COM10", "PortName=COM11"])
        self.com0com_status.setText("Creating COM10/COM11...")

    def _com0com_finished(self, exit_code: int, _exit_status) -> None:
        stdout = bytes(self.com0com_process.readAllStandardOutput()).decode(errors="replace").strip()
        stderr = bytes(self.com0com_process.readAllStandardError()).decode(errors="replace").strip()
        detail = stderr or stdout or f"exit code {exit_code}"
        self.com0com_status.setText("COM10/COM11 created" if exit_code == 0 else f"com0com failed: {detail}")

    def _com0com_error(self, _error) -> None:
        self.com0com_status.setText("Unable to run setupc.exe; check com0com installation and permissions")

    @Slot(bool)
    def _on_online(self, online: bool) -> None:
        self.connection_label.setText("ONLINE" if online else "OFFLINE")
        self.connection_label.setProperty("online", online)
        self.connection_label.style().unpolish(self.connection_label)
        self.connection_label.style().polish(self.connection_label)

    @Slot(object)
    def _on_telemetry(self, telemetry: dict[str, Any]) -> None:
        angle = float(telemetry.get("hardware_angle", self.planner.hardware_coord_deg))
        if self.planner.first_connection:
            self.planner.on_first_connection(angle)
        else:
            self.planner.set_hardware_coord(angle)
        self.config_store.update_coordinates(
            hardware_coord_deg=self.planner.hardware_coord_deg,
            software_offset_deg=self.planner.software_offset_deg,
            true_azimuth_deg=self.planner.true_azimuth_deg,
            last_true_azimuth_deg=self.planner.true_azimuth_deg,
        )
        display = self.planner.display_angle_deg
        self.current_label.setText(f"{display:05.1f} deg")
        self.compass.set_angles(display, self.compass.target_azimuth)
        self.run_status.setText("RUNNING" if telemetry.get("running") else "STOPPED")
        self.temperature_label.setText(f"Temp {telemetry.get('temperature', '--')}")
        limit_status = int(telemetry.get("limit_status", 0) or 0)
        alarm_status = int(telemetry.get("alarm_status", 0) or 0)
        self._set_indicator(self.s0_indicator, bool(limit_status & 0x01))
        self._set_indicator(self.s1_indicator, bool(limit_status & 0x02))
        self._set_indicator(self.s2_indicator, bool(alarm_status or limit_status & 0x04))

    @staticmethod
    def _set_indicator(indicator: QLabel, active: bool) -> None:
        indicator.setText(f"{indicator.text().split()[0]} {'ON' if active else 'OFF'}")
        indicator.setProperty("active", active)
        indicator.style().unpolish(indicator)
        indicator.style().polish(indicator)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.stop_motion()
        if self.services is not None:
            self.services.stop_all()
        if hasattr(self.worker, "shutdown"):
            self.worker.shutdown(self.config_store.config.registers.stop_trigger)
        if hasattr(self.worker, "wait"):
            self.worker.wait(9000)
        self.config_store.update_coordinates(
            hardware_coord_deg=self.planner.hardware_coord_deg,
            software_offset_deg=self.planner.software_offset_deg,
            true_azimuth_deg=self.planner.true_azimuth_deg,
            last_true_azimuth_deg=self.planner.true_azimuth_deg,
        )
        self.config_store.close()
        super().closeEvent(event)


def apply_dark_theme(app) -> None:
    app.setStyleSheet(
        """
        QWidget { background: #10151b; color: #e6edf3; font-family: 'Segoe UI'; }
        QGroupBox, QTabWidget::pane { border: 1px solid #35414c; }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit { background: #18212a; border: 1px solid #41515e; padding: 4px; }
        QPushButton { background: #263441; border: 1px solid #4d6271; padding: 7px 12px; }
        QPushButton:hover { background: #345064; }
        #stopButton { background: #a83d3d; font-weight: bold; min-height: 36px; }
        #currentAngle { color: #48d597; font-size: 28px; font-weight: bold; }
        #connectionLabel[online="true"] { color: #48d597; }
        #connectionLabel[online="false"] { color: #ef6c6c; }
        QLabel[active="true"] { color: #48d597; font-weight: bold; }
        QLabel[active="false"] { color: #ef6c6c; }
        QTabBar::tab { padding: 7px 14px; }
        """
    )


__all__ = ["MainWindow", "apply_dark_theme"]
