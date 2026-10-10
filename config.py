"""Central configuration for the surveillance application."""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # Keep the error message friendly if requirements are not installed.
    load_dotenv = None


BASE_DIR = Path(__file__).resolve().parent
if load_dotenv is not None:
    load_dotenv(BASE_DIR / ".env")


class Config:
    BASE_DIR = BASE_DIR
    MODELS_DIR = BASE_DIR / "models"
    LOGS_DIR = BASE_DIR / "logs"
    CAPTURES_DIR = BASE_DIR / "captures"
    ALERTS_DIR = BASE_DIR / "alerts"

    # Place your custom Ultralytics YOLO weights at models/best.pt.
    MODEL_PATH = MODELS_DIR / "best.pt"

    EMAIL_SENDER = os.getenv("EMAIL_SENDER", "").strip()
    EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "").strip()
    EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "").strip()

    APP_NAME = "AI-Based Surveillance Detection System"

    @classmethod
    def ensure_directories(cls):
        """Create folders used for logs, evidence, and model files."""
        for folder in (cls.MODELS_DIR, cls.LOGS_DIR, cls.CAPTURES_DIR, cls.ALERTS_DIR):
            folder.mkdir(parents=True, exist_ok=True)
