"""
Модуль для работы с эмодзи Telegram (поддерживает как кастомные Telegram Premium эмодзи,
так и стандартные Unicode-эмодзи при отключении или для других ботов).
"""

from config import USE_CUSTOM_EMOJI

# Список эмодзи с fallback для стандартного отображения
EMOJI = {
    # Системные и управление
    "settings": {"id": "5870982283724328568", "fallback": "⚙️"},
    "profile": {"id": "5870994129244131212", "fallback": "👤"},
    "users": {"id": "5870772616305839506", "fallback": "👥"},
    "user_check": {"id": "5891207662678317861", "fallback": "👤"},
    "user_cross": {"id": "5893192487324880883", "fallback": "👤"},
    "file": {"id": "5870528606328852614", "fallback": "📁"},
    "smile": {"id": "5870764288364252592", "fallback": "🙂"},
    "growth_chart": {"id": "5870930636742595124", "fallback": "📊"},
    "stats": {"id": "5870921681735781843", "fallback": "📊"},
    "home": {"id": "5873147866364514353", "fallback": "🏘"},
    "lock": {"id": "6037249452824072506", "fallback": "🔒"},
    "unlock": {"id": "6037496202990194718", "fallback": "🔓"},
    "loudspeaker": {"id": "6039422865189638057", "fallback": "📣"},
    "check": {"id": "5870633910337015697", "fallback": "✅"},
    "cross": {"id": "5870657884844462243", "fallback": "❌"},
    "pencil": {"id": "5870676941614354370", "fallback": "🖋"},
    "trash": {"id": "5870875489362513438", "fallback": "🗑"},
    "down": {"id": "5893057118545646106", "fallback": "📰"},
    "clip": {"id": "6039451237743595514", "fallback": "📎"},
    "link": {"id": "5769289093221454192", "fallback": "🔗"},
    "info": {"id": "6028435952299413210", "fallback": "ℹ"},
    "bot": {"id": "6030400221232501136", "fallback": "🤖"},
    "eye": {"id": "6037397706505195857", "fallback": "👁"},
    "eye_hidden": {"id": "6037243349675544634", "fallback": "👁"},
    "send": {"id": "5963103826075456248", "fallback": "⬆"},
    "download": {"id": "6039802767931871481", "fallback": "⬇"},
    "bell": {"id": "6039486778597970865", "fallback": "🔔"},
    "gift": {"id": "6032644646587338669", "fallback": "🎁"},
    "clock": {"id": "5983150113483134607", "fallback": "⏰"},
    "party": {"id": "6041731551845159060", "fallback": "🎉"},
    "font": {"id": "5870801517140775623", "fallback": "🔗"},
    "write": {"id": "5870753782874246579", "fallback": "✍"},
    "photo": {"id": "6035128606563241721", "fallback": "🖼"},
    "location": {"id": "6042011682497106307", "fallback": "📍"},
    "wallet": {"id": "5769126056262898415", "fallback": "👛"},
    "box": {"id": "5884479287171485878", "fallback": "📦"},
    "cryptobot": {"id": "5260752406890711732", "fallback": "👾"},
    "calendar": {"id": "5890937706803894250", "fallback": "📅"},
    "tag": {"id": "5886285355279193209", "fallback": "🏷"},
    "time_past": {"id": "5775896410780079073", "fallback": "🕓"},
    "apps": {"id": "5778672437122045013", "fallback": "📦"},
    "brush": {"id": "6050679691004612757", "fallback": "🖌"},
    "add_text": {"id": "5771851822897566479", "fallback": "🔡"},
    "resize": {"id": "5778479949572738874", "fallback": "↔"},
    "money": {"id": "5904462880941545555", "fallback": "🪙"},
    "send_money": {"id": "5890848474563352982", "fallback": "🪙"},
    "atm": {"id": "5879814368572478751", "fallback": "🏧"},
    "code": {"id": "5940433880585605708", "fallback": "🔨"},
    "loading": {"id": "5345906554510012647", "fallback": "🔄"},
    "back": {"id": "5960671702059848143", "fallback": "◁"},
}


def tag(name: str) -> str:
    """
    Возвращает HTML-тег <tg-emoji> для кастомных эмодзи либо стандартный Unicode-эмодзи,
    если кастомные эмодзи отключены в настройках (USE_CUSTOM_EMOJI=False).
    """
    item = EMOJI.get(name)
    if not item:
        return ""
    if not USE_CUSTOM_EMOJI or not item.get("id"):
        return item.get("fallback", "")
    return f'<tg-emoji emoji-id="{item["id"]}">{item["fallback"]}</tg-emoji>'


def btn_id(name: str) -> str | None:
    """
    Возвращает точный ID для передачи в icon_custom_emoji_id кнопки либо None,
    если кастомные эмодзи отключены в настройках.
    """
    if not USE_CUSTOM_EMOJI:
        return None
    item = EMOJI.get(name)
    return item["id"] if item and item.get("id") else None
