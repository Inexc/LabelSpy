"""
Генератор стильных графических карточек-отчётов для LabelSpy.
Создаёт премиальную карточку разбора (PNG) в тёмной теме
с визуальным рейтингом, шкалой безопасности и логотипом.
"""

import io
from PIL import Image, ImageDraw, ImageFont


def get_color_scheme(score_val: float):
    """Определяет цветовую схему в зависимости от оценки."""
    if score_val >= 7.5:
        # Зеленый / чистый
        return {
            "accent": (16, 185, 129),      # #10B981
            "accent_bg": (6, 78, 59),      # #064E3B
            "badge_text": "ЧИСТЫЙ СОСТАВ",
            "border": (16, 185, 129, 120),
        }
    elif score_val >= 4.5:
        # Желтый / сомнительный
        return {
            "accent": (245, 158, 11),     # #F59E0B
            "accent_bg": (120, 53, 15),    # #78350F
            "badge_text": "СОМНИТЕЛЬНЫЙ СОСТАВ",
            "border": (245, 158, 11, 120),
        }
    else:
        # Красный / опасный
        return {
            "accent": (239, 68, 68),      # #EF4444
            "accent_bg": (127, 29, 29),    # #7F1D1D
            "badge_text": "ОПАСНЫЕ ДОБАВКИ",
            "border": (239, 68, 68, 120),
        }


def create_report_card(product_name: str, score_str: str, verdict: str, warnings: list, positives: list) -> bytes:
    """
    Создаёт красивую инфографику 900x520 для отправки в Telegram.
    """
    width, height = 900, 520
    img = Image.new("RGBA", (width, height), color=(11, 15, 25, 255))
    draw = ImageDraw.Draw(img)

    # Парсим числовую оценку
    score_val = 5.0
    try:
        clean_score = score_str.split("/")[0].replace(",", ".").strip()
        score_val = float(clean_score)
    except Exception:
        pass

    theme = get_color_scheme(score_val)

    # Внешняя стильная рамка со скруглением
    draw.rounded_rectangle([10, 10, width - 11, height - 11], radius=28, fill=(13, 20, 34), outline=theme["accent"], width=3)

    # Верхняя плашка шапки (Header)
    draw.rounded_rectangle([14, 14, width - 15, 75], radius=24, fill=(18, 28, 48))
    # Логотип и название бота
    draw.text((40, 28), "LABELSPY", fill=(0, 242, 254), font_size=24)
    draw.text((180, 32), "•   AI FOOD & SUPPLEMENT SCANNER", fill=(148, 163, 184), font_size=16)

    # Бейдж статуса справа в шапке
    draw.rounded_rectangle([width - 290, 24, width - 40, 66], radius=14, fill=theme["accent_bg"], outline=theme["accent"], width=2)
    draw.text((width - 270, 33), theme["badge_text"], fill=(255, 255, 255), font_size=15)

    # Название продукта
    title_short = product_name[:48] + "..." if len(product_name) > 48 else product_name
    draw.text((40, 100), title_short, fill=(255, 255, 255), font_size=28)

    # Левая колонка: Большой круглый рейтинг / Score Card
    draw.rounded_rectangle([40, 160, 260, 390], radius=22, fill=(18, 28, 48), outline=(30, 45, 75), width=2)
    draw.text((95, 175), "РЕЙТИНГ", fill=(148, 163, 184), font_size=16)
    
    # Большая цифра оценки
    draw.text((65, 215), f"{score_val:.1f}", fill=theme["accent"], font_size=68)
    draw.text((185, 255), "/10", fill=(148, 163, 184), font_size=24)

    # Прогресс-бар оценки
    bar_x, bar_y, bar_w, bar_h = 60, 320, 180, 16
    draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=8, fill=(30, 41, 59))
    fill_w = int(bar_w * (max(0.5, min(10.0, score_val)) / 10.0))
    if fill_w > 0:
        draw.rounded_rectangle([bar_x, bar_y, bar_x + fill_w, bar_y + bar_h], radius=8, fill=theme["accent"])

    verdict_text = "ОПАСНО" if score_val < 4.5 else ("ВНИМАНИЕ" if score_val < 7.5 else "ОДОБРЕНО")
    draw.text((95, 350), verdict_text, fill=theme["accent"], font_size=16)

    # Правая колонка: Вердикт и ключевые факторы
    # Плашка вердикта
    draw.rounded_rectangle([285, 160, width - 40, 245], radius=18, fill=(18, 28, 48), outline=(30, 45, 75), width=1)
    draw.text((305, 172), "ВЕРДИКТ ЭКСПЕРТА:", fill=(0, 242, 254), font_size=15)
    
    # Текст вердикта (обрезка под размер блока)
    v_clean = verdict[:140] + "..." if len(verdict) > 140 else verdict
    # Разбиваем на 2 строки если длинный
    if len(v_clean) > 60:
        cut = v_clean.rfind(" ", 0, 60)
        v1 = v_clean[:cut]
        v2 = v_clean[cut:].strip()
        draw.text((305, 195), v1, fill=(241, 245, 249), font_size=15)
        draw.text((305, 218), v2, fill=(241, 245, 249), font_size=15)
    else:
        draw.text((305, 202), v_clean, fill=(241, 245, 249), font_size=16)

    # Красные флаги или плюсы
    draw.rounded_rectangle([285, 260, width - 40, 390], radius=18, fill=(18, 28, 48), outline=(30, 45, 75), width=1)
    
    if warnings:
        draw.text((305, 275), "⚠️ КРАСНЫЕ ФЛАГИ И ДОБАВКИ:", fill=(239, 68, 68), font_size=15)
        y_off = 305
        for w in warnings[:3]:
            w_text = "• " + (w[:70] + "..." if len(w) > 70 else w)
            draw.text((305, y_off), w_text, fill=(226, 232, 240), font_size=14)
            y_off += 24
    elif positives:
        draw.text((305, 275), "✅ ПЛЮСЫ СОСТАВА:", fill=(16, 185, 129), font_size=15)
        y_off = 305
        for p in positives[:3]:
            p_text = "• " + (p[:70] + "..." if len(p) > 70 else p)
            draw.text((305, y_off), p_text, fill=(226, 232, 240), font_size=14)
            y_off += 24

    # Нижняя подпись
    draw.text((40, 460), "Анализ выполнен с помощью Gemini Vision AI", fill=(100, 116, 139), font_size=14)
    draw.text((width - 240, 460), "@labelspy_bot", fill=(0, 242, 254), font_size=16)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
