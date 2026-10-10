"""Email alerts with evidence images and a per-class cooldown."""

import smtplib
import threading
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import cv2

from config import Config
from logger import logger


def send_alert_email(subject, body, image_path=None, receiver=None):
    """Send an email using .env credentials; return True only on success."""
    sender = Config.EMAIL_SENDER
    password = Config.EMAIL_PASSWORD
    recipient = (receiver or Config.EMAIL_RECEIVER).strip()

    if not sender or not password or not recipient:
        logger.warning("Email not sent: sender, app password, or recipient is missing.")
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body)

    if image_path:
        path = Path(image_path)
        if not path.is_file():
            logger.warning("Evidence image does not exist: %s", path)
            return False
        subtype = "png" if path.suffix.lower() == ".png" else "jpeg"
        with path.open("rb") as image_file:
            message.add_attachment(
                image_file.read(), maintype="image", subtype=subtype, filename=path.name
            )

    try:
        # Gmail requires an app password when 2-Step Verification is enabled.
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as smtp:
            smtp.login(sender, password)
            smtp.send_message(message)
        logger.info("Alert email sent to %s", recipient)
        return True
    except Exception:
        logger.exception("Failed to send alert email.")
        return False


class AlertSystem:
    """Save evidence and send email on a worker thread without blocking Tkinter."""

    def __init__(self, cooldown=10, alert_folder=None):
        Config.ensure_directories()
        self.alert_folder = Path(alert_folder) if alert_folder else Config.ALERTS_DIR
        self.alert_folder.mkdir(parents=True, exist_ok=True)
        self.cooldown = max(0.0, float(cooldown))
        self.last_alert_time = {}
        self.lock = threading.Lock()

    @staticmethod
    def email_is_configured(recipient):
        return bool(Config.EMAIL_SENDER and Config.EMAIL_PASSWORD and recipient and recipient.strip())

    def trigger_alert(self, recipient, class_name, confidence, frame):
        """Save evidence and queue an email; return immediately with a status."""
        if not self.email_is_configured(recipient):
            return False, "Email settings are incomplete; configure .env and receiver email."
        if frame is None:
            return False, "No frame was provided for the alert."

        class_name = str(class_name)
        now = time.monotonic()
        with self.lock:
            previous = self.last_alert_time.get(class_name)
            if previous is not None and now - previous < self.cooldown:
                return False, "Cooldown active."

            # Reserve this class's cooldown before starting a worker, avoiding duplicates.
            self.last_alert_time[class_name] = now

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe_class = "".join(
            char if char.isalnum() or char in "-_" else "_" for char in class_name
        ) or "detection"
        image_path = self.alert_folder / f"{safe_class}_{timestamp}.jpg"

        try:
            saved = cv2.imwrite(str(image_path), frame)
        except Exception:
            saved = False
            logger.exception("Could not save alert evidence.")

        if not saved:
            with self.lock:
                self.last_alert_time.pop(class_name, None)
            return False, "Could not save evidence image."

        worker = threading.Thread(
            target=self._send_in_background,
            args=(recipient.strip(), class_name, float(confidence), str(image_path)),
            daemon=True,
            name=f"EmailAlert-{safe_class}",
        )
        worker.start()
        logger.info("Alert queued: class=%s confidence=%.2f image=%s", class_name, confidence, image_path)
        return True, f"Alert queued for {class_name}; evidence saved."

    def _send_in_background(self, recipient, class_name, confidence, image_path):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subject = f"Surveillance Alert: {class_name}"
        body = (
            "A class recognized by your configured YOLO model was detected.\n\n"
            f"Class: {class_name}\n"
            f"Confidence: {confidence:.2%}\n"
            f"Time: {timestamp}\n\n"
            "The annotated evidence frame is attached. Review it before taking action."
        )
        if not send_alert_email(subject, body, image_path, receiver=recipient):
            logger.error("Alert email delivery failed for class '%s'.", class_name)
