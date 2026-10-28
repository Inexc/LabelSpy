import os
from pathlib import Path
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH)

# Telegram Bot Token
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Google Gemini API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# URL базы данных (PostgreSQL на Neon/Supabase/Render Postgres, либо SQLite при отсутствии)
DATABASE_URL = os.getenv("DATABASE_URL")

# Бесплатный лимит сканов в месяц
FREE_SCANS_PER_MONTH = 5


# Название бота
BOT_NAME = "LabelSpy"

# ID администратора бота
ADMIN_ID = int(os.getenv("ADMIN_ID", "871764715"))

# Параметры подписки
PREMIUM_STARS_PRICE = 50
PREMIUM_SUBSCRIPTION_DAYS = 30
DEMO_PREMIUM_DAYS = 7

# Защита от спама (секунды между сканами)
SCAN_COOLDOWN_SECONDS = 3

