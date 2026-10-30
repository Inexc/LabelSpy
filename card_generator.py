"""
Генератор стильных графических карточек-отчётов для LabelSpy.
Создаёт премиальную карточку разбора (PNG) в тёмной теме
с визуальным рейтингом, шкалой безопасности и логотипом.
Поддерживает шрифты TTF с кириллицей и динамическую настройку брендинга.
"""

import io
import logging
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

try:
    from config import BOT_NAME, BOT_USERNAME
except Exception:
    BOT_NAME = "LabelSpy"
    BOT_USERNAME = ""

logger = logging.getLogger(__name__)

# Кэш загруженных шрифтов
_FONT_CACHE: dict[tuple[int, bool], ImageFont.ImageFont] = {}


def get_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    """
    Возвращает кэшированный шрифт TTF с поддержкой кириллицы из папки fonts/.
    Если файл не найден, логирует предупреждение и возвращает стандартный шрифт Pillow.
    """
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    fonts_dir = Path(__file__).resolve().parent / "fonts"
    if bold:
        candidates = ["Roboto-Bold.ttf", "DejaVuSans-Bold.ttf", "Inter-Bold.ttf"]
    else:
        candidates = ["Roboto-Regular.ttf", "DejaVuSans.ttf", "Inter-Regular.ttf"]

    font_path = None
    for cand in candidates:
        cand_path = fonts_dir / cand
        if cand_path.is_file():
            font_path = cand_path
            break

    if not font_path and fonts_dir.is_dir():
        for f in fonts_dir.glob("*.ttf"):
            font_path = f
            break

    if font_path:
        try:
            font = ImageFont.truetype(str(font_path), size)
            _FONT_CACHE[key] = font
            return font
        except Exception as e:
            logger.warning(f"Не удалось загрузить шрифт {font_path}: {e}")

    logger.warning(f"Шрифт TTF не найден в {fonts_dir}, используется стандартный шрифт Pillow.")
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    _FONT_CACHE[key] = font
    return font


def truncate_by_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: float, ellipsis: str = "...") -> str:
    """Обрезает строку по фактической ширине в пикселях с помощью draw.textlength."""
    if not text:
        return ""
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis_width = draw.textlength(ellipsis, font=font)
    if ellipsis_width >= max_width:
        return ""
    low, high = 0, len(text)
    best = ""
    while low <= high:
        mid = (low + high) // 2
        cand = text[:mid]
        if draw.textlength(cand + ellipsis, font=font) <= max_width:
            best = cand + ellipsis
            low = mid + 1
        else:
            high = mid - 1
    return best


def split_lines_by_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: float, max_lines: int = 2) -> list[str]:
    """Разбивает текст на строки по словам без превышения max_width."""
    words = text.split()
    if not words:
        return []
    lines = []
    current_words = []
    idx = 0
    while idx < len(words):
        w = words[idx]
        test = " ".join(current_words + [w])
        if draw.textlength(test, font=font) <= max_width:
            current_words.append(w)
            idx += 1
        else:
            if current_words:
                lines.append(" ".join(current_words))
                current_words = []
                if len(lines) == max_lines - 1:
                    rem_text = " ".join(words[idx:])
                    lines.append(truncate_by_width(draw, rem_text, font, max_width))
                    return lines
            else:
                lines.append(truncate_by_width(draw, w, font, max_width))
                idx += 1
                if len(lines) == max_lines - 1:
                    rem_text = " ".join(words[idx:])
                    if rem_text:
                        lines.append(truncate_by_width(draw, rem_text, font, max_width))
                    return lines

    if current_words and len(lines) < max_lines:
        lines.append(" ".join(current_words))
    return lines


