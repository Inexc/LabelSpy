import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Token
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Google Gemini API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Бесплатный лимит сканов в месяц
FREE_SCANS_PER_MONTH = 5

# Название бота
BOT_NAME = "LabelSpy"

# ID администратора бота
ADMIN_ID = int(os.getenv("ADMIN_ID", "871764715"))

