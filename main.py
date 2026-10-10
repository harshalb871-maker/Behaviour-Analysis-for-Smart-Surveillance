import tkinter as tk
from gui import AppGUI
from logger import logger

def main():
    logger.info("Starting Application...")
    root = tk.Tk()
    app = AppGUI(root)
    root.protocol("WM_DELETE_WINDOW", lambda: on_closing(root, app))
    root.mainloop()

def on_closing(root, app):
    app.stop_camera()
    root.destroy()
    logger.info("Application closed.")

if __name__ == "__main__":
    main()
