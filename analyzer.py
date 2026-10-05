"""
Модуль AI-анализа состава этикеток через Google Gemini Vision.
Включает строгую валидацию входных изображений, нормализацию JSON-ответа,
умный каскад моделей при сбоях и безопасную генерацию HTML с защитой от переполнения.
"""

import html
import io
import json
import logging
import os
import re
import warnings
from PIL import Image

# Подавляем предупреждение о депрекации устаревшего SDK
warnings.filterwarnings("ignore", category=FutureWarning)

import google.generativeai as genai
from dotenv import load_dotenv

from emoji_helper import tag

logger = logging.getLogger(__name__)

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

# Приоритетный список моделей с поддержкой Vision
CANDIDATE_MODELS = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
]

SYSTEM_PROMPT = """
Ты — профессиональный эксперт по спортивному питанию, пищевой безопасности и нутрициологии для сервиса LabelSpy.
Твоя задача — детально проанализировать фото этикетки (спортивное питание, добавки, витамины или продукты питания).

Верни СТРОГО валидный JSON следующей структуры (без лишнего markdown текста вокруг, только JSON):
{
  "product_name": "Название продукта и бренд (если распознано)",
  "category": "Спортивное питание / Витамины / Продукт питания / Напиток / Кондитерские изделия / Другое",
  "score": "8.5/10",
  "verdict": "Краткий вывод в 1 предложение",
  "positives": [
    "Плюс 1",
    "Плюс 2"
  ],
  "warnings": [
    "Предупреждение 1 (например: Содержит гидрогенизированное пальмовое масло, Е-добавки)",
    "Предупреждение 2"
  ],
  "ingredients_summary": "Краткое понятное резюме основных действующих веществ и их качества",
  "recommendation": "Для кого подходит и стоит ли брать за свою цену"
}

Если на фото вообще не этикетка с составом или текст полностью нечитаем, верни JSON:
{
  "error": "Не удалось распознать состав на фото. Пожалуйста, сфотографируйте блок с составом/ингредиентами чётче и ближе."
}
"""


def validate_and_prepare_image(image_bytes: bytes) -> tuple[Image.Image | None, str | None]:
    """
    Проверяет размер, формат и валидность изображения.
    Освобождает ресурсы и возвращает оптимизированную копию в RGB.
    """
    if not image_bytes or len(image_bytes) < 100:
        return None, "Файл пуст или повреждён. Пожалуйста, отправьте корректное фото."

    if len(image_bytes) > 20 * 1024 * 1024:
        return None, "Размер изображения превышает 20 МБ. Пожалуйста, уменьшите размер фото."

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            format_name = (img.format or "").upper()
            if format_name not in ("JPEG", "JPG", "PNG", "WEBP", "MPO", "BMP"):
                return None, "Формат изображения не поддерживается. Пожалуйста, отправьте фото в формате JPG или PNG."

            w, h = img.size
            if w < 50 or h < 50:
                return None, "Изображение слишком маленькое для распознавания текста (минимум 50x50 пикселей)."

            # Конвертируем в RGB и делаем безопасную копию
            if img.mode not in ("RGB", "L"):
                rgb_img = img.convert("RGB")
            else:
                rgb_img = img.copy()

            # Ограничиваем разрешение (максимум 2048px по длинной стороне)
            # Это снижает время загрузки в сеть в разы без потери читаемости OCR
            if max(rgb_img.size) > 2048:
                rgb_img.thumbnail((2048, 2048), Image.Resampling.LANCZOS)

            return rgb_img, None

    except Exception as e:
        logger.warning(f"Ошибка валидации изображения: {e}")
        return None, "Не удалось открыть изображение. Файл повреждён или не является корректным фото."


