from __future__ import annotations

import asyncio
import threading
from typing import Optional, Any

from pymodbus.client import AsyncModbusSerialClient
from pymodbus.framer import FramerType


class ACModbusWrapper:
    """
    Wrapper class providing a synchronous interface to the asynchronous
    Modbus operations used by the AC controller.

    The class maintains its own asyncio event loop running in a
    background thread. All asynchronous client operations are scheduled
    onto that loop using ``run_coroutine_threadsafe``. This design
    eliminates the ``RuntimeError: no running event loop`` that occurs
    when ``AsyncModbusSerialClient`` is used without a running loop.
    """

    # Register map (all holding registers)
    REGISTERS = {
        "SET_NETWORK_COOLING_SETPOINT": {"address": 0, "signed": True},
        "SET_NETWORK_HIGH_TEMP_ALARM_SETPOINT": {"address": 1, "signed": True},
        "SET_NETWORK_LOW_TEMP_ALARM_SETPOINT": {"address": 2, "signed": True},
        "SET_NETWORK_HEATER_SETPOINT": {"address": 3, "signed": True},
        "SET_ENABLE_FLAGS": {"address": 4, "signed": False},
        "READ_CONTROL_SETPOINT": {"address": 5, "signed": True},
        "READ_HIGH_TEMP_SETPOINT": {"address": 6, "signed": True},
        "READ_LOW_TEMP_SETPOINT": {"address": 7, "signed": True},
        "READ_HEATER_SETPOINT": {"address": 8, "signed": True},
        "READ_CONTROL_SENSOR": {"address": 12, "signed": True},
        "READ_ALARM_STATUS": {"address": 14, "signed": False},
        "READ_OUTPUT_STATUS": {"address": 15, "signed": False},
        "READ_CONTACT_STATUS": {"address": 16, "signed": False},
    }

    def __init__(self, port: Optional[str] = None) -> None:
        """
        Initialise the wrapper.

        Args:
            port: Serial port name (e.g. ``"COM5"`` or ``"/dev/ttyUSB0"``).
                If omitted, ``"COM5"`` is used by default.
        """
        self.port: str = port or "COM5"
        self.slave_id: int = 1
        self.client: Optional[AsyncModbusSerialClient] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._connected: bool = False

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------
    def _ensure_loop(self) -> None:
        """Ensure that a dedicated event loop and worker thread are running."""
        if self._loop is not None and self._thread is not None and self._thread.is_alive():
            return
        # Create a new event loop
        self._loop = asyncio.new_event_loop()
        # Define a runner to start the loop in a thread
        def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()
        # Start the loop in a daemon thread
        self._thread = threading.Thread(
            target=_run_loop,
            args=(self._loop,),
            name="ACModbusWrapperLoop",
            daemon=True,
        )
        self._thread.start()

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    def connect(self, port: Optional[str] = None) -> bool:
        """
        Connect to the AC device using the configured serial port.

        This method blocks until the asynchronous connection is complete. If
        successful, ``is_connected()`` will return ``True`` afterwards.

        Args:
            port: Optional new serial port to override the existing ``port``.

        Returns:
            True if the connection succeeded, False otherwise.
        """
        if port:
            self.port = port
        # Avoid reconnecting if already connected
        if self._connected:
            return True
        # Ensure the event loop is running
        self._ensure_loop()
        async def _do_connect() -> bool:
            # Instantiate the client within the running event loop
            self.client = AsyncModbusSerialClient(
                framer=FramerType.RTU,
                port=self.port,
                baudrate=19200,
                stopbits=1,
                bytesize=8,
                parity="E",
                timeout=2,
            )
            await self.client.connect()
            return bool(self.client.connected)
        try:
            future = asyncio.run_coroutine_threadsafe(_do_connect(), self._loop)
            self._connected = future.result()
        except Exception as exc:
            print(f"Error connecting to AC: {exc}")
            self._connected = False
        return self._connected

    def disconnect(self) -> None:
        """
        Disconnect from the AC device and stop the background event loop.

        This call blocks until the client has been closed and the loop
        stopped. After calling ``disconnect()``, the wrapper may be reused
        by calling ``connect()`` again.
        """
        if not self._connected:
            return
        async def _do_disconnect() -> None:
            """
            Coroutine used to close the underlying Modbus client.

            In pymodbus 3.11.x the asynchronous client exposes a synchronous
            ``close()`` method rather than an awaitable coroutine. Calling
            ``await self.client.close()`` will therefore raise a ``TypeError``
            (``object NoneType can't be used in 'await' expression``).  To
            accommodate this, simply invoke ``close()`` without awaiting.  The
            call is performed inside the event loop thread to ensure thread
            safety.
            """
            if self.client:
                # close() is synchronous in pymodbus 3.11.x
                self.client.close()
        try:
            if self._loop and self._thread and self._thread.is_alive():
                future = asyncio.run_coroutine_threadsafe(_do_disconnect(), self._loop)
                future.result()
            self._connected = False
        except Exception as exc:
            print(f"Error disconnecting: {exc}")
        finally:
            # Stop the event loop
            if self._loop and self._thread:
                try:
                    self._loop.call_soon_threadsafe(self._loop.stop)
                except Exception:
                    pass
                self._thread.join(timeout=1.0)
            self._loop = None
            self._thread = None

    def is_connected(self) -> bool:
        """Return True if a connection to the device is currently active."""
        return self._connected and self.client is not None

    def read_register(self, reg_name: str) -> Optional[int]:
        """
        Read the value of a single holding register.

        Args:
            reg_name: Name of the register to read, as defined in ``REGISTERS``.

        Returns:
            The register value, or ``None`` on error or if not connected.
        """
        if not self.is_connected():
            return None
        reg = self.REGISTERS.get(reg_name)
        if reg is None:
            return None
        async def _read() -> Optional[int]:
            """
            Inner coroutine to perform the register read.

            Newer versions of pymodbus have renamed the ``unit`` parameter to
            ``device_id`` (or ``slave``). Passing the deprecated ``unit``
            parameter will raise a ``TypeError`` such as::

                ModbusClientMixin.read_holding_registers() got an unexpected
                keyword argument 'unit'

            To maintain compatibility with pymodbus >=3.11, we pass
            ``device_id`` instead of ``unit``.
            """
            rr = await self.client.read_holding_registers(
                reg["address"], count=1, device_id=self.slave_id
            )
            # If the response indicates an error, propagate None
            if rr.isError():
                return None
            value = rr.registers[0]
            # Apply two's complement conversion for signed values
            if reg.get("signed", False) and value >= 0x8000:
                value -= 0x10000
            return value
        try:
            future = asyncio.run_coroutine_threadsafe(_read(), self._loop)
            return future.result()
        except Exception as exc:
            print(f"Error reading register {reg_name}: {exc}")
            return None

    def write_register(self, address: int, value: int) -> bool:
        """
        Write a single holding register.

        Args:
            address: Register address.
            value: Value to write (masked to 16 bits).

        Returns:
            True if the write succeeded, False otherwise.
        """
        if not self.is_connected():
            return False
        async def _write() -> bool:
            """
            Inner coroutine to perform the register write.

            Similar to the read path, newer versions of pymodbus renamed
            ``unit`` to ``device_id``. Passing ``unit`` will raise a
            ``TypeError``.  We therefore supply ``device_id`` explicitly.
            """
            rq = await self.client.write_register(
                address, value & 0xFFFF, device_id=self.slave_id
            )
            # ``isError()`` returns True when an error reply is received
            return not rq.isError()
        try:
            future = asyncio.run_coroutine_threadsafe(_write(), self._loop)
            return future.result()
        except Exception as exc:
            print(f"Error writing register {address}: {exc}")
            return False

    def set_cooling_setpoint(self, value: int) -> bool:
        """Set the cooling setpoint temperature."""
        if value < -32768 or value > 32767:
            return False
        return self.write_register(0, value)

    def get_temperature(self) -> Optional[float]:
        """Return the current control sensor temperature."""
        temp = self.read_register("READ_CONTROL_SENSOR")
        return float(temp) if temp is not None else None

    def get_setpoint(self) -> Optional[float]:
        """Return the current cooling setpoint."""
        sp = self.read_register("READ_CONTROL_SETPOINT")
        return float(sp) if sp is not None else None

    def get_status(self) -> dict[str, Any]:
        """
        Get a snapshot of the current AC status.

        The returned dictionary may contain the keys ``temperature``,
        ``target``, ``power``, ``mode`` and ``fan`` depending on the
        availability of each measurement. ``mode`` is derived from the
        output status register.
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
        """Turn the AC power on."""
        enable_flags = self.read_register("SET_ENABLE_FLAGS")
        if enable_flags is not None:
            return self.write_register(4, enable_flags | 0x01)
        return False

    def power_off(self) -> bool:
        """Turn the AC power off."""
        enable_flags = self.read_register("SET_ENABLE_FLAGS")
        if enable_flags is not None:
            return self.write_register(4, enable_flags & ~0x01)
        return False

    def set_temperature(self, value: int) -> bool:
        """Alias for ``set_cooling_setpoint``."""
        return self.set_cooling_setpoint(value)

    def set_mode(self, mode: str) -> bool:
        """
        Set the AC operating mode (Cool or Heat).

        Args:
            mode: Desired mode. Only ``"cool"`` or ``"heat"`` are honoured.

        Returns:
            True if the mode change was successful, False otherwise.
        """
        enable_flags = self.read_register("SET_ENABLE_FLAGS")
        if enable_flags is None:
            return False
        if mode.lower() == "cool":
            return self.write_register(4, (enable_flags & ~0x04) | 0x02)
        elif mode.lower() == "heat":
            return self.write_register(4, (enable_flags & ~0x02) | 0x04)
        return False

    def set_fan_speed(self, speed: str) -> bool:
        """Placeholder for future fan speed control; always returns True."""
        print(f"Fan speed control not implemented. Received: {speed}")
        return True

    def __enter__(self) -> "ACModbusWrapper":
        """Enter context: connect to the device."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context: disconnect from the device."""
        self.disconnect()