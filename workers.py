import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

import config

class EmailWorker(QObject):
    """A worker to send emails in a non-blocking way."""
    finished = pyqtSignal()
    error = pyqtSignal(str)

    @pyqtSlot()
    def send_rain_email(self):
        """Constructs and sends the rain alert email."""
        msg = MIMEMultipart()
        msg["From"] = config.SENDER_EMAIL
        msg["To"] = ", ".join(config.RECEIVER_EMAILS)
        msg["Subject"] = "EM-27 Weather Update"

        body = (
            "Hello,\n\n"
            "It is raining. The EM-27 head has been automatically closed.\n\n"
            "Regards,\nEM-27 Monitoring System"
        )
        msg.attach(MIMEText(body, "plain"))

        try:
            with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as server:
                server.starttls()
                server.login(config.SENDER_EMAIL, config.SENDER_PASSWORD)
                server.send_message(msg)
            self.finished.emit()
        except Exception as e:
            self.error.emit(f"Failed to send email: {e}")