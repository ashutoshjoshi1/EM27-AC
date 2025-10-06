from collections import deque
from datetime import datetime
import config

# Calculate max length based on 24 hours of data at a 1-second interval
MAX_DATA_POINTS = 24 * 60 * 60 // (config.TIMER_INTERVAL_MS // 1000)

class SensorDataModel:
    """Manages storage and access for time-series sensor data."""
    def __init__(self):
        self.timestamps = deque(maxlen=MAX_DATA_POINTS)
        self.temperatures = deque(maxlen=MAX_DATA_POINTS)
        self.humidities = deque(maxlen=MAX_DATA_POINTS)
        self.pressures = deque(maxlen=MAX_DATA_POINTS)

    def add_data_point(self, temp, hum, pres):
        """Adds a new sensor reading and automatically handles trimming."""
        now = datetime.now().timestamp()
        self.timestamps.append(now)
        self.temperatures.append(temp)
        self.humidities.append(hum)
        self.pressures.append(pres)