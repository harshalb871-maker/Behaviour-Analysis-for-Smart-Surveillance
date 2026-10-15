"""Multi-model YOLO detector including the Security Activity model."""

from pathlib import Path

import cv2

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
    """Run separate YOLO models on one frame and combine their detections."""

    def __init__(self, model_path=None, fighting_model_path=None, running_model_path=None, security_activity_model_path=None):
        base_dir = Path(__file__).resolve().parent
        models_dir = base_dir / "models"

        # Keep the existing Config.MODEL_PATH as the weapon model path by default.
        self.model_paths = {
            "weapon": Path(model_path) if model_path else Path(Config.MODEL_PATH),
            "fighting": Path(fighting_model_path) if fighting_model_path else models_dir / "fighting_model.pt",
            "running": Path(running_model_path) if running_model_path else models_dir / "running_model.pt",
            # Six-class model: fight, knife, pistol, running, standing, walking.
            "security_activity": Path(security_activity_model_path) if security_activity_model_path else models_dir / "security_activity_model.pt",
        }
        self.models = {}
        self.load_errors = {}
        self._load_models()

    @property
    def is_ready(self):
        """True when at least one model loaded successfully."""
        return bool(self.models)

    @property
    def load_error(self):
        """Compatibility property for code that expects a single load_error."""
        if not self.load_errors:
            return None
        return "; ".join(f"{name}: {error}" for name, error in self.load_errors.items())

    @property
    def class_names(self):
        """Return unique class names from all loaded models."""
        names = []
        for model in self.models.values():
            model_names = model.names
            values = model_names.values() if isinstance(model_names, dict) else model_names
            for name in values:
                text = str(name)
                if text not in names:
                    names.append(text)
        return names

    def _load_models(self):
        if YOLO is None:
            message = f"Ultralytics is not installed: {_YOLO_IMPORT_ERROR}"
            self.load_errors["ultralytics"] = message
            logger.error(message)
            return

        for model_type, model_path in self.model_paths.items():
            if not model_path.is_file():
                message = f"Model file not found: {model_path}"
                self.load_errors[model_type] = message
                logger.warning(message)
                continue

            try:
                self.models[model_type] = YOLO(str(model_path))
                logger.info(
                    "Loaded %s model: %s; classes=%s",
                    model_type,
                    model_path,
                    self._names_for_model(self.models[model_type]),
                )
            except Exception as error:
                self.load_errors[model_type] = str(error)
                logger.exception("Could not load %s model: %s", model_type, error)

        if not self.models:
            logger.error("No YOLO models loaded. Check the model paths in models/ and config.py.")

    @staticmethod
    def _names_for_model(model):
        names = model.names
        if isinstance(names, dict):
            return [str(value) for _, value in sorted(names.items())]
        return [str(value) for value in names]

    @staticmethod
    def _class_name(model, class_id):
        names = model.names
        if isinstance(names, dict):
            return str(names.get(class_id, class_id))
        if 0 <= class_id < len(names):
            return str(names[class_id])
        return str(class_id)

    def process_frame(self, frame, confidence=0.70):
        """Return (annotated_frame, detections); each detection has class/confidence/box/model."""
        if frame is None:
            raise ValueError("The input frame is empty.")
        if not self.models:
            raise RuntimeError(self.load_error or "No YOLO models are ready.")

        confidence = max(0.0, min(1.0, float(confidence)))
        annotated_frame = frame.copy()
        detections = []

        # The GUI slider is the base threshold. Running often fires on action
        # scenes that are not running, so require a higher score for that model.
        # This reduces false positives but does not replace better training data.
        model_thresholds = {
            "weapon": confidence,
            "fighting": confidence,
            "running": max(confidence, 0.75),
            "security_activity": confidence,
        }

        # Draw each model's detections onto the same frame so boxes from earlier models remain.
        colors = {
            "weapon": (0, 0, 255),      # red
            "fighting": (0, 165, 255),  # orange
            "running": (255, 0, 0),     # blue
            "security_activity": (0, 255, 0),  # green
        }

        for model_type, model in self.models.items():
            try:
                results = model.predict(
                    source=frame,
                    conf=model_thresholds.get(model_type, confidence),
                    verbose=False,
                )
            except Exception:
                logger.exception("Prediction failed for %s model", model_type)
                continue

            for result in results:
                if result.boxes is None:
                    continue

                for box in result.boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                    score = float(box.conf[0].item())
                    class_id = int(box.cls[0].item())
                    class_name = self._class_name(model, class_id)
                    label = f"{model_type}: {class_name} {score:.2f}"
                    color = colors.get(model_type, (0, 255, 0))

                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
                    text_y = max(22, y1 - 8)
                    text_x = max(4, min(x1, annotated_frame.shape[1] - 180))
                    cv2.putText(
                        annotated_frame,
                        label,
                        (text_x, text_y),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.60,   # Keep labels readable without covering the scene
                        color,
                        2,
                        cv2.LINE_AA,
                    )

                    detections.append({
                        "class": class_name,
                        "confidence": score,
                        "box": (x1, y1, x2, y2),
                        "model": model_type,
                    })

        return annotated_frame, detections

    def save_capture(self, frame, filename):
        """Save a frame only when Config.SAVE_DETECTION_IMAGES is enabled."""
        if not getattr(Config, "SAVE_DETECTION_IMAGES", False):
            logger.info("Capture image saving is disabled; no image was written.")
            return ""

        Config.CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        filepath = Config.CAPTURES_DIR / filename
        if not cv2.imwrite(str(filepath), frame):
            raise OSError(f"Could not save capture image: {filepath}")
        logger.info("Capture saved: %s", filepath)
        return str(filepath)
