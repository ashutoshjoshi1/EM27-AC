from __future__ import annotations
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QLabel,
    QPushButton, QComboBox, QCheckBox, QSlider, QDoubleSpinBox, QLineEdit
)

from services.ac_service import ACService


class ACControlWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        # ---- Service ----
        self.svc = ACService(poll_ms=1000)
        self.svc.start()

        # ---- UI ----
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Connection box
        conn_box = QGroupBox("Connection")
        conn_layout = QGridLayout(conn_box)
        self.port_edit = QLineEdit()
        self.port_edit.setPlaceholderText("Optional: COM3 or /dev/ttyUSB0")
        self.btn_connect = QPushButton("Connect")
        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.setEnabled(False)

        conn_layout.addWidget(QLabel("Port"), 0, 0)
        conn_layout.addWidget(self.port_edit, 0, 1)
        conn_layout.addWidget(self.btn_connect, 0, 2)
        conn_layout.addWidget(self.btn_disconnect, 0, 3)

        # Controls box
        ctrl_box = QGroupBox("Controls")
        ctrl_layout = QGridLayout(ctrl_box)

        self.chk_power = QCheckBox("Power ON")
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["Auto", "Cool", "Heat", "Dry", "Fan"])  # adjust to device

        self.cmb_fan = QComboBox()
        self.cmb_fan.addItems(["Auto", "Low", "Medium", "High"])       # adjust to device

        self.temp_slider = QSlider(Qt.Horizontal)
        self.temp_slider.setRange(16, 30)  # °C typical range; adjust as needed
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setDecimals(1)
        self.temp_spin.setRange(16.0, 30.0)
        self.temp_spin.setSingleStep(0.5)

        ctrl_layout.addWidget(self.chk_power, 0, 0, 1, 1)
        ctrl_layout.addWidget(QLabel("Mode"), 0, 1)
        ctrl_layout.addWidget(self.cmb_mode, 0, 2)
        ctrl_layout.addWidget(QLabel("Fan"), 0, 3)
        ctrl_layout.addWidget(self.cmb_fan, 0, 4)
        ctrl_layout.addWidget(QLabel("Setpoint (°C)"), 1, 0)
        ctrl_layout.addWidget(self.temp_slider, 1, 1, 1, 3)
        ctrl_layout.addWidget(self.temp_spin, 1, 4)

        # Status box
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

        # Layout
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

        # Start disabled until connected
        self._set_controls_enabled(False)

    # ---------- UI handlers ----------
    def _on_connect(self) -> None:
        port = self.port_edit.text().strip()
        if port:
            self.svc._port = port  # update desired port
        self.svc.connect_device()

    def _on_disconnect(self) -> None:
        self.svc.disconnect_device()

    def _on_temp_changed(self, value: float) -> None:
        self.svc.set_temperature(float(value))

    def _on_status(self, s: dict) -> None:
        # Update labels; keep text friendly
        if "power" in s:
            self.lbl_power.setText(f"Power: {'ON' if s['power'] else 'OFF'}")
            self.chk_power.blockSignals(True)
            self.chk_power.setChecked(bool(s["power"]))
            self.chk_power.blockSignals(False)

        if "mode" in s and s["mode"]:
            self.lbl_mode.setText(f"Mode: {s['mode']}")
            # sync combo silently if differs
            if self.cmb_mode.currentText() != str(s["mode"]):
                self.cmb_mode.blockSignals(True)
                idx = self.cmb_mode.findText(str(s["mode"]))
                if idx >= 0:
                    self.cmb_mode.setCurrentIndex(idx)
                self.cmb_mode.blockSignals(False)

        if "fan" in s and s["fan"]:
            self.lbl_fan.setText(f"Fan: {s['fan']}")
            if self.cmb_fan.currentText() != str(s["fan"]):
                self.cmb_fan.blockSignals(True)
                idx = self.cmb_fan.findText(str(s["fan"]))
                if idx >= 0:
                    self.cmb_fan.setCurrentIndex(idx)
                self.cmb_fan.blockSignals(False)

        if "target" in s and s["target"] is not None:
            self.lbl_target.setText(f"Target: {s['target']} °C")
            # keep slider/spin synced
            try:
                target = float(s["target"])
                self.temp_slider.blockSignals(True)
                self.temp_spin.blockSignals(True)
                if int(round(target)) != self.temp_slider.value():
                    self.temp_slider.setValue(int(round(target)))
                if self.temp_spin.value() != target:
                    self.temp_spin.setValue(target)
            finally:
                self.temp_slider.blockSignals(False)
                self.temp_spin.blockSignals(False)

        if "temperature" in s and s["temperature"] is not None:
            self.lbl_temp.setText(f"Ambient: {s['temperature']} °C")

    def _on_error(self, msg: str) -> None:
        # Lightweight error display without modal blocking
        self.lbl_temp.setText(f"Error: {msg}")

    def _on_connected(self, ok: bool) -> None:
        self.btn_connect.setEnabled(not ok)
        self.btn_disconnect.setEnabled(ok)
        self._set_controls_enabled(ok)

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.chk_power.setEnabled(enabled)
        self.cmb_mode.setEnabled(enabled)
        self.cmb_fan.setEnabled(enabled)
        self.temp_slider.setEnabled(enabled)
        self.temp_spin.setEnabled(enabled)

    # Cleanup when widget is closed
    def closeEvent(self, event) -> None:  # type: ignore[override]
        try:
            self.svc.stop()
        finally:
            super().closeEvent(event)
