import logging
import os
from config import Config

def setup_logger():
    os.makedirs(Config.LOGS_DIR, exist_ok=True)
    
    logger = logging.getLogger("AppLogger")
    logger.setLevel(logging.DEBUG)
    
    # Formatter
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # File Handler
    fh = logging.FileHandler(os.path.join(Config.LOGS_DIR, 'app.log'))
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    
    # Console Handler
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    
    return logger

logger = setup_logger()
