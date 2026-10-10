import tkinter as tk
from gui import AppGUI
from logger import logger


def main():
    logger.info("Starting Application...")

    root = tk.Tk()
    app = AppGUI(root)

    # Handle clicking the X button
    root.protocol(
        "WM_DELETE_WINDOW",
        lambda: on_closing(root, app)
    )

    root.mainloop()


def on_closing(root, app):
    try:
        app.on_close()
        logger.info("Application closed.")
    except Exception as error:
        logger.exception(f"Error while closing application: {error}")
        root.destroy()


if __name__ == "__main__":
    main()
