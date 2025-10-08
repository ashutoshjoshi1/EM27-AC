from __future__ import annotations

import asyncio
import threading
from typing import Optional, Any

from pymodbus.client import AsyncModbusSerialClient
from pymodbus.exceptions import ModbusIOException
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

    def __init__(
        self,
        port: Optional[str] = None,
        *,
        slave_id: int = 1,
        baudrate: int = 19200,
        bytesize: int = 8,
        parity: str = "E",
        stopbits: int = 1,
        timeout: float = 2.0,
        retries: int = 3,
    ) -> None:
        """
        Initialise the wrapper.

        Args:
            port: Serial port name (e.g. ``"COM5"`` or ``"/dev/ttyUSB0"``).
                If omitted, ``"COM5"`` is used by default.
            slave_id: Modbus device ID. Defaults to 1.
            baudrate: Serial baud rate. Defaults to 19200.
            bytesize: Number of bits per byte (7 or 8). Defaults to 8.
            parity: Parity bit to use ('N', 'E', 'O'). Defaults to 'E'.
            stopbits: Number of stop bits (1, 1.5 or 2). Defaults to 1.
            timeout: Timeout for connecting and receiving data in seconds. Defaults to 2.0.
            retries: Maximum number of retries per request before an exception is raised.
                Defaults to 3.  Increasing this may help with flaky connections, whereas
                lowering it will return errors more quickly.
        """
        self.port: str = port or "COM5"
        self.slave_id: int = slave_id
        self.baudrate: int = baudrate
        self.bytesize: int = bytesize
        self.parity: str = parity
        self.stopbits: int = stopbits
        self.timeout: float = timeout
        self.retries: int = retries
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
            """
            Coroutine to instantiate and connect the asynchronous Modbus client.

            Uses the configuration provided at construction time, including
            ``baudrate``, ``bytesize``, ``parity``, ``stopbits``, ``timeout``
            and ``retries``.  Adjusting these values may help with devices that
            respond slowly or require different serial settings.
            """
            # Instantiate the client within the running event loop.  All
            # parameters are explicitly passed from the wrapper's state
            self.client = AsyncModbusSerialClient(
                framer=FramerType.RTU,
                port=self.port,
                baudrate=self.baudrate,
                stopbits=self.stopbits,
                bytesize=self.bytesize,
                parity=self.parity,
                timeout=self.timeout,
                retries=self.retries,
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
        except ModbusIOException as exc:
            # A Modbus I/O error indicates no response was received from the
            # device after the configured number of retries.  Log the error,
            # attempt a reconnect once, and return None so the caller can decide
            # how to proceed.
            print(
                f"Modbus I/O error while reading register {reg_name}: {exc}. "
                "Attempting to reconnect..."
            )
            try:
                # Reset the connection in case the client got stuck
                self.disconnect()
                self.connect(self.port)
            except Exception:
                # Ignore errors during reconnect
                pass
            return None
        except Exception as exc:
            # Other exceptions are unexpected; log and return None
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
        except ModbusIOException as exc:
            print(
                f"Modbus I/O error while writing register {address}: {exc}. "
                "Attempting to reconnect..."
            )
            try:
                self.disconnect()
                self.connect(self.port)
            except Exception:
                pass
            return False
        except Exception as exc:
            print(f"Error writing register {address}: {exc}")
            return False
        
    def _decode_temp_c(self, raw: int | None) -> float | None:
        """Modbus temps are in tenths of °C; convert to °C."""
        if raw is None:
            return None
        return float(raw) / 10.0

    def _encode_temp_c(self, value_c: float) -> int:
        """Convert °C to tenths of °C for Modbus writes."""
        return int(round(value_c * 10))

    # --- OPTIONAL: call from connect() after port open (safe no-op if register not present) ---
    def force_celsius(self) -> None:
        """
        If your register map exposes a C/F setting, set it to Celsius.
        This is optional for Modbus (values are already °C on the wire),
        but aligns the front-panel display with the app.
        """
        try:
            # If your register map defines e.g. "SET_C_F" (0=C, 1=F), force 0
            # Adjust the register name/index to your existing mapping if different:
            reg_index = self.REGISTER_MAP.get("SET_C_F")
            if reg_index is not None:
                self.write_register(reg_index, 0)  # 0 = Celsius, 1 = Fahrenheit
        except Exception:
            # ignore if not supported
            pass

    def get_temperature(self) -> float | None:
        """Return ambient/internal temperature in °C."""
        raw = self.read_register("READ_AMBIENT_TEMPERATURE")
        return self._decode_temp_c(raw)

    def get_setpoint(self) -> float | None:
        """Return control setpoint in °C."""
        raw = self.read_register("READ_CONTROL_SETPOINT")
        return self._decode_temp_c(raw)

    # --- writing setpoint in °C ---
    def set_cooling_setpoint(self, value_c: float) -> bool:
        """
        Write cooling setpoint (°C). Controller expects 0.1°C units.
        Clamp to a sane range to avoid controller rejects.
        """
        value_c = max(10.0, min(60.0, float(value_c)))  # typical usable range
        return self.write_register(self.REGISTER_MAP["SET_CONTROL_SETPOINT"],
                                self._encode_temp_c(value_c))

    def get_status(self) -> dict:
        st = {}
        temp = self.get_temperature()
        setp = self.get_setpoint()
        out = self.read_register("READ_OUTPUT_STATUS")

        if temp is not None:
            st["temperature"] = round(temp, 1)
        if setp is not None:
            st["target"] = round(setp, 1)

        if out is not None:
            st["power"] = bool(out & 0x01)
            cooling = bool(out & 0x02)
            heating = bool(out & 0x04)
            st["cooling"] = cooling
            st["heating"] = heating
            st["mode"] = "Cool" if cooling else ("Heat" if heating else "Auto")
            st["fan"] = "Auto"

        return st

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

    def __enter__(self) -> "ACModbusWrapper":
        """Enter context: connect to the device."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context: disconnect from the device."""
        self.disconnect()