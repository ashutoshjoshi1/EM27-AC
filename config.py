APP_NAME = "EM-27 SciGlob"
MIN_WINDOW_SIZE = (1200, 800)
TIMER_INTERVAL_MS = 1000  # Interval for sensor and rain checks
CAMERA_FRAME_RATE = 33 # approx 30 fps

# --- Serial Port Settings ---
TEMP_CONTROLLER_PORT = "COM2"
THP_CONTROLLER_PORT = "COM7"
MOTOR_CONTROLLER_PORT = "COM8"

# --- SMTP Email Settings ---
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "alerts@sciglob.com"
SENDER_PASSWORD = "tpnu xyav aybr wguk"
RECEIVER_EMAILS = ["omar@sciglob.com", "ajoshi@sciglob.com"]

# --- UI & Styling ---
# Using a dictionary for styles that can be applied via a central function
STYLES = {
    "main_window": "background-color: #333333;",
    "group_box": """
        QGroupBox {
            background-color: #2c2c2c;
            border: 1px solid #444;
            border-radius: 10px;
            color: white;
            font-weight: bold;
            margin-top: 1ex;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top center;
            padding: 0 5px;
        }
    """,
    "connect_btn": "padding:8px; border-radius:5px; background:#4CAF50; color:white;",
    "disconnect_btn": "padding:8px; border-radius:5px; background:#f44336; color:white;",
    "rain_indicator_raining": "font-weight: bold; font-size: 16px; color: #FF5555;",
    "rain_indicator_not_raining": "font-weight: bold; font-size: 16px; color: #55FF55;",
    "rain_indicator_unknown": "font-weight: bold; font-size: 16px; color: #CCCCCC;",
}

# --- Motor Positions ---
MOTOR_OPEN_POSITION = "-2300"
MOTOR_CLOSED_POSITION = "0"