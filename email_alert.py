import smtplib
from email.message import EmailMessage
import os
from config import Config
from logger import logger

def send_alert_email(subject, body, image_path=None):
    if not Config.EMAIL_SENDER or not Config.EMAIL_PASSWORD or not Config.EMAIL_RECEIVER:
        logger.warning("Email credentials are not configured properly.")
        return
        
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = Config.EMAIL_SENDER
    msg['To'] = Config.EMAIL_RECEIVER
    msg.set_content(body)

    if image_path and os.path.exists(image_path):
        with open(image_path, 'rb') as f:
            img_data = f.read()
            msg.add_attachment(img_data, maintype='image', subtype='jpeg', filename=os.path.basename(image_path))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(Config.EMAIL_SENDER, Config.EMAIL_PASSWORD)
            smtp.send_message(msg)
        logger.info("Alert email sent successfully.")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