def validate_and_normalize_analysis(data: dict) -> dict:
    """
    Валидирует и нормализует JSON-ответ модели по схеме.
    Защищает от null, некорректных типов и выхода числовой оценки за пределы 1-10.
    """
    if not isinstance(data, dict):
        return {"error": "AI вернул некорректный формат данных. Пожалуйста, повторите сканирование."}

    if "error" in data:
        err_val = str(data["error"]).strip()
        return {"error": err_val[:300] if err_val else "Не удалось распознать состав на фото."}

    # 1. Название продукта
    raw_p = data.get("product_name")
    product_name = str(raw_p).strip() if raw_p and isinstance(raw_p, (str, int, float)) else "Неизвестный продукт"
    product_name = product_name[:120]

    # 2. Категория
    raw_c = data.get("category")
    category = str(raw_c).strip() if raw_c and isinstance(raw_c, (str, int, float)) else "Продукт"
    category = category[:60]

    # 3. Оценка от 1 до 10
    raw_s = data.get("score")
    score_val = 5.0
    if raw_s is not None:
        try:
            clean_s = str(raw_s).split("/")[0].replace(",", ".").strip()
            score_val = float(clean_s)
        except (ValueError, TypeError):
            score_val = 5.0

    # Ограничиваем строгим диапазоном 1.0 - 10.0
    score_val = max(1.0, min(10.0, score_val))
    score_str = f"{score_val:.1f}/10"

    # 4. Вердикт
    raw_v = data.get("verdict")
    verdict = str(raw_v).strip() if raw_v and isinstance(raw_v, (str, int, float)) else "Состав проанализирован."
    verdict = verdict[:350]

    # 5. Плюсы
    raw_pos = data.get("positives")
    positives = []
    if isinstance(raw_pos, list):
        for item in raw_pos:
            if item and isinstance(item, (str, int, float)):
                clean_item = str(item).strip()[:150]
                if clean_item:
                    positives.append(clean_item)
    positives = positives[:5]

    # 6. Предупреждения / риски
    raw_w = data.get("warnings")
    warnings_list = []
    if isinstance(raw_w, list):
        for item in raw_w:
            if item and isinstance(item, (str, int, float)):
                clean_item = str(item).strip()[:150]
                if clean_item:
                    warnings_list.append(clean_item)
    warnings_list = warnings_list[:5]

    # 7. Резюме ингредиентов и рекомендация
    summary = str(data.get("ingredients_summary") or "").strip()[:800]
    rec = str(data.get("recommendation") or "").strip()[:400]

    return {
        "product_name": product_name,
        "category": category,
        "score": score_str,
        "score_val": score_val,
        "verdict": verdict,
        "positives": positives,
        "warnings": warnings_list,
        "ingredients_summary": summary,
        "recommendation": rec,
    }


def is_transient_error(err_str: str) -> bool:
    """
    Определяет, является ли ошибка временной (квоты, тайм-ауты, сбои серверов),
    при которой имеет смысл переключиться на резервную модель.
    """
    err_lower = err_str.lower()
    transient_indicators = [
        "429", "quota", "resourceexhausted", "503", "unavailable",
        "500", "internal", "deadline", "timeout", "timed out", "overloaded"
    ]
    return any(ind in err_lower for ind in transient_indicators)


async def analyze_label(image_bytes: bytes) -> dict:
    """
    Анализирует изображение этикетки через Gemini Vision.
    Проверяет изображение, безопасно вызывает API с каскадом моделей
    и возвращает нормализованную структуру данных.
    """
    import asyncio

    # 1. Предварительная валидация изображения
    prepared_image, val_error = validate_and_prepare_image(image_bytes)
    if val_error:
        return {"error": val_error}

    last_error = None

    try:
        # 2. Каскадный опрос моделей
        for model_name in CANDIDATE_MODELS:
            try:
                model = genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=SYSTEM_PROMPT,
                    generation_config={"response_mime_type": "application/json"}
                )

                response = await asyncio.to_thread(
                    model.generate_content,
                    [
                        "Внимательно изучи эту этикетку и разбери полный состав, дозировки, добавки и безопасность:",
                        prepared_image
                    ]
                )

                raw_text = (response.text or "").strip()
                match = re.search(r'\{[\s\S]*\}', raw_text)
                if match:
                    parsed_json = json.loads(match.group(0))
                else:
                    parsed_json = json.loads(raw_text)

                return validate_and_normalize_analysis(parsed_json)

            except Exception as e:
                last_error = e
                err_str = str(e)
                logger.warning(f"Модель {model_name} вернула ошибку: {err_str[:120]}")

                # Если ошибка не временная (например, фатальная ошибка параметров), прерываем
                if not is_transient_error(err_str):
                    logger.error(f"Непоправимая ошибка вызова API: {err_str}")
                    break

                continue

        # Безопасное логирование без раскрытия деталей пользователю
        logger.error(f"Все кандидаты моделей недоступны. Последняя ошибка: {last_error}")
        return {"error": "Сервис временно перегружен. Пожалуйста, повторите попытку через минуту."}

    finally:
        # Явно освобождаем ресурсы изображения
        if prepared_image is not None:
            try:
                prepared_image.close()
            except Exception:
                pass


