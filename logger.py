"""Application logging to both the console and logs/app.log."""

import logging

from config import Config


def setup_logger():
    Config.ensure_directories()
    app_logger = logging.getLogger("AppLogger")
    app_logger.setLevel(logging.INFO)
    app_logger.propagate = False

    # Avoid duplicate messages if setup_logger() is called more than once.
    if not app_logger.handlers:
        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s"
        )
        file_handler = logging.FileHandler(
            Config.LOGS_DIR / "app.log", encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        app_logger.addHandler(file_handler)
        app_logger.addHandler(console_handler)

    return app_logger


logger = setup_logger()
