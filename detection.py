# """Load a custom YOLO model and analyze individual OpenCV frames."""

import cv2

from pathlib import Path

from config import Config
from logger import logger

try:
    from ultralytics import YOLO
except ImportError as import_error:
    YOLO = None
    _YOLO_IMPORT_ERROR = import_error
else:
    _YOLO_IMPORT_ERROR = None


class ObjectDetector:
    """YOLO detector that returns an annotated frame and generic detections."""

    def __init__(self, model_path=None):
        self.model_path = Path(Config.MODEL_PATH if model_path is None else model_path)
        self.model = None
        self.load_error = None
        self._load_model()

    @property
    def is_ready(self):
        return self.model is not None

    @property
    def class_names(self):
        """Return class names supplied by the loaded model, without assumptions."""
        if self.model is None:
            return []
        names = self.model.names
        if isinstance(names, dict):
            return [str(name) for _, name in sorted(names.items())]
        return [str(name) for name in names]

    def _load_model(self):
        if YOLO is None:
            self.load_error = (
                "The Ultralytics package is not installed. Run: pip install -r requirements.txt"
            )
            logger.error("%s (%s)", self.load_error, _YOLO_IMPORT_ERROR)
            return

        if not self.model_path.is_file():
            self.load_error = (
                f"Model file was not found: {self.model_path}. "
                "Place your custom weights at models/best.pt."
            )
            logger.error(self.load_error)
            return

        try:
            self.model = YOLO(str(self.model_path))
            logger.info("YOLO model loaded: %s", self.model_path)
            logger.info("Model class names: %s", self.class_names)
        except Exception as error:
            self.load_error = f"Could not load YOLO model: {error}"
            self.model = None
            logger.exception(self.load_error)

    def process_frame(self, frame, confidence=0.70):
        """Return (annotated_frame, detections) for one BGR frame.

        Each detection dictionary has: class, confidence, and box.
        Confidence is a value from 0.0 to 1.0.
        """
        if frame is None:
            raise ValueError("The input frame is empty.")
        if self.model is None:
            raise RuntimeError(self.load_error or "The YOLO model is not ready.")

        confidence = float(confidence)
        confidence = max(0.0, min(1.0, confidence))
        results = self.model.predict(
            source=frame,
            conf=confidence,
            verbose=False,
        )
        detections = []
        annotated_frame = frame.copy()

        for result in results:
            annotated_frame = result.plot()
            if result.boxes is None:
                continue

            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                score = float(box.conf[0].item())
                class_id = int(box.cls[0].item())
                names = self.model.names
                class_name = names.get(class_id, str(class_id)) if isinstance(names, dict) else names[class_id]

                detections.append({
                    "class": str(class_name),
                    "confidence": score,
                    "box": (x1, y1, x2, y2),
                })

        return annotated_frame, detections

    def save_capture(self, frame, filename):
        """Save a frame to the captures folder and return its path."""
        Config.CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        filepath = Config.CAPTURES_DIR / filename
        if not cv2.imwrite(str(filepath), frame):
            raise OSError(f"Could not save capture image: {filepath}")
        logger.info("Capture saved: %s", filepath)
        return str(filepath)