def format_analysis_html(data: dict) -> str:
    """
    Форматирует результат анализа в безопасный HTML для Telegram.
    Гарантирует соблюдение лимита в 4096 символов и добавляет официальный дисклеймер.
    """
    if "error" in data:
        err_msg = html.escape(str(data.get("error", "Произошла ошибка при анализе.")))
        return (
            f"{tag('cross')} <b>Внимание:</b>\n"
            f"<blockquote>{err_msg}</blockquote>\n\n"
            f"{tag('pencil')} <i>Совет: сфотографируйте блок с составом чётче и ближе при хорошем освещении.</i>"
        )

    product_name = html.escape(str(data.get("product_name", "Неизвестный продукт")))
    category = html.escape(str(data.get("category", "Продукт")))
    score_str = html.escape(str(data.get("score", "5.0/10")))
    verdict = html.escape(str(data.get("verdict", "")))

    lines = [
        f"{tag('bot')} <b>LABELSPY · АНАЛИЗ СОСТАВА</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"{tag('tag')} <b>Продукт:</b> {product_name}",
        f"{tag('file')} <b>Категория:</b> {category}",
        f"{tag('stats')} <b>Оценка безопасности:</b> <code>{score_str}</code>\n",
        f"<blockquote>{tag('info')} <b>ВЕРДИКТ:</b>\n{verdict}</blockquote>\n",
    ]

    warnings = data.get("warnings", [])
    if warnings and isinstance(warnings, list):
        lines.append(f"<b>{tag('cross')} КРАСНЫЕ ФЛАГИ И РИСКИ:</b>")
        for warn in warnings[:4]:
            lines.append(f"• {tag('cross')} {html.escape(str(warn))}")
        lines.append("")
    else:
        lines.append(f"<b>{tag('check')} ЧИСТОТА СОСТАВА:</b>")
        lines.append(f"• {tag('check')} Опасных добавок и скрытых примесей не обнаружено.\n")

    positives = data.get("positives", [])
    if positives and isinstance(positives, list):
        lines.append(f"<b>{tag('check')} ПЛЮСЫ СОСТАВА:</b>")
        for pos in positives[:3]:
            lines.append(f"• {tag('check')} {html.escape(str(pos))}")
        lines.append("")

    summary = data.get("ingredients_summary", "")
    rec = data.get("recommendation", "")
    if summary or rec:
        lines.append("<blockquote expandable>")
        if summary:
            lines.append(f"{tag('file')} <b>Разбор активных веществ:</b>\n{html.escape(str(summary))}\n")
        if rec:
            lines.append(f"{tag('pencil')} <b>Рекомендация:</b>\n{html.escape(str(rec))}")
        lines.append("</blockquote>\n")

    # Обязательный дисклеймер
    lines.append(
        "ℹ️ <i>Дисклеймер: Результат сформирован AI для ознакомления и не является медицинской рекомендацией.</i>"
    )

    full_text = "\n".join(lines)

    # Защита от лимита длины сообщений Telegram (4096 символов)
    if len(full_text) > 3900:
        # Укорачиваем длинные описания при необходимости
        full_text = full_text[:3850] + "...\n</i>"

    return full_text
