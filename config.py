import os
from pathlib import Path
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH)

# Telegram Bot Token (обязательно)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Google Gemini API Key (обязательно)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# URL базы данных (PostgreSQL на Neon/Supabase/Render Postgres, либо SQLite при отсутствии)
DATABASE_URL = os.getenv("DATABASE_URL")

# Название и юзернейм бота
BOT_NAME = os.getenv("BOT_NAME", "LabelSpy").strip() or "LabelSpy"
BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip().lstrip("@")

# ID администратора бота (необязательно, если не задан — админ-функции отключены)
_raw_admin_id = os.getenv("ADMIN_ID", "").strip()
ADMIN_ID = int(_raw_admin_id) if _raw_admin_id.isdigit() else None

# Лимиты и параметры подписки
FREE_SCANS_PER_MONTH = int(os.getenv("FREE_SCANS_PER_MONTH", "5"))
PREMIUM_STARS_PRICE = int(os.getenv("PREMIUM_STARS_PRICE", "50"))
PREMIUM_SUBSCRIPTION_DAYS = int(os.getenv("PREMIUM_SUBSCRIPTION_DAYS", "30"))
DEMO_PREMIUM_DAYS = int(os.getenv("DEMO_PREMIUM_DAYS", "7"))

# Защита от спама (секунды между сканами)
SCAN_COOLDOWN_SECONDS = int(os.getenv("SCAN_COOLDOWN_SECONDS", "3"))

# Список моделей Gemini с поддержкой Vision (через запятую)
_default_gemini_models = "gemini-2.5-flash,gemini-2.0-flash,gemini-1.5-flash,gemini-1.5-pro"
_raw_models = os.getenv("GEMINI_MODELS", _default_gemini_models).strip()
GEMINI_MODELS = [m.strip() for m in _raw_models.split(",") if m.strip()]
if not GEMINI_MODELS:
    GEMINI_MODELS = [m.strip() for m in _default_gemini_models.split(",") if m.strip()]

# Прокси (необязательно, для запуска в регионах с ограничениями Google Gemini, например РФ)
HTTPS_PROXY = os.getenv("HTTPS_PROXY", "").strip() or None
HTTP_PROXY = os.getenv("HTTP_PROXY", "").strip() or None
if HTTPS_PROXY:
    os.environ["HTTPS_PROXY"] = HTTPS_PROXY
    os.environ["https_proxy"] = HTTPS_PROXY
if HTTP_PROXY:
    os.environ["HTTP_PROXY"] = HTTP_PROXY
    os.environ["http_proxy"] = HTTP_PROXY

# Использование кастомных эмодзи Telegram Premium (True/False)
USE_CUSTOM_EMOJI = os.getenv("USE_CUSTOM_EMOJI", "true").strip().lower() in ("true", "1", "yes")


