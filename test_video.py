
import tkinter as tk
from tkinter import filedialog
from ultralytics import YOLO

MODEL_PATH = "models/security_activity_model.pt"

root = tk.Tk()
root.withdraw()

video_path = filedialog.askopenfilename(
    title="Select a video for Security Activity Detection",
    filetypes=[
        ("Video files", "*.mp4 *.avi *.mov *.mkv"),
        ("All files", "*.*"),
    ],
)

if video_path:
    model = YOLO(MODEL_PATH)
    model.predict(
        source=video_path,
        conf=0.50,
        save=True,
        show=False,
    )
    print("Prediction completed.")
else:
    print("No video selected.")

root.destroy()
