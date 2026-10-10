# """Application entry point."""

import tkinter as tk

from config import Config
from gui import AppGUI
from logger import logger


def main():
    Config.ensure_directories()
    logger.info("Starting %s", Config.APP_NAME)
    root = tk.Tk()
    AppGUI(root)
    root.mainloop()
    logger.info("Application closed.")


if __name__ == "__main__":
    main()

