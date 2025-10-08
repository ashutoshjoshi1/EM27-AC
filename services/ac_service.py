from __future__ import annotations
from typing import Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from controllers.ac_adapter import ACAdapter
import config


class ACService(QObject):
    status = pyqtSignal(dict)
    error = pyqtSignal(str)
    connected = pyqtSignal(bool)

    def __init__(self, port: Optional[str] = None, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._thread = QThread(self)
        self._thread.setObjectName("ACServiceThread")
        self._port = port if port is not None else config.AC_CONTROLLER_PORT
        self._adapter: Optional[ACAdapter] = None
        self.moveToThread(self._thread)

    def start(self) -> None:
        if not self._thread.isRunning():
            self._thread.start()

    def stop(self) -> None:
        try:
            if self._adapter:
                try:
                    self._adapter.disconnect()
                except Exception as e:
                    print(f"Error disconnecting: {e}")
        finally:
            if self._thread.isRunning():
                self._thread.quit()
                self._thread.wait(2000)

    @pyqtSlot(str, int)
    def connect_device(self, port: str, modbus_id: int) -> None:
        """Attempt to connect to the AC device on the given serial port and Modbus ID."""
        try:
            if port:
                self._port = port
            from controllers.ac_modbus_wrapper import ACModbusWrapper
            ac = ACModbusWrapper(self._port, slave_id=modbus_id)
            self._adapter = ACAdapter(ac)
            connected = self._adapter.connect(self._port)
            if not connected:
                # If no response, raise an exception to trigger error signal
                raise Exception("No response from AC unit (check connection and address)")
            self.connected.emit(True)
            self.poll_now()  # Initial poll on successful connect
        except Exception as e:
            self.error.emit(f"Error connecting to device: {e}")
            self.connected.emit(False)

    @pyqtSlot()
    def disconnect_device(self) -> None:
        try:
            if self._adapter:
                self._adapter.disconnect()
            self.connected.emit(False)
        except Exception as e:
            self.error.emit(f"Error during disconnect: {e}")

    @pyqtSlot(bool)
    def set_power(self, on: bool) -> None:
        if self._adapter:
            try:
                self._adapter.power(on)
                self.poll_now()
            except Exception as e:
                self.error.emit(f"Error in setting power: {e}")

    @pyqtSlot(str)
    def set_mode(self, mode: str) -> None:
        if self._adapter:
            try:
                self._adapter.set_mode(mode)
                self.poll_now()
            except Exception as e:
                self.error.emit(f"Error in setting mode: {e}")

    @pyqtSlot(float)
    def set_temperature(self, value: float) -> None:
        if self._adapter:
            try:
                # Convert float (from UI spinner) to int (tenths of degree for Modbus)
                self._adapter.set_temperature(int(value))
                self.poll_now()
            except Exception as e:
                self.error.emit(f"Error in setting temperature: {e}")

    @pyqtSlot()
    def set_fan(self, speed: str) -> None:
        if self._adapter:
            try:
                self._adapter.set_fan_speed(speed)
                self.poll_now()
            except Exception as e:
                self.error.emit(f"Error in setting fan speed: {e}")

    @pyqtSlot()
    def poll_now(self) -> None:
        if not self._adapter:
            return
        try:
            status = self._adapter.get_status() or {}
            self.status.emit(status)
        except Exception as e:
            self.error.emit(f"Error polling device: {e}")