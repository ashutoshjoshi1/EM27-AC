from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QGroupBox, QLabel,
    QPushButton, QComboBox, QCheckBox, QSlider, QDoubleSpinBox, QLineEdit, QSpinBox
)

from services.ac_service import ACService
import config


class ACControlWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # ---- Service ----
        self.svc = ACService()
        self.svc.start()
        # ---- Polling Timer ----
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(1000)  # poll every 1 second
        self.poll_timer.timeout.connect(self.svc.poll_now)
        # ---- UI Layout ----
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        # Status label at the top
        self.status_label = QLabel("Disconnected")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-weight: bold; padding: 4px;")
        root.addWidget(self.status_label)
        # Connection box
        conn_box = QGroupBox("Connection")
        conn_layout = QGridLayout(conn_box)
        self.port_edit = QLineEdit()
        self.port_edit.setText(config.AC_CONTROLLER_PORT)  # default port (e.g., "COM5")
        self.port_edit.setPlaceholderText("e.g., COM5 or /dev/ttyUSB0")
        self.id_spin = QSpinBox()
        self.id_spin.setRange(1, 247)
        self.id_spin.setValue(1)
        self.btn_connect = QPushButton("Connect")
        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.setEnabled(False)
        # Arrange connection inputs in grid
        conn_layout.addWidget(QLabel("Port"), 0, 0)
        conn_layout.addWidget(self.port_edit, 0, 1, 1, 3)    # span Port field across columns
        conn_layout.addWidget(QLabel("Address"), 1, 0)
        conn_layout.addWidget(self.id_spin, 1, 1)
        conn_layout.addWidget(self.btn_connect, 1, 2)
        conn_layout.addWidget(self.btn_disconnect, 1, 3)
        # Controls box (Power, Mode, Fan, Setpoint)
        ctrl_box = QGroupBox("Controls")
        ctrl_layout = QGridLayout(ctrl_box)
        self.chk_power = QCheckBox("Power ON")
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["Auto", "Cool", "Heat", "Dry", "Fan"])
        self.cmb_fan = QComboBox()
        self.cmb_fan.addItems(["Auto", "Low", "Medium", "High"])
        self.temp_slider = QSlider(Qt.Horizontal)
        self.temp_slider.setRange(16, 30)  # range in °C
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setDecimals(1)
        self.temp_spin.setRange(16.0, 30.0)
        self.temp_spin.setSingleStep(0.5)
        ctrl_layout.addWidget(self.chk_power, 0, 0)
        ctrl_layout.addWidget(QLabel("Mode"), 0, 1)
        ctrl_layout.addWidget(self.cmb_mode, 0, 2)
        ctrl_layout.addWidget(QLabel("Fan"), 0, 3)
        ctrl_layout.addWidget(self.cmb_fan, 0, 4)
        ctrl_layout.addWidget(QLabel("Setpoint (°C)"), 1, 0)
        ctrl_layout.addWidget(self.temp_slider, 1, 1, 1, 3)
        ctrl_layout.addWidget(self.temp_spin, 1, 4)
        # Status box (to display readings)
        stat_box = QGroupBox("Status")
        stat_layout = QGridLayout(stat_box)
        self.lbl_power = QLabel("Power: —")
        self.lbl_mode = QLabel("Mode: —")
        self.lbl_fan = QLabel("Fan: —")
        self.lbl_target = QLabel("Target: —")
        self.lbl_temp = QLabel("Ambient: —")
        stat_layout.addWidget(self.lbl_power, 0, 0)
        stat_layout.addWidget(self.lbl_mode, 0, 1)
        stat_layout.addWidget(self.lbl_fan, 0, 2)
        stat_layout.addWidget(self.lbl_target, 1, 0)
        stat_layout.addWidget(self.lbl_temp, 1, 1)
        # Assemble layout
        root.addWidget(conn_box)
        root.addWidget(ctrl_box)
        root.addWidget(stat_box)
        root.addStretch(1)
        # ---- Wire up signals ----
        self.btn_connect.clicked.connect(self._on_connect)
        self.btn_disconnect.clicked.connect(self._on_disconnect)
        self.chk_power.toggled.connect(self.svc.set_power)
        self.cmb_mode.currentTextChanged.connect(self.svc.set_mode)
        self.cmb_fan.currentTextChanged.connect(self.svc.set_fan)
        self.temp_slider.valueChanged.connect(lambda v: self.temp_spin.setValue(float(v)))
        self.temp_spin.valueChanged.connect(self._on_temp_changed)
        self.svc.status.connect(self._on_status)
        self.svc.error.connect(self._on_error)
        self.svc.connected.connect(self._on_connected)
        # Disable controls until connected
        self._set_controls_enabled(False)

    # --- Slots ---
    def _on_connect(self) -> None:
        port = self.port_edit.text().strip()
        addr = self.id_spin.value()
        self.svc.connect_device(port, addr)

    def _on_disconnect(self) -> None:
        self.svc.disconnect_device()

    def _on_temp_changed(self, value: float) -> None:
        self.svc.set_temperature(value)

    def _on_status(self, s: dict) -> None:
        # Update UI labels based on status dict from ACService
        if "power" in s:
            self.lbl_power.setText(f"Power: {'ON' if s['power'] else 'OFF'}")
            self.chk_power.blockSignals(True)
            self.chk_power.setChecked(bool(s["power"]))
            self.chk_power.blockSignals(False)
        if "mode" in s and s["mode"]:
            self.lbl_mode.setText(f"Mode: {s['mode']}")
            # Update mode dropdown to reflect actual mode
            current = self.cmb_mode.currentText()
            if current != str(s["mode"]):
                self.cmb_mode.blockSignals(True)
                idx = self.cmb_mode.findText(str(s["mode"]))
                if idx >= 0:
                    self.cmb_mode.setCurrentIndex(idx)
                self.cmb_mode.blockSignals(False)
        if "fan" in s and s["fan"]:
            self.lbl_fan.setText(f"Fan: {s['fan']}")
            # Update fan dropdown if needed
            current_fan = self.cmb_fan.currentText()
            if current_fan != str(s["fan"]):
                self.cmb_fan.blockSignals(True)
                idx = self.cmb_fan.findText(str(s["fan"]))
                if idx >= 0:
                    self.cmb_fan.setCurrentIndex(idx)
                self.cmb_fan.blockSignals(False)
        if "target" in s and s["target"] is not None:
            self.lbl_target.setText(f"Target: {s['target']} °C")
            try:
                target_val = float(s["target"])
                # Sync slider/spin to the reported setpoint
                self.temp_slider.blockSignals(True)
                self.temp_spin.blockSignals(True)
                if int(round(target_val)) != self.temp_slider.value():
                    self.temp_slider.setValue(int(round(target_val)))
                if self.temp_spin.value() != target_val:
                    self.temp_spin.setValue(target_val)
            finally:
                self.temp_slider.blockSignals(False)
                self.temp_spin.blockSignals(False)
        if "temperature" in s and s["temperature"] is not None:
            self.lbl_temp.setText(f"Ambient: {s['temperature']} °C")

    def _on_error(self, msg: str) -> None:
        # Display error messages (e.g., connection failures)
        self.status_label.setText(f"Error: {msg}")

    def _on_connected(self, ok: bool) -> None:
        # Update UI elements on connect/disconnect events
        self.btn_connect.setEnabled(not ok)
        self.btn_disconnect.setEnabled(ok)
        self._set_controls_enabled(ok)
        self.status_label.setText("Connected" if ok else "Disconnected")
        if ok:
            self.poll_timer.start()
        else:
            self.poll_timer.stop()

    def _set_controls_enabled(self, enabled: bool) -> None:
        # Enable/disable control inputs
        self.chk_power.setEnabled(enabled)
        self.cmb_mode.setEnabled(enabled)
        self.cmb_fan.setEnabled(enabled)
        self.temp_slider.setEnabled(enabled)
        self.temp_spin.setEnabled(enabled)

    def closeEvent(self, event) -> None:
        self.poll_timer.stop()
        self.svc.stop()
        super().closeEvent(event)

    def get_status(self) -> dict[str, Any]:
        """
        Get a snapshot of the current AC status.
        Returns keys: "temperature", "target", "power", "mode", "fan".
        """
        status: dict[str, Any] = {}
        temp = self.get_temperature()
        setpoint = self.get_setpoint()
        output_status = self.read_register("READ_OUTPUT_STATUS")
        if temp is not None:
            status["temperature"] = temp
        if setpoint is not None:
            status["target"] = setpoint
        if output_status is not None:
            # Interpret output status bits (bit0: Heater on, bit1: Cooling on, etc.)
            status["power"] = bool(output_status & 0x01)
            status["cooling"] = bool(output_status & 0x02)
            status["heating"] = bool(output_status & 0x04)
            if status.get("cooling"):
                status["mode"] = "Cool"
            elif status.get("heating"):
                status["mode"] = "Heat"
            else:
                status["mode"] = "Auto"
            status["fan"] = "Auto"
        return status

    def power_on(self) -> bool:
        """Turn the AC power on (equivalent to closing the door contact)."""
        enable_flags = self.read_register("SET_ENABLE_FLAGS")
        if enable_flags is not None:
            # Clear bit 8 (EN_INPUT1_INVERT) so door contact logic is normal (unit ON):contentReference[oaicite:8]{index=8}
            return self.write_register(4, enable_flags & ~0x100)
        return False

    def power_off(self) -> bool:
        """Turn the AC power off (equivalent to opening the door contact)."""
        enable_flags = self.read_register("SET_ENABLE_FLAGS")
        if enable_flags is not None:
            # Set bit 8 (EN_INPUT1_INVERT) to invert door contact logic (unit OFF):contentReference[oaicite:9]{index=9}
            return self.write_register(4, enable_flags | 0x100)
        return False

    def set_temperature(self, value: int) -> bool:
        """Alias for set_cooling_setpoint (in tenths of a degree)."""
        return self.set_cooling_setpoint(value)

    def set_mode(self, mode: str) -> bool:
        """
        Set the AC operating mode. Supports "auto", "cool", "heat", "dry", "fan".
        """
        enable_flags = self.read_register("SET_ENABLE_FLAGS")
        if enable_flags is None:
            return False
        if mode.lower() == "cool":
            # Enable cooling-only mode (bit1 = 1, bit2 = 0)
            return self.write_register(4, (enable_flags & ~0x04) | 0x02)
        elif mode.lower() == "heat":
            # Enable heating-only mode (bit2 = 1, bit1 = 0)
            return self.write_register(4, (enable_flags & ~0x02) | 0x04)
        elif mode.lower() in ("auto", "fan", "dry"):
            # Auto/Fan/Dry: clear both cooling and heating request bits (0x02 and 0x04)
            return self.write_register(4, enable_flags & ~0x06)
        return False

    def set_fan_speed(self, speed: str) -> bool:
        """Fan speed control not supported in this controller (always returns True)."""
        print(f"Fan speed control not implemented. Received: {speed}")
        return True