"""
Configuration file for the Telegram Quiz Bot
Create a .env file with your actual values
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Bot Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
GROUP_ID = int(os.getenv("GROUP_ID", "-1001234567890"))

# Google Drive Configuration
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.pickle"
QUIZZES_FOLDER_NAME = "quizzes"

# Quiz Configuration
MIN_TIMER_SECONDS = 5
MAX_TIMER_SECONDS = 300
DEFAULT_TIMER_SECONDS = 30

# Logging Configuration
LOG_LEVEL = "INFO"
LOG_FILE = "bot.log"

# Flask Configuration (for Render deployment)
FLASK_PORT = int(os.getenv("PORT", 5000))
FLASK_HOST = "0.0.0.0"
FLASK_DEBUG = False
