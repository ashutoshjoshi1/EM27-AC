from typing import Optional, Any

class ACAdapter:
    """Adapter pattern for AC device operations, wrapping a device driver (e.g. ACModbusWrapper)."""
    def __init__(self, device: Optional[Any] = None) -> None:
        self._device = device

    def connect(self, *args, **kwargs) -> bool:
        """Connect to the AC device. Returns True if successful, False otherwise."""
        if not self._device:
            return False
        # Attempt connection on underlying device
        result = self._device.connect(*args, **kwargs) if hasattr(self._device, "connect") else False
        # If connected, enable network setpoints so Modbus-set values take effect
        if result and hasattr(self._device, "read_register") and hasattr(self._device, "write_register"):
            flags = self._device.read_register("SET_ENABLE_FLAGS")
            if flags is not None:
                # Set bit 9 (EN_NETWORK_SETPOINTS) to use Modbus setpoints for control:contentReference[oaicite:6]{index=6}:contentReference[oaicite:7]{index=7}
                self._device.write_register(4, flags | 0x200)
        return result

    def disconnect(self) -> None:
        """Disconnect from the AC device."""
        if self._device and hasattr(self._device, "disconnect"):
            self._device.disconnect()

    def power(self, on: bool) -> bool:
        """Turn the AC power on (True) or off (False)."""
        if not self._device:
            return False
        try:
            if on:
                # Use specific power_on method if available
                if hasattr(self._device, "power_on"):
                    return self._device.power_on()
                elif hasattr(self._device, "power"):
                    return self._device.power(True)
            else:
                if hasattr(self._device, "power_off"):
                    return self._device.power_off()
                elif hasattr(self._device, "power"):
                    return self._device.power(False)
        except Exception as e:
            print(f"Error in power control: {e}")
        return False

    def set_mode(self, mode: str) -> bool:
        """Set the AC operation mode (Auto, Cool, Heat, Dry, Fan)."""
        if not self._device or not hasattr(self._device, "set_mode"):
            return False
        return self._device.set_mode(mode)

    def set_temperature(self, value: int) -> bool:
        """Set the target temperature (cooling setpoint)."""
        if not self._device:
            return False
        # Use set_temperature if available, otherwise fallback to direct cooling setpoint
        if hasattr(self._device, "set_temperature"):
            return self._device.set_temperature(value)
        elif hasattr(self._device, "set_cooling_setpoint"):
            return self._device.set_cooling_setpoint(value)
        return False

    def set_fan_speed(self, speed: str) -> bool:
        """Set the fan speed (if supported by device)."""
        if not self._device:
            return False
        if hasattr(self._device, "set_fan_speed"):
            return self._device.set_fan_speed(speed)
        return False

    def get_status(self) -> dict:
        """Retrieve current status from the AC device."""
        if not self._device or not hasattr(self._device, "get_status"):
            return {}
        return self._device.get_status()

