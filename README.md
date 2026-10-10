# YOLO Tkinter Application

This is a boilerplate application for running a real-time object detection system using OpenCV, YOLOv8, and a Tkinter GUI.

## Setup

1. **Install Dependencies**
   Make sure you have Python installed, then run:
   ```bash
   pip install -r requirements.txt
   ```

2. **Download YOLO Model**
   Place your trained YOLO model (e.g., `best.pt`) inside the `models/` directory.

3. **Configure Environment**
   Copy `.env.example` to `.env` and fill in your email credentials for alerts:
   ```bash
   cp .env.example .env
   ```

## Running the App

```bash
python main.py
```