def get_color_scheme(score_val: float):
    """Определяет цветовую схему в зависимости от оценки."""
    if score_val >= 7.5:
        return {
            "accent": (16, 185, 129),      # #10B981
            "accent_bg": (6, 78, 59),      # #064E3B
            "badge_text": "ЧИСТЫЙ СОСТАВ",
            "border": (16, 185, 129, 120),
        }
    elif score_val >= 4.5:
        return {
            "accent": (245, 158, 11),     # #F59E0B
            "accent_bg": (120, 53, 15),    # #78350F
            "badge_text": "СОМНИТЕЛЬНЫЙ СОСТАВ",
            "border": (245, 158, 11, 120),
        }
    else:
        return {
            "accent": (239, 68, 68),      # #EF4444
            "accent_bg": (127, 29, 29),    # #7F1D1D
            "badge_text": "ОПАСНЫЕ ДОБАВКИ",
            "border": (239, 68, 68, 120),
        }


def create_report_card(product_name: str, score_str: str, verdict: str, warnings: list, positives: list) -> bytes:
    """
    Создаёт красивую инфографику 900x520 для отправки в Telegram.
    Поддерживает кириллицу и отображение графических маркеров вместо эмодзи.
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
    brand_title = (BOT_NAME or "LabelSpy").upper()
    font_brand = get_font(22, bold=True)
    draw.text((40, 30), brand_title, fill=(0, 242, 254), font=font_brand)
    brand_w = draw.textlength(brand_title, font=font_brand)

    # Разделитель и подзаголовок
    sub_x = 40 + brand_w + 16
    draw.ellipse([sub_x, 43, sub_x + 5, 48], fill=(148, 163, 184))
    draw.text((sub_x + 15, 33), "AI FOOD & SUPPLEMENT SCANNER", fill=(148, 163, 184), font=get_font(14))

    # Бейдж статуса справа в шапке
    badge_font = get_font(13, bold=True)
    badge_text = theme["badge_text"]
    badge_tw = draw.textlength(badge_text, font=badge_font)
    badge_w = max(190, int(badge_tw + 32))
    badge_x1 = width - 40 - badge_w
    badge_x2 = width - 40
    draw.rounded_rectangle([badge_x1, 24, badge_x2, 66], radius=14, fill=theme["accent_bg"], outline=theme["accent"], width=2)
    draw.text((badge_x1 + (badge_w - badge_tw) / 2, 35), badge_text, fill=(255, 255, 255), font=badge_font)

    # Название продукта с защитой от переполнения
    font_title = get_font(26, bold=True)
    title_clean = truncate_by_width(draw, product_name or "Неизвестный продукт", font_title, 820)
    draw.text((40, 100), title_clean, fill=(255, 255, 255), font=font_title)

    # Левая колонка: Большой круглый рейтинг / Score Card
    draw.rounded_rectangle([40, 160, 260, 390], radius=22, fill=(18, 28, 48), outline=(30, 45, 75), width=2)
    font_rating_header = get_font(15, bold=True)
    rt_w = draw.textlength("РЕЙТИНГ", font=font_rating_header)
    draw.text((150 - rt_w / 2, 175), "РЕЙТИНГ", fill=(148, 163, 184), font=font_rating_header)

    # Большая цифра оценки
    font_score = get_font(60, bold=True)
    font_slash = get_font(22)
    score_txt = f"{score_val:.1f}"
    sc_w = draw.textlength(score_txt, font=font_score)
    sl_w = draw.textlength("/10", font=font_slash)
    total_sc_w = sc_w + 6 + sl_w
    sc_start_x = 150 - total_sc_w / 2

    draw.text((sc_start_x, 220), score_txt, fill=theme["accent"], font=font_score)
    draw.text((sc_start_x + sc_w + 6, 252), "/10", fill=(148, 163, 184), font=font_slash)

    # Прогресс-бар оценки
    bar_x, bar_y, bar_w, bar_h = 60, 318, 180, 14
    draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=7, fill=(30, 41, 59))
    fill_w = int(bar_w * (max(0.5, min(10.0, score_val)) / 10.0))
    if fill_w > 0:
        draw.rounded_rectangle([bar_x, bar_y, bar_x + fill_w, bar_y + bar_h], radius=7, fill=theme["accent"])

    verdict_badge = "ОПАСНО" if score_val < 4.5 else ("ВНИМАНИЕ" if score_val < 7.5 else "ОДОБРЕНО")
    font_vbadge = get_font(15, bold=True)
    vb_w = draw.textlength(verdict_badge, font=font_vbadge)
    draw.text((150 - vb_w / 2, 348), verdict_badge, fill=theme["accent"], font=font_vbadge)

    # Правая колонка: Вердикт и ключевые факторы
    # Плашка вердикта
    draw.rounded_rectangle([285, 160, width - 40, 245], radius=18, fill=(18, 28, 48), outline=(30, 45, 75), width=1)
    draw.text((305, 172), "ВЕРДИКТ ЭКСПЕРТА:", fill=(0, 242, 254), font=get_font(14, bold=True))

    font_vtext = get_font(14)
    v_lines = split_lines_by_width(draw, verdict or "Состав проанализирован.", font_vtext, 535, max_lines=2)
    if len(v_lines) == 1:
        draw.text((305, 200), v_lines[0], fill=(241, 245, 249), font=font_vtext)
    elif len(v_lines) >= 2:
        draw.text((305, 194), v_lines[0], fill=(241, 245, 249), font=font_vtext)
        draw.text((305, 216), v_lines[1], fill=(241, 245, 249), font=font_vtext)

    # Красные флаги или плюсы состава
    draw.rounded_rectangle([285, 260, width - 40, 390], radius=18, fill=(18, 28, 48), outline=(30, 45, 75), width=1)

    font_item = get_font(13)
    if warnings:
        # Нарисованный графический маркер предупреждения (красный значок с "!")
        draw.rounded_rectangle([305, 273, 323, 291], radius=4, fill=(239, 68, 68))
        draw.text((311, 274), "!", fill=(255, 255, 255), font=get_font(12, bold=True))
        draw.text((330, 273), "КРАСНЫЕ ФЛАГИ И ДОБАВКИ:", fill=(239, 68, 68), font=get_font(14, bold=True))

        y_off = 303
        for w in warnings[:3]:
            w_text = truncate_by_width(draw, w, font_item, 515)
            draw.ellipse([308, y_off + 4, 314, y_off + 10], fill=(239, 68, 68))
            draw.text((324, y_off), w_text, fill=(226, 232, 240), font=font_item)
            y_off += 26
    elif positives:
        # Нарисованный графический маркер плюсов (зеленый значок с "+")
        draw.rounded_rectangle([305, 273, 323, 291], radius=4, fill=(16, 185, 129))
        draw.text((310, 273), "+", fill=(255, 255, 255), font=get_font(13, bold=True))
        draw.text((330, 273), "ПЛЮСЫ СОСТАВА:", fill=(16, 185, 129), font=get_font(14, bold=True))

        y_off = 303
        for p in positives[:3]:
            p_text = truncate_by_width(draw, p, font_item, 515)
            draw.ellipse([308, y_off + 4, 314, y_off + 10], fill=(16, 185, 129))
            draw.text((324, y_off), p_text, fill=(226, 232, 240), font=font_item)
            y_off += 26
    else:
        # Нейтральный состав
        draw.rounded_rectangle([305, 273, 323, 291], radius=4, fill=(59, 130, 246))
        draw.text((312, 274), "i", fill=(255, 255, 255), font=get_font(12, bold=True))
        draw.text((330, 273), "ОСОБЕННОСТИ СОСТАВА:", fill=(59, 130, 246), font=get_font(14, bold=True))
        draw.text((305, 305), "Особых рисков или действующих добавок не выделено.", fill=(226, 232, 240), font=font_item)

    # Нижняя подпись
    draw.text((40, 460), "Анализ выполнен с помощью Gemini Vision AI", fill=(100, 116, 139), font=get_font(13))

    # Отображаем @username бота только если он настроен
    clean_username = BOT_USERNAME.strip().lstrip("@") if BOT_USERNAME else ""
    if clean_username:
        uname_text = f"@{clean_username}"
        font_uname = get_font(15, bold=True)
        u_width = draw.textlength(uname_text, font=font_uname)
        draw.text((width - 40 - u_width, 460), uname_text, fill=(0, 242, 254), font=font_uname)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
