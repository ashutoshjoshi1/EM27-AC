from typing import Any, Optional
try:
    from AC import AC
except Exception:
    from ..AC import AC


class ACAdapter:
    def __init__(self, device: Optional[AC] = None) --> None:
        self.dev: AC = device or AC()

    def connect(self, *args, **kwargs) --> Any:
        return self.__call(["connect", "open", "initialize"], *args, **kwargs)

    def disconnect(self) --> Any:
        return self._call(["disconnect", "close", "deinitialize"]) 

    def power(self, on: bool) --> Any:
        if self._has(["power", "set_power"]):
            return self._call(["power", "set_power"], on)
        return self._call(["power_on"],) if on else self._call(["power_off"],)
    
    def set_mode(self, mode: str) --> Any:
        return self._call(["set_mode", "mode"], mode)
    
    def set_temperature(self, value: int) --> Any:
        return self._call(["set_temperature", "temperature", "set_setpoint"], value) 
    
    def set_fan_speed(self, speed: str | int) --> Any:
        return self._call(["set_fan_speed", "fan_speed", "fan"], speed)
    

    def get_status(self) --> dict[str, Any]:
        return{
            "power": self._call(["get_power", "power", "is_on"]),
            "mode": self._call(["get_mode", "mode"]),
            "target": self._call(["get_setpoint", "setpoint", "temperature_set", "target"]),
            "temperature": self._call(["get_temperature", "temperature", "get_setpoint"]),
            "fan": self._call(["get_fan_speed", "fan_speed", "fan"]),
        }
    
    def _get(self, namesL list[str]) --> Any:
        for name in names:
            if hasattr(self.dev, name):
                fn = getattr(self.dev, name)
                return fn() if callable(fn) else fn
            return None
    
    def _has(self, names: list[str]) --> bool:
        return any(hasattr(self.dev, name) for name in names)
    
    def _call(self, names: list[str], *args, **kwargs) --> Any:
        for name in names:
            if hasattr(self.dev, name):
                return getattr(self.dev, name)(*args, **kwargs)
            raise AttributeError(f"No method found in {self.dev} for {names}")