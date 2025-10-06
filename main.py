import sys
import cv2
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QStatusBar, QPushButton, QLabel, QGroupBox, QTabWidget)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap, QFont
import pyqtgraph as pg

# Local imports
import config
from controllers.temp_controller import TempController
from controllers.thp_controller import THPController
from controllers.motor_controller import MotorController
from workers import EmailWorker
from data_model import SensorDataModel

class MainWindow(QMainWindow):
    # Signal to trigger the email worker
    request_send_email = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(config.APP_NAME)
        self.setMinimumSize(*config.MIN_WINDOW_SIZE)

        # Initialize core components
        self.data_model = SensorDataModel()
        self.setup_email_worker()
        
        # State flags
        self.was_raining = False
        self.email_sent_for_current_event = False
        self.current_motor_position = None # 0 for closed, 90 for open

        # Setup UI
        self.setup_ui()
        self.connect_signals_and_slots()

        # Initialize devices and timers
        self.initialize_controllers()
        self.initialize_timers()
        self.startup_check()

    def setup_ui(self):
        """Main UI setup method."""
        central = QWidget()
        central.setStyleSheet(config.STYLES["main_window"])
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # Status Bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)

        # --- Top Layout ---
        top_layout = QHBoxLayout()
        top_layout.addWidget(self._create_camera_group())
        top_layout.addWidget(self._create_sensor_cards_group())
        top_layout.addLayout(self._create_controllers_group())
        main_layout.addLayout(top_layout)

        # --- Bottom Layout ---
        main_layout.addWidget(self._create_motor_control_group())
        main_layout.addWidget(self._create_plots_group())

    def _create_camera_group(self):
        """Creates the camera feed UI group."""
        camera_group = QGroupBox("Camera Feed")
        camera_group.setStyleSheet(config.STYLES["group_box"])
        camera_group.setMaximumWidth(400)
        layout = QVBoxLayout(camera_group)

        self.camera_label = QLabel("No Camera Feed", alignment=Qt.AlignCenter)
        self.camera_label.setMinimumSize(360, 240)
        self.camera_label.setStyleSheet("background-color: #111; border-radius: 8px; color: white;")
        layout.addWidget(self.camera_label)
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.camera_connect_btn = QPushButton("Connect")
        self.camera_connect_btn.setStyleSheet(config.STYLES["connect_btn"])
        self.camera_disconnect_btn = QPushButton("Disconnect")
        self.camera_disconnect_btn.setStyleSheet(config.STYLES["disconnect_btn"])
        self.camera_disconnect_btn.setEnabled(False)
        btn_layout.addWidget(self.camera_connect_btn)
        btn_layout.addWidget(self.camera_disconnect_btn)
        layout.addLayout(btn_layout)

        return camera_group

    def _create_sensor_cards_group(self):
        """Creates the group of sensor display cards."""
        sensor_widget = QWidget()
        layout = QHBoxLayout(sensor_widget)
        layout.setSpacing(15)

        # Factory function for creating a card
        def create_card(title, initial_text="--", unit=""):
            card = QGroupBox()
            card.setFixedSize(160, 220)
            card.setStyleSheet("QGroupBox { background-color:#4e6d94; border-radius:10px; color:white; }")
            card_layout = QVBoxLayout(card)
            card_layout.addWidget(QLabel(title, alignment=Qt.AlignCenter))
            value_label = QLabel(initial_text, alignment=Qt.AlignCenter)
            value_label.setFont(QFont("Segoe UI", 20, QFont.Bold))
            card_layout.addWidget(value_label)
            card_layout.addWidget(QLabel(unit, alignment=Qt.AlignCenter))
            return card, value_label

        temp_card, self.lbl_t_value = create_card("Temperature", unit="°C")
        self.lbl_t_value.setStyleSheet("color:#FF7440;")
        
        hum_card, self.lbl_h_value = create_card("Humidity", unit="%")
        self.lbl_h_value.setStyleSheet("color:#55FF55;")

        pres_card, self.lbl_p_value = create_card("Pressure", unit="hPa")
        self.lbl_p_value.setStyleSheet("color:#88B9FF;")

        layout.addWidget(temp_card)
        layout.addWidget(hum_card)
        layout.addWidget(pres_card)

        return sensor_widget
        
    def _create_controllers_group(self):
        """Creates the UI group for various controllers."""
        layout = QVBoxLayout()
        # Initialize controller objects (UI part)
        self.temp_ctrl = TempController(parent=self)
        self.temp_ctrl.widget.setMaximumWidth(250)
        self.temp_ctrl.widget.setStyleSheet(config.STYLES["group_box"])
        layout.addWidget(self.temp_ctrl.widget)

        self.thp_ctrl = THPController(parent=self)
        self.thp_ctrl.groupbox.setMaximumWidth(250)
        self.thp_ctrl.groupbox.setStyleSheet(config.STYLES["group_box"])
        layout.addWidget(self.thp_ctrl.groupbox)
        
        return layout

    def _create_motor_control_group(self):
        """Creates the motor control UI group."""
        motor_group = QGroupBox("Motor Control")
        motor_group.setStyleSheet(config.STYLES["group_box"])
        layout = QVBoxLayout(motor_group)

        self.motor_ctrl = MotorController(parent=self)
        layout.addWidget(self.motor_ctrl.groupbox)

        self.rain_indicator = QLabel("Rain: Unknown")
        self.rain_indicator.setStyleSheet(config.STYLES["rain_indicator_unknown"])
        layout.addWidget(self.rain_indicator, alignment=Qt.AlignCenter)
        
        btn_layout = QHBoxLayout()
        self.open_btn = QPushButton("OPEN")
        self.open_btn.setMinimumHeight(50)
        self.open_btn.setStyleSheet(config.STYLES["connect_btn"])
        btn_layout.addWidget(self.open_btn)

        self.close_btn = QPushButton("CLOSE")
        self.close_btn.setMinimumHeight(50)
        self.close_btn.setStyleSheet(config.STYLES["disconnect_btn"])
        btn_layout.addWidget(self.close_btn)
        
        layout.addLayout(btn_layout)
        return motor_group
        
    def _create_plots_group(self):
        """Creates the group containing sensor data plots."""
        plots_group = QGroupBox("Sensor Data (Last 24 Hours)")
        plots_group.setStyleSheet(config.STYLES["group_box"])
        layout = QVBoxLayout(plots_group)
        tabs = QTabWidget()

        # Factory function for creating a plot
        def create_plot_tab(title):
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            plot_widget = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem(orientation='bottom')})
            plot_widget.setTitle(title)
            curve = plot_widget.plot(pen=pg.mkPen(width=2))
            tab_layout.addWidget(plot_widget)
            tabs.addTab(tab, title.split(" ")[0]) # Use first word for tab name
            return curve, plot_widget

        self.temp_curve, self.temp_plot = create_plot_tab("Temperature (24h)")
        self.hum_curve, self.hum_plot = create_plot_tab("Humidity (24h)")
        self.pres_curve, self.pres_plot = create_plot_tab("Pressure (24h)")
        
        layout.addWidget(tabs)
        return plots_group

    def connect_signals_and_slots(self):
        """Central place to connect all signals to slots."""
        # Camera
        self.camera_connect_btn.clicked.connect(self.connect_camera)
        self.camera_disconnect_btn.clicked.connect(self.disconnect_camera)
        
        # Motor
        self.open_btn.clicked.connect(self.open_motor)
        self.close_btn.clicked.connect(self.close_motor)
        self.motor_ctrl.status_signal.connect(self.status.showMessage)
        
        # Controllers
        self.temp_ctrl.status_signal.connect(self.status.showMessage)
        self.thp_ctrl.status_signal.connect(self.status.showMessage)
        
        # Email Worker
        self.request_send_email.connect(self.email_worker.send_rain_email)

    def initialize_controllers(self):
        """Connect to hardware controllers."""
        self.temp_ctrl.port = config.TEMP_CONTROLLER_PORT
        self.temp_ctrl.connect_controller()

        self.thp_ctrl.port = config.THP_CONTROLLER_PORT
        self.thp_ctrl.connect_controller()
        
        self.motor_ctrl.preferred_port = config.MOTOR_CONTROLLER_PORT
        self.motor_ctrl.connect()

    def initialize_timers(self):
        """Setup and start all QTimers."""
        # Camera Timer (started on connect)
        self.camera_timer = QTimer(self)
        self.camera_timer.timeout.connect(self.update_camera_feed)

        # Main data update timer
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_all_data)
        self.update_timer.start(config.TIMER_INTERVAL_MS)
        
    def setup_email_worker(self):
        """Creates and moves the EmailWorker to a separate thread."""
        self.email_thread = QThread()
        self.email_worker = EmailWorker()
        self.email_worker.moveToThread(self.email_thread)
        
        self.email_worker.finished.connect(lambda: self.status.showMessage("Rain email sent successfully."))
        self.email_worker.error.connect(lambda err_msg: self.status.showMessage(err_msg))
        
        self.email_thread.start()

    # --- Core Logic Methods ---

    def update_all_data(self):
        """Master update function called by the main timer."""
        self.update_sensor_readings()
        self.check_rain_status()

    def update_sensor_readings(self):
        """Fetch sensor data, update UI cards, and refresh plots."""
        latest = self.thp_ctrl.get_latest()
        temp = latest.get('temperature', float('nan'))
        hum = latest.get('humidity', float('nan'))
        pres = latest.get('pressure', float('nan'))
        
        # Update cards
        self.lbl_t_value.setText(f"{temp:.1f}")
        self.lbl_h_value.setText(f"{hum:.1f}")
        self.lbl_p_value.setText(f"{pres:.1f}")
        
        # Add to data model
        self.data_model.add_data_point(temp, hum, pres)
        
        # Update plots
        self.temp_curve.setData(list(self.data_model.timestamps), list(self.data_model.temperatures))
        self.hum_curve.setData(list(self.data_model.timestamps), list(self.data_model.humidities))
        self.pres_curve.setData(list(self.data_model.timestamps), list(self.data_model.pressures))

    def check_rain_status(self):
        """Check for rain and handle state transitions (closing, opening, emailing)."""
        if not self.motor_ctrl.is_connected():
            self.rain_indicator.setText("Rain: Unknown (Motor Off)")
            self.rain_indicator.setStyleSheet(config.STYLES["rain_indicator_unknown"])
            return

        try:
            success, message = self.motor_ctrl.driver.check_rain_status()
            is_raining = success and "Raining" in message
        except Exception as e:
            self.status.showMessage(f"Rain check error: {e}")
            return
            
        # State machine for rain handling
        if is_raining:
            self.rain_indicator.setText("RAINING")
            self.rain_indicator.setStyleSheet(config.STYLES["rain_indicator_raining"])
            self.open_btn.setEnabled(False)

            if self.current_motor_position == 90: # If it's open, close it
                self.status.showMessage("Rain detected! Auto-closing head.")
                self.close_motor()

            if not self.email_sent_for_current_event:
                self.request_send_email.emit() # Trigger email via worker
                self.email_sent_for_current_event = True
            
            self.was_raining = True

        else: # Not raining
            self.rain_indicator.setText("Not Raining")
            self.rain_indicator.setStyleSheet(config.STYLES["rain_indicator_not_raining"])
            self.open_btn.setEnabled(True)

            if self.was_raining: # If it just stopped raining, auto-open
                self.status.showMessage("Rain has stopped. Auto-opening head.")
                self.open_motor()
            
            # Reset flags for the next rain event
            self.was_raining = False
            self.email_sent_for_current_event = False

    def startup_check(self):
        """Check rain status on startup to decide initial motor position."""
        self.connect_camera() # Auto-connect camera on start
        try:
            success, message = self.motor_ctrl.driver.check_rain_status()
            if success and "Raining" in message:
                self.status.showMessage("Startup: Rain detected. Head will remain closed.")
                self.close_motor()
            else:
                self.status.showMessage("Startup: No rain. Auto-opening head.")
                self.open_motor()
        except Exception as e:
            self.status.showMessage(f"Startup rain check failed: {e}")

    # --- Slot Methods (Event Handlers) ---

    def connect_camera(self):
        """Connect to the camera and start the feed."""
        self.camera_feed = cv2.VideoCapture(0)
        if not self.camera_feed.isOpened():
            self.status.showMessage("Failed to open camera")
            return
        
        self.camera_feed.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
        self.camera_feed.set(cv2.CAP_PROP_EXPOSURE, -6)
        
        self.camera_timer.start(config.CAMERA_FRAME_RATE)
        self.camera_connect_btn.setEnabled(False)
        self.camera_disconnect_btn.setEnabled(True)
        self.status.showMessage("Camera connected.")

    def disconnect_camera(self):
        """Disconnect from the camera and stop the feed."""
        self.camera_timer.stop()
        if hasattr(self, 'camera_feed'):
            self.camera_feed.release()
        self.camera_label.setText("No Camera Feed")
        self.camera_label.setPixmap(QPixmap())
        self.camera_connect_btn.setEnabled(True)
        self.camera_disconnect_btn.setEnabled(False)
        self.status.showMessage("Camera disconnected.")

    def update_camera_feed(self):
        """Capture a frame, process it, and display it."""
        ret, frame = self.camera_feed.read()
        if not ret: return

        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        frame = cv2.convertScaleAbs(frame, alpha=0.8, beta=-30)
        
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        pix = QPixmap.fromImage(img).scaled(self.camera_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.camera_label.setPixmap(pix)

    def open_motor(self):
        """Command the motor to move to the open position."""
        if self.motor_ctrl.is_connected():
            self.motor_ctrl.angle_input.setText(config.MOTOR_OPEN_POSITION)
            self.motor_ctrl.move()
            self.current_motor_position = 90
            self.status.showMessage("Opening motor.")
        else:
            self.status.showMessage("Motor not connected.")
            
    def close_motor(self):
        """Command the motor to move to the closed position."""
        if self.motor_ctrl.is_connected():
            self.motor_ctrl.angle_input.setText(config.MOTOR_CLOSED_POSITION)
            self.motor_ctrl.move()
            self.current_motor_position = 0
            self.status.showMessage("Closing motor.")
        else:
            self.status.showMessage("Motor not connected.")
            
    def closeEvent(self, event):
        """Ensure threads are cleaned up properly on exit."""
        self.email_thread.quit()
        self.email_thread.wait()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 9))
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())