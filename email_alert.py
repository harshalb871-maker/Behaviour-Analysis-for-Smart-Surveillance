# Safe email alerts for a smart surveillance system.
# - Credentials loaded from environment only (never hardcoded)
# - Per-class cooldown + global rate limiting (anti-spam / anti-DoS)
# - Attachment path restricted to the alerts directory (no path traversal)
# - Input sanitization to prevent header injection
# - TLS enforced, timeouts, size caps on attachments
# - Non-blocking worker threads; thread-safe cooldown tracking

import os
import re
import smtplib
import ssl
import threading
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

from config import Config
from logger import logger


# ----------------------------- Constants -----------------------------

# Only these extensions may be attached.
_ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}

# Hard cap for any single attachment (5 MB).
_MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024

# SMTP connection settings.
_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587
_SMTP_TIMEOUT = 20

# Characters allowed in a class name after sanitization.
_SAFE_CLASS_RE = re.compile(r"[^A-Za-z0-9 _\-]")

# Simple RFC-5322-ish email check (defense in depth; not a full validator).
_EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")

# Per-process global rate limit: max emails per rolling 60 seconds.
_GLOBAL_RATE_LIMIT = 30
_GLOBAL_RATE_WINDOW = 60.0


# ----------------------------- Helpers --------------------------------

def _clean_header(value: str, max_len: int = 200) -> str:
    """Strip CR/LF and control chars to prevent email header injection."""
    if value is None:
        return ""
    # Remove CR and LF first (the actual injection vector), then collapse
    # remaining control characters.
    cleaned = value.replace("\r", " ").replace("\n", " ")
    cleaned = "".join(ch for ch in cleaned if ch.isprintable() or ch == " ")
    cleaned = cleaned.strip()
    return cleaned[:max_len]


def _is_valid_email(address: str) -> bool:
    """Basic sanity check for an email address used in headers."""
    if not address or len(address) > 254:
        return False
    if "\r" in address or "\n" in address:
        return False
    return bool(_EMAIL_RE.match(address))


def _sanitize_class_name(class_name: str, max_len: int = 60) -> str:
    """Return a filesystem/header-safe class label."""
    name = _SAFE_CLASS_RE.sub("_", str(class_name)).strip("_")
    return (name or "detection")[:max_len]


def _resolve_safe_image(image_path, base_dir: Path) -> Path | None:
    """
    Resolve image_path and confirm it stays inside base_dir with an allowed
    suffix and a sane size. Returns the resolved Path or None.
    """
    if not image_path:
        return None
    try:
        candidate = Path(image_path).resolve()
        base = base_dir.resolve()
    except (OSError, RuntimeError):
        return None

    # Path traversal guard.
    if base not in candidate.parents and candidate != base:
        logger.warning("Attachment rejected (outside alert dir): %s", candidate)
        return None

    if candidate.suffix.lower() not in _ALLOWED_IMAGE_SUFFIXES:
        logger.warning("Attachment rejected (bad extension): %s", candidate)
        return None

    if not candidate.is_file():
        logger.warning("Attachment missing: %s", candidate)
        return None

    try:
        if candidate.stat().st_size > _MAX_ATTACHMENT_BYTES:
            logger.warning("Attachment too large: %s", candidate)
            return None
    except OSError:
        return None

    return candidate


# ----------------------------- Email sender ---------------------------

def send_alert_email(subject, body, image_path=None, receiver=None):
    """
    Send an alert email. Returns True only on confirmed success.

    All inputs are validated/sanitized before use. Credentials come from
    Config (which should read from the environment/.env).
    """
    # --- Credentials -------------------------------------------------
    sender = (Config.EMAIL_SENDER or "").strip()
    password = (Config.EMAIL_PASSWORD or "").strip().replace(" ", "")
    recipient = (receiver or Config.EMAIL_RECEIVER or "").strip()

    if not sender or not password or not recipient:
        logger.warning("Email not sent: missing sender, password, or recipient.")
        return False

    if not _is_valid_email(sender) or not _is_valid_email(recipient):
        logger.warning("Email not sent: invalid sender or recipient format.")
        return False

    # --- Message construction ---------------------------------------
    message = EmailMessage()
    message["Subject"] = _clean_header(subject)
    message["From"] = formataddr(("Surveillance Alerts", sender))
    message["To"] = recipient
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=sender.split("@")[-1] or None)
    message.set_content(body)

    # --- Optional attachment (path-confined) ------------------------
    if image_path:
        safe_path = _resolve_safe_image(image_path, Config.ALERTS_DIR)
        if safe_path is None:
            # Non-fatal: still send the text alert.
            logger.info("Continuing without attachment for this alert.")
        else:
            subtype = "png" if safe_path.suffix.lower() == ".png" else "jpeg"
            try:
                with safe_path.open("rb") as fh:
                    message.add_attachment(
                        fh.read(),
                        maintype="image",
                        subtype=subtype,
                        filename=safe_path.name,
                    )
            except OSError:
                logger.exception("Failed to read attachment: %s", safe_path)

    # --- Transport ---------------------------------------------------
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=_SMTP_TIMEOUT) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(sender, password)
            smtp.send_message(message)
        logger.info("Alert email sent to %s", recipient)
        return True
    except smtplib.SMTPAuthenticationError:
        # Never log the password; just the fact of failure.
        logger.error("SMTP authentication failed. Check EMAIL_PASSWORD (app password).")
        return False
    except (smtplib.SMTPException, ssl.SSLError, OSError):
        logger.exception("Failed to send alert email.")
        return False
    except Exception:
        logger.exception("Unexpected error sending alert email.")
        return False


