import os
import queue
import re
import smtplib
import ssl
import threading
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

import cv2

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

# Email bhejne ki koshish kitni baar karni hai aur har koshish ke beech kitna wait.
_SEND_RETRIES = 3
_RETRY_DELAY = 2.0

# In classes ke liye email nahi jayega (harmless activity). Isse email queue
# kaam ki alerts (fight, knife, pistol, running) ke liye free rehti hai.
# Sab classes par email chahiye to isse khali set() kar do.
IGNORED_ALERT_CLASSES = {"standing", "walking", "normal person", "person"}

# Per-process global rate limit: max emails per rolling 60 seconds.
_GLOBAL_RATE_LIMIT = 30

# Email ke saath jaane wali snapshot image.
_JPEG_QUALITY = 85          # 85 par ek frame ~100-200 KB (limit 5 MB hai)
_KEEP_ALERT_IMAGES = 200    # alerts/ folder mein itni hi latest images rakhi jayengi
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

def _prepare_message(subject, body, image_path=None, receiver=None):
    """
    Validate credentials and build the EmailMessage.
    Returns (message, sender, password, recipient) or None if not sendable.
    """
    # --- Credentials -------------------------------------------------
    sender = (Config.EMAIL_SENDER or "").strip()
    password = (Config.EMAIL_PASSWORD or "").strip().replace(" ", "")
    recipient = (receiver or Config.EMAIL_RECEIVER or "").strip()

    if not sender or not password or not recipient:
        logger.warning("Email not sent: missing sender, password, or recipient.")
        return None

    if not _is_valid_email(sender) or not _is_valid_email(recipient):
        logger.warning("Email not sent: invalid sender or recipient format.")
        return None

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

    return message, sender, password, recipient


def send_alert_email(subject, body, image_path=None, receiver=None):
    """
    Send an alert email. Returns True only on confirmed success.

    All inputs are validated/sanitized before use. Credentials come from
    Config (which should read from the environment/.env).
    """
    prepared = _prepare_message(subject, body, image_path, receiver)
    if prepared is None:
        return False
    message, sender, password, recipient = prepared

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


# ----------------------------- SMTP session ---------------------------

class _SmtpSession:
    """
    Ek hi Gmail SMTP connection ko baar-baar use karta hai (har email par naya
    connect + TLS + login nahi). Connection toote ya idle timeout ho to apne
    aap dobara connect ho jata hai. Sirf worker thread se use hota hai.
    """

    def __init__(self):
        self._smtp = None

    def close(self):
        smtp, self._smtp = self._smtp, None
        if smtp is None:
            return
        try:
            smtp.quit()
        except Exception:
            try:
                smtp.close()
            except Exception:
                pass

    def _connect(self, sender, password):
        smtp = smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=_SMTP_TIMEOUT)
        try:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(sender, password)
        except Exception:
            try:
                smtp.close()
            except Exception:
                pass
            raise
        self._smtp = smtp

    def send(self, message, sender, password):
        if self._smtp is not None:
            try:
                self._smtp.noop()  # connection abhi zinda hai?
                self._smtp.send_message(message)
                return
            except (smtplib.SMTPException, OSError):
                self.close()  # purana connection mar chuka; neeche naya banega
        self._connect(sender, password)
        self._smtp.send_message(message)


# ----------------------------- Alert system ---------------------------

