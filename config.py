import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    # Directories
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    MODELS_DIR = os.path.join(BASE_DIR, 'models')
    LOGS_DIR = os.path.join(BASE_DIR, 'logs')
    CAPTURES_DIR = os.path.join(BASE_DIR, 'captures')
    
    # Email Settings
    EMAIL_SENDER = os.getenv("EMAIL_SENDER", "")
    EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
    EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "")
    
    # App Settings
    APP_NAME = "Smart Surveillance"
    MODEL_PATH = os.path.join(MODELS_DIR, "yolov8n.pt")
