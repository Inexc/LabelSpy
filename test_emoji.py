import os
import json
import httpx
from dotenv import load_dotenv

def run_live_emoji_test():
    """Отправляет тестовое сообщение в Telegram только при явном флаге RUN_LIVE_TEST=1."""
    if os.getenv("RUN_LIVE_TEST") != "1":
        print("Live test skipped: RUN_LIVE_TEST is not set to '1'. This protects against accidental API calls.")
        return False

    load_dotenv()
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        print("TELEGRAM_TOKEN is missing.")
        return False

    admin_env = os.getenv("ADMIN_ID")
    if not admin_env or not admin_env.strip().isdigit():
        print("Live test skipped: ADMIN_ID is not configured in .env.")
        return False

    chat_id = int(admin_env.strip())
    payload = {
        "chat_id": chat_id,
        "text": 'Тест кастом эмодзи: <tg-emoji emoji-id="5870982283724328568">⚙️</tg-emoji>',
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [
                [
                    {
                        "text": "Настройки",
                        "callback_data": "test",
                        "icon_custom_emoji_id": "5870982283724328568"
                    }
                ]
            ]
        }
    }

    try:
        res = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=10.0)
        with open("test_output.json", "w", encoding="utf-8") as f:
            json.dump(res.json(), f, indent=2, ensure_ascii=False)
        print("Saved to test_output.json successfully")
        return True
    except Exception as e:
        print(f"Error executing live test: {e}")
        return False


if __name__ == "__main__":
    run_live_emoji_test()