# ----------------------------- Alert system ---------------------------

class AlertSystem:
    """
    Thread-safe, rate-limited alert dispatcher.

    - One cooldown per detected class.
    - One global rolling-window cap to protect against runaway alerts.
    - Emails are dispatched on daemon worker threads (non-blocking UI).
    """

    def __init__(self, cooldown=10, alert_folder=None):
        Config.ensure_directories()

        self.alert_folder = Path(alert_folder) if alert_folder else Config.ALERTS_DIR
        self.alert_folder.mkdir(parents=True, exist_ok=True)

        self.cooldown = max(0.0, float(cooldown))
        self.last_alert_time: dict[str, float] = {}

        self.lock = threading.Lock()

        # Rolling-window global rate limiter.
        self._recent_sends: list[float] = []

    # -------- configuration check --------
    @staticmethod
    def email_is_configured(recipient) -> bool:
        sender = (Config.EMAIL_SENDER or "").strip()
        password = (Config.EMAIL_PASSWORD or "").strip().replace(" ", "")
        recipient_value = (recipient or "").strip()
        return bool(
            sender
            and password
            and recipient_value
            and _is_valid_email(sender)
            and _is_valid_email(recipient_value)
        )

    # -------- global rate limiter --------
    def _global_rate_ok_locked(self) -> bool:
        """Must be called while holding self.lock."""
        now = time.monotonic()
        cutoff = now - _GLOBAL_RATE_WINDOW
        self._recent_sends = [t for t in self._recent_sends if t >= cutoff]
        return len(self._recent_sends) < _GLOBAL_RATE_LIMIT

    # -------- public entry point --------
    def trigger_alert(self, recipient, class_name, confidence, frame=None):
        """
        Validate, respect cooldowns, then queue an email.
        Returns (queued: bool, message: str).
        """
        if not self.email_is_configured(recipient):
            return False, "Email settings incomplete; configure .env and receiver."

        # Clamp confidence to a sane range.
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            return False, "Invalid confidence value."

        safe_class = _sanitize_class_name(class_name)
        now = time.monotonic()

        with self.lock:
            previous = self.last_alert_time.get(safe_class)
            if previous is not None and (now - previous) < self.cooldown:
                remaining = self.cooldown - (now - previous)
                return False, f"Cooldown active ({remaining:.1f}s remaining)."

            if not self._global_rate_ok_locked():
                return False, "Global alert rate limit reached; try again shortly."

            # Reserve the slot before starting the worker.
            self.last_alert_time[safe_class] = now
            self._recent_sends.append(now)

        worker = threading.Thread(
            target=self._send_in_background,
            args=(recipient.strip(), safe_class, confidence),
            daemon=True,
            name=f"EmailAlert-{safe_class}",
        )
        worker.start()
        logger.info(
            "Alert queued: class=%s confidence=%.2f recipient=%s",
            safe_class,
            confidence,
            recipient.strip(),
        )
        return True, f"Alert queued for {safe_class}."

    # -------- worker --------
    def _send_in_background(self, recipient, class_name, confidence):
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        subject = f"Surveillance Alert: {class_name}"
        body = (
            "A class recognized by your configured model was detected.\n\n"
            f"Class: {class_name}\n"
            f"Confidence: {confidence:.2%}\n"
            f"Time: {timestamp}\n\n"
            "Review the live application before taking action.\n"
            "This is an automated message; do not reply.\n"
        )
        if not send_alert_email(subject, body, image_path=None, receiver=recipient):
            logger.error("Alert email delivery failed for class '%s'.", class_name)