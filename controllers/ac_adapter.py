from typing import Any, List

class ACAdapter:
    """
    Adapter to provide a standardized interface for different AC controller objects.
    It finds and calls methods on the wrapped device object based on a list of possible names.
    """
    def __init__(self, device: Any) -> None:
        if device is None:
            raise ValueError("ACAdapter requires a device object to be provided.")
        self.dev: Any = device

    def connect(self, *args, **kwargs) -> Any:
        return self._call(["connect", "open", "initialize"], *args, **kwargs)

    def disconnect(self) -> Any:
        return self._call(["disconnect", "close", "deinitialize"]) 

    def power(self, on: bool) -> Any:
        if self._has(["power", "set_power"]):
            return self._call(["power", "set_power"], on)
        return self._call(["power_on"],) if on else self._call(["power_off"],)
    
    def set_mode(self, mode: str) -> Any:
        return self._call(["set_mode", "mode"], mode)
    
    def set_temperature(self, value: int) -> Any:
        return self._call(["set_temperature", "temperature", "set_setpoint"], value) 
    
    def set_fan_speed(self, speed: Any) -> Any:
        return self._call(["set_fan_speed", "fan_speed", "fan"], speed)
    
    def get_status(self) -> dict[str, Any]:
        return {
            "power": self._get(["get_power", "power", "is_on"]),
            "mode": self._get(["get_mode", "mode"]),
            "target": self._get(["get_setpoint", "setpoint", "temperature_set", "target"]),
            "temperature": self._get(["get_temperature", "temperature", "ambient"]),
            "fan": self._get(["get_fan_speed", "fan_speed", "fan"]),
        }
    
    def _get(self, names: List[str]) -> Any:
        """
        Gets an attribute or calls a method from the device, trying a list of possible names.
        Returns the value, or None if no matching attribute is found.
        """
        for name in names:
            if hasattr(self.dev, name):
                attr = getattr(self.dev, name)
                return attr() if callable(attr) else attr
        return None
    
    def _has(self, names: List[str]) -> bool:
        """Checks if the device has any of the attributes in the list."""
        return any(hasattr(self.dev, name) for name in names)
    
    def _call(self, names: List[str], *args, **kwargs) -> Any:
        """
        Calls a method on the device, trying a list of possible names.
        Raises an AttributeError if no matching method is found.
        """
        for name in names:
            if hasattr(self.dev, name):
                method = getattr(self.dev, name)
                if callable(method):
                    return method(*args, **kwargs)
        raise AttributeError(f"No callable method found in {self.dev} for any of these names: {names}")