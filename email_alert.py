import os
import smtplib
import threading
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import cv2

from config import Config
from logger import logger


# Keep the original function available for existing imports/calls.
def send_alert_email(subject, body, image_path=None):
    """Send a simple email using credentials from config.py.

    If image_path is provided and exists, attach the image.
    """
    sender = getattr(Config, "EMAIL_SENDER", None)
    password = getattr(Config, "EMAIL_PASSWORD", None)
    receiver = getattr(Config, "EMAIL_RECEIVER", None)

    if not sender or not password or not receiver:
        logger.warning(
            "Email credentials or receiver are not configured in Config."
        )
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = receiver
    message.set_content(body)

    if image_path and os.path.isfile(image_path):
        path = Path(image_path)
        # The evidence frames are saved as JPEG files by AlertSystem.
        suffix = path.suffix.lower()
        subtype = "png" if suffix == ".png" else "jpeg"
        with path.open("rb") as image_file:
            message.add_attachment(
                image_file.read(),
                maintype="image",
                subtype=subtype,
                filename=path.name,
            )

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as smtp:
            smtp.login(sender, password)
            smtp.send_message(message)
        logger.info("Alert email sent successfully.")
        return True
    except Exception as error:
        logger.exception("Failed to send alert email: %s", error)
        return False


class AlertSystem:
    """Save an annotated frame and email it without blocking the GUI.

    Args:
        cooldown: Minimum seconds between alerts for the same detected class.
        alert_folder: Optional evidence directory. Defaults to project/alerts.
    """

    def __init__(self, cooldown=10, alert_folder=None):
        project_folder = Path(__file__).resolve().parent
        self.alert_folder = (
            Path(alert_folder) if alert_folder else project_folder / "alerts"
        )
        self.alert_folder.mkdir(parents=True, exist_ok=True)

        self.cooldown = max(0, float(cooldown))
        self.last_alert_time = {}
        self.lock = threading.Lock()

    def send_email(self, recipient, class_name, confidence, image_path):
        """Send an alert email with the captured evidence attached."""
        sender = getattr(Config, "EMAIL_SENDER", None)
        password = getattr(Config, "EMAIL_PASSWORD", None)

        if not sender or not password:
            raise ValueError(
                "Configure EMAIL_SENDER and EMAIL_PASSWORD in config.py."
            )
        if not recipient or not recipient.strip():
            raise ValueError("A recipient email address is required.")

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = EmailMessage()
        message["Subject"] = f"Surveillance Alert: {class_name}"
        message["From"] = sender
        message["To"] = recipient.strip()
        message.set_content(
            "An object configured for alerts was detected.\n\n"
            f"Class: {class_name}\n"
            f"Confidence: {confidence:.2%}\n"
            f"Time: {timestamp}\n\n"
            "Please review the attached image."
        )

        image_file_path = Path(image_path)
        suffix = image_file_path.suffix.lower()
        subtype = "png" if suffix == ".png" else "jpeg"
        with image_file_path.open("rb") as image_file:
            message.add_attachment(
                image_file.read(),
                maintype="image",
                subtype=subtype,
                filename=image_file_path.name,
            )

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as smtp:
            smtp.login(sender, password)
            smtp.send_message(message)

        logger.info("Alert email sent for class '%s'.", class_name)

    def trigger_alert(self, recipient, class_name, confidence, frame):
        """Queue an alert; returns (success, message) immediately."""
        if not recipient or not recipient.strip():
            return False, "Enter a recipient email address."
        if frame is None:
            return False, "No frame was provided for the alert."

        now = time.time()
        with self.lock:
            previous = self.last_alert_time.get(class_name, 0)
            if now - previous < self.cooldown:
                return False, "Alert skipped: cooldown active."
            # Reserve the cooldown before starting the worker thread.
            self.last_alert_time[class_name] = now

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe_class = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in str(class_name)
        ) or "detection"
        image_path = self.alert_folder / f"{safe_class}_{timestamp}.jpg"

        try:
            saved = cv2.imwrite(str(image_path), frame)
        except Exception as error:
            saved = False
            logger.exception("Could not save alert evidence: %s", error)

        if not saved:
            with self.lock:
                self.last_alert_time.pop(class_name, None)
            return False, "Could not save evidence image."

        worker = threading.Thread(
            target=self._send_in_background,
            args=(recipient.strip(), class_name, float(confidence), str(image_path)),
            daemon=True,
        )
        worker.start()
        logger.info("Alert queued for class '%s'.", class_name)
        return True, f"Alert queued for {class_name}."

    def _send_in_background(self, recipient, class_name, confidence, image_path):
        try:
            self.send_email(recipient, class_name, confidence, image_path)
        except Exception as error:
            logger.exception("Email alert failed for '%s': %s", class_name, error)


if __name__ == "__main__":
    # A simple import/configuration check; this does not send an email.
    alert_system = AlertSystem()
    print("email_alert.py loaded successfully.")
    print(f"Evidence folder: {alert_system.alert_folder}")
    print("To test sending, call AlertSystem.trigger_alert(...) from your GUI")