# EM27-AC Code Index

This document provides a comprehensive index of all code definitions in the EM27-AC project.

## Project Overview
EM27-AC is a control system for EM-27 SciGlob equipment, featuring:
- Temperature and climate control
- Motor control for equipment positioning
- Environmental sensors (Temperature, Humidity, Pressure)
- Camera integration
- Real-time data monitoring and visualization
- Email alerts for rain detection

---

## Table of Contents
1. [Main Application Files](#main-application-files)
2. [Controllers](#controllers)
3. [Drivers](#drivers)
4. [Services](#services)
5. [UI Components](#ui-components)
6. [Configuration](#configuration)
7. [Data Models](#data-models)

---

## Main Application Files

### AC.py
**Purpose:** Textual-based Modbus application interface for AC control

**Functions:**
- `read_register(client, reg, slave_id: int)` - Async function to read Modbus registers
- `set_cooling_setpoint(client, value: int, slave_id: int = 1)` - Set cooling temperature setpoint
- `run()` - Main async function to run the Textual app

**Classes:**
- `ModbusApp(App)`
  - `__init__(self, client, slave_id=1, interval=15, **kwargs)` - Initialize Modbus app
  - `compose(self) -> ComposeResult` - Compose UI widgets
  - `on_mount(self) -> None` - Async mount handler
  - `poll_registers(self) -> None` - Async function to poll registers periodically
  - `on_input_submitted(self, event: Input.Submitted) -> None` - Handle input submission
  - `on_unmount(self) -> None` - Async unmount handler

### main.py
**Purpose:** Main PyQt6 application window with comprehensive UI for sensor monitoring and control

**Classes:**
- `MainWindow(QMainWindow)` - Main application window
  - `__init__(self)` - Initialize main window
  - `setup_ui(self)` - Set up the user interface
  - `_create_camera_group(self)` - Create camera control group
  - `_create_sensor_cards_group(self)` - Create sensor display cards
    - `create_card(title, initial_text="--", unit="")` - Helper to create individual sensor cards
  - `_create_controllers_group(self)` - Create controllers configuration group
  - `_create_motor_control_group(self)` - Create motor control interface
  - `_create_plots_group(self)` - Create data visualization plots
    - `create_plot_tab(title)` - Helper to create plot tabs
  - `connect_signals_and_slots(self)` - Connect UI signals to handlers
  - `initialize_controllers(self)` - Initialize hardware controllers
  - `initialize_timers(self)` - Set up update timers
  - `setup_email_worker(self)` - Configure email alert system
  - `update_all_data(self)` - Update all sensor readings
  - `update_sensor_readings(self)` - Update sensor display values
  - `check_rain_status(self)` - Check and handle rain detection
  - `startup_check(self)` - Perform startup system checks
  - `connect_camera(self)` - Connect to camera device
  - `disconnect_camera(self)` - Disconnect camera device
  - `update_camera_feed(self)` - Update camera video feed
  - `open_motor(self)` - Open motor to specified position
  - `close_motor(self)` - Close motor to home position
  - `closeEvent(self, event)` - Handle application close event

### workers.py
**Purpose:** Background worker threads for async operations

**Classes:**
- `EmailWorker(QObject)` - Worker for sending email alerts
  - `send_rain_email(self)` - Send rain detection alert email

---

## Controllers

### ac_adapter.py
**Purpose:** Adapter pattern implementation for AC device control

**Classes:**
- `ACAdapter` - Adapter for AC device operations
  - `__init__(self, device: Optional[AC] = None) -> None` - Initialize adapter
  - `connect(self, *args, **kwargs) -> Any` - Connect to AC device
  - `disconnect(self) -> Any` - Disconnect from AC device
  - `power(self, on: bool) -> Any` - Control power state
  - `set_mode(self, mode: str) -> Any` - Set AC operation mode
  - `set_temperature(self, value: int) -> Any` - Set target temperature
  - `set_fan_speed(self, speed: str | int) -> Any` - Set fan speed
  - `get_status(self) -> dict[str, Any]` - Get current status
  - `_get(self, names: list[str]) -> Any` - Internal getter
  - `_has(self, names: list[str]) -> bool` - Check attribute existence
  - `_call(self, names: list[str], *args, **kwargs) -> Any` - Internal method caller

### motor_controller.py
**Purpose:** Motor control and validation

**Classes:**
- `StrictIntValidator(QIntValidator)` - Custom integer input validator
  - `__init__(self, minimum, maximum, parent=None)` - Initialize validator
  - `validate(self, input_str, pos)` - Validate input string

- `MotorController(QObject)` - Motor control logic
  - `__init__(self, parent=None)` - Initialize motor controller
  - `driver(self)` - Get motor driver instance
  - `_on_connect(self)` - Handle connection event
  - `_on_move(self)` - Handle move command
  - `is_connected(self)` - Check connection status
  - `move(self)` - Execute motor movement
  - `connect(self)` - Connect to motor

### temp_controller.py
**Purpose:** Temperature controller management

**Classes:**
- `TempController(QObject)` - Temperature control logic
  - `__init__(self, parent=None)` - Initialize temperature controller
  - `connect_controller(self)` - Connect to temperature controller
  - `_find_tc_port(self)` - Auto-detect temperature controller port
  - `set_temperature(self)` - Set target temperature
  - `_upd(self)` - Update temperature readings
  - `current_temp(self)` - Get current temperature
  - `setpoint(self)` - Get temperature setpoint
  - `is_connected(self)` - Check connection status

### thp_controller.py
**Purpose:** Temperature, Humidity, Pressure sensor controller

**Classes:**
- `THPController(QObject)` - THP sensor control logic
  - `__init__(self, port=None, parent=None)` - Initialize THP controller
  - `connect_sensor(self)` - Connect to THP sensor
  - `_find_thp_port(self)` - Auto-detect THP sensor port
  - `_update_data(self)` - Update sensor readings
  - `get_latest(self)` - Get latest sensor data
  - `is_connected(self)` - Check connection status

---

## Drivers

### motor.py
**Purpose:** Low-level motor driver using Modbus protocol

**Functions:**
- `modbus_crc16(data: bytes) -> int` - Calculate Modbus CRC16 checksum

**Classes:**
- `MotorConnectThread(QThread)` - Threaded motor connection handler
  - `__init__(self, port_name, parent=None)` - Initialize connection thread
  - `run(self)` - Execute connection in thread

- `MotorDriver` - Motor communication driver
  - `__init__(self, serial_obj)` - Initialize with serial connection
  - `move_to(self, angle: int) -> (bool, str)` - Move motor to angle
  - `check_rain_status(self) -> (bool, str)` - Query rain sensor status

### tc36_25_driver.py
**Purpose:** TC36-25 temperature controller driver

**Classes:**
- `TC36_25` - Driver for TC36-25 temperature controller
  - `__init__(self, port: str = "COM16", delay_char: float = 0.001)` - Initialize driver
  - `_to_hex32(value: int) -> str` - Convert to 32-bit hex string
  - `_csum(payload: str) -> str` - Calculate checksum
  - `_tx(self, cmd: str, value_hex: str) -> str` - Transmit command
  - `_write(self, cmd: str, value_hex: str = "00000000")` - Write command
  - `_read(self, cmd: str) -> str` - Read command
  - `enable_computer_setpoint(self) -> None` - Enable computer control
  - `power(self, on: bool) -> None` - Control power state
  - `get_temperature(self) -> float` - Get current temperature
  - `get_setpoint(self) -> float` - Get temperature setpoint
  - `set_setpoint(self, temp_c: float) -> None` - Set temperature setpoint
  - `close(self)` - Close connection
  - `__enter__(self)` - Context manager enter
  - `__exit__(self, exc_type, exc, tb)` - Context manager exit

### thp_sensor.py
**Purpose:** THP (Temperature, Humidity, Pressure) sensor driver

**Functions:**
- `read_thp_sensor_data(port_name, baud_rate=9600, timeout=1)` - Read sensor data from serial port

---

## Services

### ac_service.py
**Purpose:** Service layer for AC device management with polling and event handling

**Classes:**
- `ACService(QObject)` - AC device service with signal/slot communication
  - `__init__(self, port: Optional[AC] = None, poll_ms: int = 1000, parent: Optional[QObject] = None) -> None` - Initialize service
  - `start(self) -> None` - Start the service
  - `stop(self) -> None` - Stop the service
  - `connect_device(self) -> None` - Connect to AC device
  - `_on_started(self) -> None` - Handle service start
  - `_set_power(self, on: bool) -> None` - Set power state
  - `_set_mode(self, mode: str) -> None` - Set operation mode
  - `_set_temperature(self, value: float) -> None` - Set temperature
  - `_set_fan_speed(self, speed: str|int) -> None` - Set fan speed
  - `_poll_now(self) -> None` - Poll device status

---

## UI Components

### ac_control_widget.py
**Purpose:** PyQt6 widget for AC control interface

**Classes:**
- `ACControlWidget(QWidget)` - Widget for AC device control
  - `__init__(self, parent: Optional[QWidget] = None) -> None` - Initialize widget
  - `_on_connect(self) -> None` - Handle connect button
  - `_on_disconnect(self) -> None` - Handle disconnect button
  - `_on_temp_changed(self, value: float) -> None` - Handle temperature change
  - `_on_status(self, s: dict) -> None` - Update status display
  - `_on_error(self, msg: str) -> None` - Display error message
  - `_on_connected(self, ok: bool) -> None` - Handle connection status change
  - `_set_controls_enabled(self, enabled: bool) -> None` - Enable/disable controls
  - `closeEvent(self, event) -> None` - Handle widget close

---

## Configuration

### config.py
**Purpose:** Centralized configuration file for application settings

**Constants:**
- `APP_NAME` = "EM-27 SciGlob" - Application name
- `MIN_WINDOW_SIZE` = (1200, 800) - Minimum window dimensions
- `TIMER_INTERVAL_MS` = 1000 - Update interval in milliseconds
- `CAMERA_FRAME_RATE` = 33 - Camera frame rate (~30 fps)

**Serial Port Settings:**
- `TEMP_CONTROLLER_PORT` = "COM2" - Temperature controller port
- `THP_CONTROLLER_PORT` = "COM7" - THP sensor port
- `MOTOR_CONTROLLER_PORT` = "COM8" - Motor controller port

**SMTP Email Settings:**
- `SMTP_SERVER` = "smtp.gmail.com" - Email server
- `SMTP_PORT` = 587 - Email port
- `SENDER_EMAIL` - Email sender address
- `SENDER_PASSWORD` - Email authentication password
- `RECEIVER_EMAILS` - List of recipient email addresses

**UI Styles:**
- `STYLES` - Dictionary containing CSS styles for various UI components:
  - `main_window` - Main window styling
  - `group_box` - Group box styling
  - `connect_btn` - Connect button styling
  - `disconnect_btn` - Disconnect button styling
  - `rain_indicator_*` - Rain status indicator styles

**Motor Positions:**
- `MOTOR_OPEN_POSITION` = "-2300" - Motor open position
- `MOTOR_CLOSED_POSITION` = "0" - Motor closed position

---

## Data Models

### data_model.py
**Purpose:** Data model for sensor readings storage and management

**Classes:**
- `SensorDataModel` - Model for storing and managing sensor data
  - `__init__(self)` - Initialize data model
  - `add_data_point(self, temp, hum, pres)` - Add new sensor reading

---

## Architecture Overview

### Component Hierarchy
```
Main Application (main.py)
├── Controllers/
│   ├── TempController (temp_controller.py)
│   ├── THPController (thp_controller.py)
│   ├── MotorController (motor_controller.py)
│   └── ACAdapter (ac_adapter.py)
├── Drivers/
│   ├── TC36_25 (tc36_25_driver.py)
│   ├── MotorDriver (motor.py)
│   └── THP Sensor Functions (thp_sensor.py)
├── Services/
│   └── ACService (ac_service.py)
├── UI/
│   └── ACControlWidget (ac_control_widget.py)
└── Workers/
    └── EmailWorker (workers.py)
```

### Communication Flow
1. **Hardware Layer**: Drivers communicate with physical devices via serial ports
2. **Controller Layer**: Controllers manage drivers and provide high-level interfaces
3. **Service Layer**: Services handle async operations and state management
4. **UI Layer**: PyQt6 widgets provide user interface and visualization
5. **Worker Layer**: Background threads handle long-running operations

### Key Features
- **Real-time monitoring**: Temperature, humidity, pressure sensors
- **Motor control**: Automated positioning with rain detection
- **Climate control**: Temperature controller integration
- **AC control**: Modbus-based air conditioning management
- **Camera integration**: Live video feed display
- **Data visualization**: Real-time plotting of sensor data
- **Alert system**: Email notifications for rain events
- **Multi-threaded**: Non-blocking operations using QThread

---

## File Dependencies

### Critical Dependencies
- **PyQt6**: UI framework and event handling
- **serial/pyserial**: Serial port communication
- **textual**: Terminal UI for AC.py
- **pymodbus**: Modbus protocol communication
- **matplotlib**: Data visualization

### Import Structure
- Controllers depend on Drivers
- Main application depends on Controllers, Services, and UI
- Services depend on Controllers and Adapters
- UI components are standalone with service integration

---

*Last Updated: 2025-01-07*
*Project: EM27-AC*
*Repository: https://github.com/ashutoshjoshi1/EM27-AC.git*
