"""
AC Modbus Wrapper - Provides synchronous interface to AC.py async Modbus operations
"""
import asyncio
from typing import Optional, Any
from pymodbus.client import AsyncModbusSerialClient
from pymodbus.framer import FramerType
from pymodbus.exceptions import ModbusException


class ACModbusWrapper:
    """Wrapper class to provide synchronous interface to async Modbus AC operations"""
    
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
    
    def __init__(self, port: Optional[str] = None):
        """Initialize AC Modbus wrapper
        
        Args:
            port: Serial port name (e.g., 'COM5', '/dev/ttyUSB0'). Defaults to 'COM5'
        """
        self.port = port or "COM5"
        self.slave_id = 1
        self.client: Optional[AsyncModbusSerialClient] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._connected = False
        
    def connect(self, port: Optional[str] = None) -> bool:
        """Connect to AC device via Modbus serial
        
        Args:
            port: Optional override for serial port
            
        Returns:
            True if connected successfully
        """
        if port:
            self.port = port
            
        try:
            # Create new event loop for async operations
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            
            # Create and connect client
            self.client = AsyncModbusSerialClient(
                framer=FramerType.RTU,
                port=self.port,
                baudrate=19200,
                stopbits=1,
                bytesize=8,
                parity="E",
                timeout=2,
            )
            
            # Run connection in event loop
            self._loop.run_until_complete(self.client.connect())
            self._connected = self.client.connected
            
            return self._connected
        except Exception as e:
            print(f"Error connecting to AC: {e}")
            self._connected = False
            return False
    
    def disconnect(self) -> None:
        """Disconnect from AC device"""
        if self.client and self._connected:
            try:
                if self._loop and self._loop.is_running():
                    self._loop.run_until_complete(self.client.close())
                self._connected = False
            except Exception as e:
                print(f"Error disconnecting: {e}")
        
        # Clean up event loop
        if self._loop:
            try:
                self._loop.close()
            except Exception:
                pass
            self._loop = None
    
    def is_connected(self) -> bool:
        """Check if connected to device"""
        return self._connected and self.client is not None
    
    def read_register(self, reg_name: str) -> Optional[int]:
        """Read a single holding register
        
        Args:
            reg_name: Register name from REGISTERS dict
            
        Returns:
            Register value or None on error
        """
        if not self.is_connected():
            return None
            
        reg = self.REGISTERS.get(reg_name)
        if not reg:
            return None
            
        try:
            async def _read():
                rr = await self.client.read_holding_registers(
                    reg["address"], count=1, unit=self.slave_id
                )
                if rr.isError():
                    return None
                    
                value = rr.registers[0]
                if reg.get("signed", False) and value >= 0x8000:
                    value -= 0x10000
                return value
            
            return self._loop.run_until_complete(_read())
        except Exception as e:
            print(f"Error reading register {reg_name}: {e}")
            return None
    
    def write_register(self, address: int, value: int) -> bool:
        """Write a single holding register
        
        Args:
            address: Register address
            value: Value to write (will be masked to 16-bit)
            
        Returns:
            True if successful
        """
        if not self.is_connected():
            return False
            
        try:
            async def _write():
                rq = await self.client.write_register(
                    address, value & 0xFFFF, unit=self.slave_id
                )
                return not rq.isError()
            
            return self._loop.run_until_complete(_write())
        except Exception as e:
            print(f"Error writing register {address}: {e}")
            return False
    
    def set_cooling_setpoint(self, value: int) -> bool:
        """Set cooling setpoint temperature
        
        Args:
            value: Temperature setpoint (-32768 to 32767)
            
        Returns:
            True if successful
        """
        if value < -32768 or value > 32767:
            return False
        return self.write_register(0, value)
    
    def get_temperature(self) -> Optional[float]:
        """Get current control sensor temperature
        
        Returns:
            Temperature in degrees or None on error
        """
        temp = self.read_register("READ_CONTROL_SENSOR")
        return float(temp) if temp is not None else None
    
    def get_setpoint(self) -> Optional[float]:
        """Get current cooling setpoint
        
        Returns:
            Setpoint temperature or None on error
        """
        sp = self.read_register("READ_CONTROL_SETPOINT")
        return float(sp) if sp is not None else None
    
    def get_status(self) -> dict[str, Any]:
        """Get comprehensive AC status
        
        Returns:
            Dictionary with status information
        """
        status = {}
        
        # Read key registers
        temp = self.get_temperature()
        setpoint = self.get_setpoint()
        output_status = self.read_register("READ_OUTPUT_STATUS")
        
        if temp is not None:
            status["temperature"] = temp
        if setpoint is not None:
            status["target"] = setpoint
        if output_status is not None:
            # Interpret output status bits
            status["power"] = bool(output_status & 0x01)
            status["cooling"] = bool(output_status & 0x02)
            status["heating"] = bool(output_status & 0x04)
            
            # Determine mode from status
            if status.get("cooling"):
                status["mode"] = "Cool"
            elif status.get("heating"):
                status["mode"] = "Heat"
            else:
                status["mode"] = "Auto"
                
            status["fan"] = "Auto"  # Default fan mode
        
        return status
    
    def power_on(self) -> bool:
        """Turn AC power on"""
        # Implement based on device protocol
        # This is a placeholder - adjust based on actual device needs
        enable_flags = self.read_register("SET_ENABLE_FLAGS")
        if enable_flags is not None:
            return self.write_register(4, enable_flags | 0x01)
        return False
    
    def power_off(self) -> bool:
        """Turn AC power off"""
        # Implement based on device protocol
        enable_flags = self.read_register("SET_ENABLE_FLAGS")
        if enable_flags is not None:
            return self.write_register(4, enable_flags & ~0x01)
        return False
    
    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()
