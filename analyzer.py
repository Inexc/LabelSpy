"""
Модуль AI-анализа состава этикеток через Google Gemini Vision
Интегрирован с Telegram Premium эмодзи по гайду emoji.wivvi.net
"""

import html
import io
import json
import os
from PIL import Image
import google.generativeai as genai
from dotenv import load_dotenv

from emoji_helper import tag

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Приоритетный список моделей с поддержкой Vision
CANDIDATE_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-flash-latest",
]

SYSTEM_PROMPT = """
Ты — профессиональный эксперт по спортивному питанию, пищевой безопасности и нутрициологии для сервиса LabelSpy.
Твоя задача — детально проанализировать фото этикетки (спортивное питание, добавки, витамины или продукты питания).

Верни СТРОГО валидный JSON следующей структуры (без лишнего markdown текста вокруг, только JSON):
{
  "product_name": "Название продукта и бренд (если распознано)",
  "category": "Спортивное питание / Витамины / Продукт питания / Напиток / Кондитерские изделия / Другое",
  "score": "8.5/10",
  "verdict": "Краткий вывод в 1 предложение (например: 'Качественный изолят с чистым составом' или 'Много гидрогенизированных жиров и скрытого сахара')",
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

Если на фото вообще не этикетка или текст не читается, верни JSON:
{
  "error": "Не удалось распознать состав на фото. Пожалуйста, сфотографируйте блок с составом/ингредиентами чётче и ближе."
}
"""


async def analyze_label(image_bytes: bytes) -> dict:
    """
    Анализирует изображение этикетки через Gemini Vision.
    Использует автоматический повтор и резервные модели при лимитах.
    """
    import asyncio

    image = Image.open(io.BytesIO(image_bytes))
    last_error = None

    for model_name in CANDIDATE_MODELS:
        for attempt in range(2):
            try:
                model = genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=SYSTEM_PROMPT,
                    generation_config={"response_mime_type": "application/json"}
                )
                
                # Запускаем в отдельном потоке, так как generate_content синхронный
                response = await asyncio.to_thread(
                    model.generate_content,
                    [
                        "Внимательно изучи эту этикетку и разбери полный состав, дозировки, добавки и безопасность:",
                        image
                    ]
                )
                
                raw_text = response.text.strip()
                # Очищаем от возможных обёрток ```json ... ```
                if raw_text.startswith("```json"):
                    raw_text = raw_text[7:]
                if raw_text.startswith("```"):
                    raw_text = raw_text[3:]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3]
                raw_text = raw_text.strip()

                data = json.loads(raw_text)
                return data
            except Exception as e:
                last_error = e
                err_str = str(e)
                if "429" in err_str or "Quota exceeded" in err_str:
                    # Кратковременный лимит запросов в минуту — ждём и повторяем
                    await asyncio.sleep(4)
                    continue
                else:
                    break

    return {"error": f"Сервис перегружен, пожалуйста, повторите попытку через 10 секунд ({str(last_error)})"}



def format_analysis_html(data: dict) -> str:
    """
    Форматирует результат анализа с использованием точного премиум-пака эмодзи
    """
    if "error" in data:
        return (
            f"{tag('cross')} <b>Внимание:</b>\n"
            f"<blockquote>{html.escape(data['error'])}</blockquote>\n\n"
            f"{tag('pencil')} <i>Совет: сфотографируйте блок с составом чётче и ближе при хорошем освещении.</i>"
        )

    product_name = html.escape(data.get("product_name", "Неизвестный продукт"))
    category = html.escape(data.get("category", "Продукт"))
    score_str = html.escape(str(data.get("score", "5.0/10")))
    verdict = html.escape(data.get("verdict", ""))

    lines = [
        f"{tag('bot')} <b>LABELSPY · АНАЛИЗ СОСТАВА</b>",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"{tag('tag')} <b>Продукт:</b> {product_name}",
        f"{tag('file')} <b>Категория:</b> {category}",
        f"{tag('stats')} <b>Оценка безопасности:</b> <code>{score_str}</code>\n",
        f"<blockquote>{tag('info')} <b>ВЕРДИКТ:</b>\n{verdict}</blockquote>\n",
    ]

    warnings = data.get("warnings", [])
    if warnings:
        lines.append(f"<b>{tag('cross')} КРАСНЫЕ ФЛАГИ И РИСКИ:</b>")
        for warn in warnings[:4]:
            lines.append(f"• {tag('cross')} {html.escape(str(warn))}")
        lines.append("")
    else:
        lines.append(f"<b>{tag('check')} ЧИСТОТА СОСТАВА:</b>")
        lines.append(f"• {tag('check')} Опасных добавок и скрытых примесей не обнаружено.\n")

    positives = data.get("positives", [])
    if positives:
        lines.append(f"<b>{tag('check')} ПЛЮСЫ СОСТАВА:</b>")
        for pos in positives[:3]:
            lines.append(f"• {tag('check')} {html.escape(str(pos))}")
        lines.append("")

    summary = data.get("ingredients_summary", "")
    rec = data.get("recommendation", "")
    if summary or rec:
        lines.append("<blockquote expandable>")
        if summary:
            lines.append(f"{tag('file')} <b>Разбор активных веществ:</b>\n{html.escape(summary)}\n")
        if rec:
            lines.append(f"{tag('pencil')} <b>Рекомендация:</b>\n{html.escape(rec)}")
        lines.append("</blockquote>")

    return "\n".join(lines)