class AlertSystem:
    """
    Thread-safe, rate-limited alert dispatcher.

    - One cooldown per detected class.
    - One global rolling-window cap to protect against runaway alerts.
    - Ek hi background worker emails ek-ek karke bhejta hai (queue se), taaki
      Gmail par ek saath kai login na hon. Fail hone par retry hota hai.
    - Email fail ho jaye to us class ka cooldown hata diya jata hai, taaki agli
      detection par dobara koshish ho.
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

        # Single worker + bounded queue.
        self._queue: "queue.Queue[dict]" = queue.Queue(maxsize=20)
        self._session = _SmtpSession()
        self._worker = threading.Thread(
            target=self._worker_loop, daemon=True, name="EmailAlertWorker"
        )
        self._worker.start()

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

    def _save_snapshot(self, frame, safe_class):
        """Detection wali frame ko alerts/ folder mein JPEG ke roop mein save karo."""
        if frame is None:
            return None
        try:
            self.alert_folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            name = safe_class.replace(" ", "_")
            path = self.alert_folder / f"{name}_{stamp}.jpg"
            if not cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), _JPEG_QUALITY]):
                logger.warning("Could not write alert snapshot: %s", path)
                return None
            self._prune_snapshots()
            return path
        except Exception:
            logger.exception("Could not save alert snapshot.")
            return None

    def _prune_snapshots(self):
        """Purani images hata do taaki disk na bhare (sirf latest _KEEP_ALERT_IMAGES rakho)."""
        files = sorted(self.alert_folder.glob("*.jpg"), key=lambda p: p.stat().st_mtime)
        for old in files[: max(0, len(files) - _KEEP_ALERT_IMAGES)]:
            try:
                old.unlink()
            except OSError:
                pass

    def _release_cooldown(self, key: str):
        with self.lock:
            self.last_alert_time.pop(key, None)

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
        if safe_class.lower() in IGNORED_ALERT_CLASSES:
            return False, f"Class '{safe_class}' is ignored for email alerts."

        # "Running" aur "running" ko ek hi class maano (cooldown key lowercase).
        key = safe_class.lower()
        now = time.monotonic()

        with self.lock:
            previous = self.last_alert_time.get(key)
            if previous is not None and (now - previous) < self.cooldown:
                remaining = self.cooldown - (now - previous)
                return False, f"Cooldown active ({remaining:.1f}s remaining)."

            if not self._global_rate_ok_locked():
                return False, "Global alert rate limit reached; try again shortly."

            # Reserve the slot before queueing.
            self.last_alert_time[key] = now
            self._recent_sends.append(now)

        # Slot mil chuka hai, to ab hi image save karo (lock ke bahar, taaki GUI na ruke).
        snapshot = self._save_snapshot(frame, safe_class)

        job = {
            "image_path": str(snapshot) if snapshot else None,
            "recipient": recipient.strip(),
            "class_name": safe_class,
            "key": key,
            "confidence": confidence,
            # Detection ka asli time (email mein yahi dikhega, bhejne ka nahi).
            "detected_at": datetime.now(timezone.utc),
            "queued_mono": now,
        }
        try:
            self._queue.put_nowait(job)
        except queue.Full:
            self._release_cooldown(key)
            logger.warning("Alert queue full; dropped alert for '%s'.", safe_class)
            return False, "Alert queue is full; email skipped."

        logger.info(
            "Alert queued: class=%s confidence=%.2f recipient=%s (queue size ~%d)",
            safe_class,
            confidence,
            job["recipient"],
            self._queue.qsize(),
        )
        return True, f"Alert queued for {safe_class}."

    # -------- worker --------
    def _worker_loop(self):
        while True:
            job = self._queue.get()
            try:
                self._deliver(job)
            except Exception:
                logger.exception("Unexpected error in email worker.")
                self._release_cooldown(job["key"])
            finally:
                self._queue.task_done()

    def _send_once(self, subject, body, recipient, image_path=None):
        prepared = _prepare_message(subject, body, image_path, recipient)
        if prepared is None:
            return False
        message, sender, password, _ = prepared
        try:
            self._session.send(message, sender, password)
            logger.info("Alert email sent to %s", recipient)
            return True
        except smtplib.SMTPAuthenticationError:
            logger.error("SMTP authentication failed. Check EMAIL_PASSWORD (app password).")
        except (smtplib.SMTPException, ssl.SSLError, OSError):
            logger.exception("Failed to send alert email.")
        except Exception:
            logger.exception("Unexpected error sending alert email.")
        self._session.close()
        return False

    def _deliver(self, job):
        class_name = job["class_name"]
        confidence = job["confidence"]
        detected = job["detected_at"].strftime("%Y-%m-%d %H:%M:%S UTC")
        subject = f"Surveillance Alert: {class_name}"
        body = (
            "A class recognized by your configured model was detected.\n\n"
            f"Class: {class_name}\n"
            f"Confidence: {confidence:.2%}\n"
            f"Detected at: {detected}\n\n"
            + ("A snapshot of the detection is attached.\n\n" if job.get("image_path") else "")
            + "Review the live application before taking action.\n"
            "This is an automated message; do not reply.\n"
        )

        for attempt in range(1, _SEND_RETRIES + 1):
            started = time.monotonic()
            ok = self._send_once(subject, body, job["recipient"], job.get("image_path"))
            if ok:
                logger.info(
                    "Alert email for '%s' delivered to SMTP in %.1fs (%.1fs after detection, attempt %d).",
                    class_name,
                    time.monotonic() - started,
                    time.monotonic() - job["queued_mono"],
                    attempt,
                )
                return
            if attempt < _SEND_RETRIES:
                logger.warning(
                    "Alert email for '%s' failed (attempt %d/%d); retrying in %.0fs.",
                    class_name, attempt, _SEND_RETRIES, _RETRY_DELAY,
                )
                time.sleep(_RETRY_DELAY)

        logger.error("Alert email delivery failed for class '%s' after %d attempts.", class_name, _SEND_RETRIES)
        # Agli detection par dobara koshish ho sake.
        self._release_cooldown(job["key"])