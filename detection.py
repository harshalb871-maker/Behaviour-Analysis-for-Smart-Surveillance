import cv2
import os
from ultralytics import YOLO
from config import Config
from logger import logger

class ObjectDetector:
    def __init__(self):
        try:
            self.model = YOLO(Config.MODEL_PATH)
            logger.info("YOLO model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load YOLO model: {e}")
            self.model = None

    def process_frame(self, frame):
        if self.model is None:
            return frame, []
            
        results = self.model(frame, stream=True, verbose=False)
        detections = []
        
        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf[0])
                cls = int(box.cls[0])
                
                # Draw bounding box
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, f'{self.model.names[cls]} {conf:.2f}', (x1, y1 - 10), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                
                detections.append({
                    "class": self.model.names[cls],
                    "confidence": conf,
                    "box": (x1, y1, x2, y2)
                })
                
        return frame, detections

    def save_capture(self, frame, filename):
        os.makedirs(Config.CAPTURES_DIR, exist_ok=True)
        filepath = os.path.join(Config.CAPTURES_DIR, filename)
        cv2.imwrite(filepath, frame)
        logger.info(f"Capture saved: {filepath}")
        return filepath
