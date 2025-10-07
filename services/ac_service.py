from __future__ import annotations
from typing import Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal, pyqtSlot, QTimer

from controllers.ac_adapter import ACAdapter


class ACService(QObject):
    status = pyqtSignal(dict)
    error = pyqtSignal(str)
    connected = pyqtSignal(bool)

    def __init__(self, port: Optional[AC] = None, poll_ms: int = 1000, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._thread = QThread(self)
        self._thread.setObjectName("ACServiceThread")
        self._port = port
        self._poll_ms = poll_ms
        self._poll_timer: Optional[QTimer] = None
        self._adapter: Optional[ACAdapter] = None

        self.moveToThread(self._thread)
        self._thread.started.connect(self._on_started)

    def start(self) -> None:
        if not self._thread.isRunning():
            self._thread.start()    
    
    def stop(self) -> None:
        try:
            if self._poll_timer:
                self._poll_timer.stop()
            if self._adapter:
                try:
                    self._adapter.disconnect()
                except Exception as e:
                    print(f"Error disconnecting: {e}")
        finally:
            self._thread.quit()
            self._thread.wait(2000)

    @pyqtSlot()
    def connect_device(self) -> None:
        try:
            # Import AC wrapper from modbus implementation
            from controllers.ac_modbus_wrapper import ACModbusWrapper
            ac = ACModbusWrapper(self._port) if self._port else ACModbusWrapper()
            self._adapter = ACAdapter(ac)
            if self._port:
                try:
                    self._adapter.connect(self._port)
                except TypeError:
                    self._adapter.connect()
            else:
                self._adapter.connect()
            self.connected.emit(True)
            if self._poll_timer and not self._poll_timer.isActive():
                self._poll_timer.start()
            self._poll_now()
        except Exception as e:
            self.error.emit(f"Error connecting to device: {e}")
            self.connected.emit(False)

    @pyqtSlot()
    def disconnect_device(self) -> None:
        try:
            if self._poll_timer:
                self._poll_timer.stop()
            if self._adapter:
                self._adapter.disconnect()
            self.connected.emit(False)
        except Exception as e:
            self.error.emit(f"Error during disconnect: {e}")

    @pyqtSlot(bool)
    def set_power(self, on: bool) -> None:
        try:
            if self._adapter:
                self._adapter.power(on)
                self._poll_now()
        except Exception as e:
            self.error.emit(f"Error in setting power: {e}")
    
    @pyqtSlot(str)
    def set_mode(self, mode: str) -> None:
        try:
            if self._adapter:
                self._adapter.set_mode(mode)
                self._poll_now()
        except Exception as e:
            self.error.emit(f"Error in setting mode: {e}")

    @pyqtSlot(float)
    def set_temperature(self, value: float) -> None:
        try:
            if self._adapter:
                self._adapter.set_temperature(int(value))
                self._poll_now()
        except Exception as e:
            self.error.emit(f"Error in setting temperature: {e}")
    
    def set_fan(self, speed: str) -> None:
        try:
            if self._adapter:
                self._adapter.set_fan_speed(speed)
                self._poll_now()
        except Exception as e:
            self.error.emit(f"Error in setting fan speed: {e}")

    @pyqtSlot()
    def _on_started(self) -> None:
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self._poll_ms)
        self._poll_timer.timeout.connect(self._poll_now)

    @pyqtSlot()
    def _poll_now(self) -> None:
        if not self._adapter:
            return
        try:
            status = self._adapter.get_status() or {}
            self.status.emit(status)
        except Exception as e:
            self.error.emit(f"Error polling device: {e}")
