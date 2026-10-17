import threading
import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile

from detection import ObjectDetector

app = FastAPI(title="Surveillance Detection API")
detector = ObjectDetector()
lock = threading.Lock()   # ek model ko ek time par ek hi request use kare


@app.post("/detect")
async def detect(file: UploadFile = File(...), confidence: float = 0.7):
    data = np.frombuffer(await file.read(), np.uint8)
    frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="Valid image bhejo (jpg/png).")

    with lock:
        _, detections = detector.process_frame(frame, confidence)

    return {"detections": [
        {"class": d["class"], "confidence": round(d["confidence"], 3),
         "box": list(d["box"]), "alert": d.get("alert", True)}
        for d in detections
    ]}