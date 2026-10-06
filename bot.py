"""
Telegram бот LabelSpy — AI-сканер состава продуктов и спортивного питания
Кнопки с яркими визуальными эмодзи, работающими на всех устройствах.
Включает строгую проверку платежей, ограничение срока подписки, защиту от параллельного спама
и поддержку фото как в виде сжатых изображений, так и файлов/документов.
"""

import html
import logging
import os
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    LabeledPrice,
)
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    ContextTypes,
    filters,
)

from config import (
    TELEGRAM_TOKEN,
    FREE_SCANS_PER_MONTH,
    BOT_NAME,
    ADMIN_ID,
    PREMIUM_STARS_PRICE,
    PREMIUM_SUBSCRIPTION_DAYS,
    DEMO_PREMIUM_DAYS,
    SCAN_COOLDOWN_SECONDS,
)
from database import (
    init_db,
    add_user,
    get_monthly_scan_count,
    add_scan,
    is_premium,
    set_premium,
    grant_premium,
    get_premium_until,
    record_successful_payment,
    get_user_info,
    get_total_users,
    get_total_scans,
    get_scan,
)
from emoji_helper import tag, btn_id
from analyzer import analyze_label, format_analysis_html
from card_generator import create_report_card
import json


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Защита от параллельного спама и обхода лимитов
active_user_scans: set[int] = set()
last_user_scan_time: dict[int, float] = {}


class HealthHandler(BaseHTTPRequestHandler):
    """Эндпоинт для облачных хостингов (Render, Koyeb и др.)."""
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK - LabelSpy Bot is running!")

    def log_message(self, format, *args):
        pass


def start_health_server():
    """Запускает фоновый веб-сервер для проверки доступности."""
    port = int(os.environ.get("PORT", 10000))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        server.serve_forever()
    except Exception as e:
        logger.warning(f"Health server error: {e}")


if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Постоянное нижнее меню под полем ввода с кастомными иконками."""
    rows = [
        [
            KeyboardButton(
                text="Сделать скан",
                icon_custom_emoji_id=btn_id("photo"),
            ),
            KeyboardButton(
                text="Мой профиль",
                icon_custom_emoji_id=btn_id("profile"),
            ),
        ],
        [
            KeyboardButton(
                text="Премиум",
                icon_custom_emoji_id=btn_id("money"),
            ),
            KeyboardButton(
                text="О сервисе",
                icon_custom_emoji_id=btn_id("info"),
            ),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню с кастомными иконками в кнопках."""
    rows = [
        [
            InlineKeyboardButton(
                text="Сделать скан",
                callback_data="guide",
                icon_custom_emoji_id=btn_id("photo"),
            ),
            InlineKeyboardButton(
                text="Мой профиль",
                callback_data="profile",
                icon_custom_emoji_id=btn_id("profile"),
            ),
        ],
        [
            InlineKeyboardButton(
                text="Премиум",
                callback_data="premium",
                icon_custom_emoji_id=btn_id("money"),
            ),
            InlineKeyboardButton(
                text="О сервисе",
                callback_data="about",
                icon_custom_emoji_id=btn_id("info"),
            ),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def analysis_keyboard(scan_id: int | None = None) -> InlineKeyboardMarkup:
    """Кнопки под результатом анализа состава."""
    rows = []
    if scan_id:
        rows.append([
            InlineKeyboardButton(
                text="🖼 Карточка-отчёт (PNG)",
                callback_data=f"card_{scan_id}",
                icon_custom_emoji_id=btn_id("photo"),
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text="Сканировать ещё",
            callback_data="guide",
            icon_custom_emoji_id=btn_id("loading"),
        ),
        InlineKeyboardButton(
            text="Мой профиль",
            callback_data="profile",
            icon_custom_emoji_id=btn_id("profile"),
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            text="Оформить Премиум",
            callback_data="premium",
            icon_custom_emoji_id=btn_id("money"),
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)



def back_keyboard() -> InlineKeyboardMarkup:
    """Кнопка возврата в главное меню."""
    rows = [
        [
            InlineKeyboardButton(
                text="Назад",
                callback_data="back_to_main",
                icon_custom_emoji_id=btn_id("back"),
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def premium_keyboard(user_id: int | None = None) -> InlineKeyboardMarkup:
    """Кнопки раздела Премиум (демо-доступ доступен только администратору)."""
    rows = [
        [
            InlineKeyboardButton(
                text=f"Оплатить {PREMIUM_STARS_PRICE} Stars (~$0.99)",
                callback_data="buy_premium_stars",
                icon_custom_emoji_id=btn_id("money"),
            )
        ],
    ]
    if user_id == ADMIN_ID:
        rows.append([
            InlineKeyboardButton(
                text=f"Тестовый доступ ({DEMO_PREMIUM_DAYS} дн.)",
                callback_data="activate_test_premium",
                icon_custom_emoji_id=btn_id("gift"),
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_main",
            icon_custom_emoji_id=btn_id("back"),
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_start_text(user) -> str:
    """Формирует приветственный текст с оформлением."""
    scans_used = get_monthly_scan_count(user.id)
    user_has_prem = is_premium(user.id)
    remaining_scans = max(0, FREE_SCANS_PER_MONTH - scans_used)
    limit_text = "Безлимитно" if user_has_prem else f"{remaining_scans} из {FREE_SCANS_PER_MONTH}"

    return (
        f"{tag('bot')} <b>LABELSPY · AI СКАНИРОВАНИЕ СОСТАВА</b>\n\n"
        f"<blockquote>🤖 Персональный независимый AI-анализатор чистоты продуктов и добавок прямо в Telegram.</blockquote>\n\n"
        f"• {tag('file')} <b>Спортпит и витамины:</b> проверка реальных дозировок и качества сырья\n"
        f"• {tag('cross')} <b>Контроль рисков:</b> выявление скрытого сахара, трансжиров и вредных добавок\n"
        f"• {tag('stats')} <b>Экспертный вердикт:</b> честная оценка от 1 до 10\n\n"
        f"{tag('money')} <b>Ваш лимит сканов:</b> <code>{limit_text}</code>\n\n"
        f"<i>{tag('photo')} Отправьте фото этикетки с составом прямо в чат!</i>"
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start."""
    user = update.effective_user
    add_user(user.id, user.username or "", user.first_name or "")
    text = get_start_text(user)

    await update.message.reply_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_reply_keyboard(),
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка фото этикетки (как сжатого фото, так и файла/документа).
    Защищена от параллельного обхода лимитов и флуда.
    """
    user = update.effective_user
    add_user(user.id, user.username or "", user.first_name or "")

    now_ts = time.time()
    last_ts = last_user_scan_time.get(user.id, 0.0)

    # 1. Защита от частого спама (cooldown)
    if now_ts - last_ts < SCAN_COOLDOWN_SECONDS:
        await update.message.reply_text(
            "⏳ <b>Слишком частые запросы.</b> Пожалуйста, подождите пару секунд перед следующим сканированием.",
            parse_mode=ParseMode.HTML,
        )
        return

    # 2. Защита от параллельных запросов для обхода лимита
    if user.id in active_user_scans:
        await update.message.reply_text(
            "⏳ <b>Ваш предыдущий скан ещё обрабатывается.</b> Пожалуйста, дождитесь завершения перед отправкой следующего фото.",
            parse_mode=ParseMode.HTML,
        )
        return

    # 3. Проверка месячного лимита
    user_has_prem = is_premium(user.id)
    scans_used = get_monthly_scan_count(user.id)

    if not user_has_prem and scans_used >= FREE_SCANS_PER_MONTH:
        limit_msg = (
            f"❌ <b>Лимит бесплатных сканов исчерпан!</b>\n\n"
            f"Вы использовали все {FREE_SCANS_PER_MONTH} бесплатных сканов в текущем месяце.\n\n"
            f"💎 Оформите <b>LabelSpy Premium</b> для безлимитного анализа без ограничений!"
        )
        await update.message.reply_text(
            text=limit_msg,
            parse_mode=ParseMode.HTML,
            reply_markup=premium_keyboard(user.id),
        )
        return

    active_user_scans.add(user.id)
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        status_msg = await update.message.reply_text(
            "🔄 <b>Изучаю этикетку...</b>\n<i>AI читает состав и сверяет компоненты. Это займет несколько секунд.</i>",
            parse_mode=ParseMode.HTML,
        )

        # Поддерживаем и обычные фото, и документы-изображения (отправка «без сжатия»)
        if update.message.photo:
            photo_file = await update.message.photo[-1].get_file()
        elif update.message.document:
            doc = update.message.document
            mime = (doc.mime_type or "").lower()
            if not mime.startswith("image/"):
                await status_msg.edit_text(
                    "❌ <b>Пожалуйста, отправьте изображение этикетки</b> (JPG, PNG или WEBP).",
                    parse_mode=ParseMode.HTML,
                )
                return
            photo_file = await doc.get_file()
        else:
            await status_msg.edit_text(
                "❌ <b>Не удалось найти изображение в сообщении.</b>",
                parse_mode=ParseMode.HTML,
            )
            return

        photo_bytes = await photo_file.download_as_bytearray()
        analysis = await analyze_label(bytes(photo_bytes))

        # Списываем попытку и сохраняем данные только при успешном распознавании этикетки
        scan_id = None
        if "error" not in analysis:
            product_name = analysis.get("product_name") or "Нераспознано"
            score = analysis.get("score")
            analysis_json_str = json.dumps(analysis, ensure_ascii=False)
            scan_id = add_scan(
                user.id,
                product_name,
                str(score) if score is not None else None,
                status="success",
                analysis_json=analysis_json_str,
            )

        reply_html = format_analysis_html(analysis)
        await status_msg.edit_text(
            text=reply_html,
            parse_mode=ParseMode.HTML,
            reply_markup=analysis_keyboard(scan_id=scan_id),
        )


    except Exception as e:
        logger.error(f"Ошибка при обработке фото: {e}")
        try:
            await status_msg.edit_text(
                "❌ <b>Произошла ошибка при анализе фото.</b>\nПожалуйста, отправьте фото еще раз чётче.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    finally:
        active_user_scans.discard(user.id)
        last_user_scan_time[user.id] = time.time()


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий инлайн-кнопок."""
    query = update.callback_query
    user = query.from_user
    add_user(user.id, user.username or "", user.first_name or "")
    data = query.data

    # Защита от повторного query.answer(): обработка алерта для не-админа
    if data == "activate_test_premium" and user.id != ADMIN_ID:
        await query.answer("Эта опция доступна только администратору.", show_alert=True)
        return

    await query.answer()

    if data == "back_to_main":
        text = get_start_text(user)
        await query.message.edit_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard(),
        )

    elif data == "guide":
        text = (
            "📁 <b>Как сделать идеальный скан:</b>\n\n"
            "1. Сфотографируйте блок <b>'Состав'</b> или <b>'Supplement Facts'</b>.\n"
            "2. Держите камеру ровно при хорошем свете.\n"
            "3. Убедитесь, что текст четкий и читаемый.\n"
            "4. Отправьте фото прямо в этот чат!\n\n"
            "🖋 <i>Бот одинаково хорошо читает составы на русском и английском языках.</i>"
        )
        await query.message.edit_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=back_keyboard(),
        )

    elif data == "profile":
        scans_count = get_monthly_scan_count(user.id)
        has_prem = is_premium(user.id)
        prem_until = get_premium_until(user.id)

        if has_prem:
            status_str = f"💎 <b>Premium Безлимит</b>\n<b>Действует до:</b> <code>{prem_until} (UTC)</code>"
        else:
            status_str = f"<b>Бесплатный</b> ({scans_count}/{FREE_SCANS_PER_MONTH} использовано)"

        text = (
            "👤 <b>Профиль пользователя</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Имя:</b> {html.escape(user.first_name or 'Пользователь')}\n"
            f"<b>ID:</b> <code>{user.id}</code>\n"
            f"<b>Статус:</b> {status_str}\n"
            f"<b>Сканов в этом месяце:</b> <code>{scans_count}</code>\n"
        )

        rows = []
        if not has_prem:
            rows.append([
                InlineKeyboardButton(
                    text="Оформить Премиум",
                    callback_data="premium",
                    icon_custom_emoji_id=btn_id("money"),
                )
            ])
        rows.append([
            InlineKeyboardButton(
                text="Назад",
                callback_data="back_to_main",
                icon_custom_emoji_id=btn_id("back"),
            )
        ])

        await query.message.edit_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )

    elif data == "about":
        text = (
            f"ℹ️ <b>О сервисе {BOT_NAME}</b>\n\n"
            f"🤖 <b>LabelSpy</b> — независимый эксперт по составам продуктов и добавок.\n\n"
            f"Многие производители маскируют вредные добавки и экономят на сырье.\n\n"
            f"<b>✅ Что проверяет наш AI:</b>\n"
            f"• Чистоту спортивных добавок (протеин, креатин, BCAA)\n"
            f"• Наличие опасных красителей и консервантов\n"
            f"• Скрытый сахар и подсластители\n"
            f"• Качество и биодоступность витаминов\n\n"
            f"<i>Выбирайте продукты осознанно!</i>"
        )
        await query.message.edit_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=back_keyboard(),
        )

    elif data == "premium":
        demo_hint = f" (или демо на {DEMO_PREMIUM_DAYS} дн.)" if user.id == ADMIN_ID else ""
        text = (
            f"{tag('money')} <b>LabelSpy Premium</b>\n\n"
            "Премиум-возможности подписки:\n"
            f"• {tag('check')} <b>Безлимитный AI-анализ</b> 24/7 (без месячных лимитов)\n"
            f"• {tag('stats')} <b>Детальный разбор добавок</b>, Е-кодов и скрытого сахара\n"
            f"• {tag('file')} <b>Подробные рекомендации</b> по чистоте состава\n\n"
            f"<b>Стоимость подписки:</b> <b>{PREMIUM_STARS_PRICE} ⭐ Stars (~$0.99) на {PREMIUM_SUBSCRIPTION_DAYS} дней</b>\n\n"
            f"<i>Нажмите кнопку ниже для оплаты{demo_hint}:</i>"
        )
        await query.message.edit_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=premium_keyboard(user.id),
        )

    elif data == "buy_premium_stars":
        title = f"LabelSpy Premium ({PREMIUM_SUBSCRIPTION_DAYS} дней)"
        description = "Безлимитный AI-анализ составов продуктов, добавок и спортивного питания 24/7."
        payload = f"premium_1m_{user.id}"
        currency = "XTR"
        prices = [LabeledPrice(f"Подписка на {PREMIUM_SUBSCRIPTION_DAYS} дней", PREMIUM_STARS_PRICE)]

        await context.bot.send_invoice(
            chat_id=query.message.chat_id,
            title=title,
            description=description,
            payload=payload,
            provider_token="",  # Для Telegram Stars provider_token всегда пустая строка
            currency=currency,
            prices=prices,
        )

    elif data == "activate_test_premium":
        if user.id != ADMIN_ID:
            return
        new_until = grant_premium(user.id, duration_days=DEMO_PREMIUM_DAYS)
        await query.message.edit_text(
            f"🎉 <b>Поздравляем! Демо-Премиум активирован на {DEMO_PREMIUM_DAYS} дней!</b>\n\n"
            f"📅 <b>Подписка активна до:</b> <code>{new_until} (UTC)</code>.\n"
            f"Теперь у вас безлимитные сканы без ограничений ✅.\n"
            f"Отправьте любое фото этикетки!",
            parse_mode=ParseMode.HTML,
            reply_markup=back_keyboard(),
        )

    elif data.startswith("card_"):
        try:
            scan_id = int(data.split("_")[1])
            scan = get_scan(scan_id)
            if not scan or not scan.get("analysis_json"):
                await query.answer("Карточка для этого анализа устарела. Сделайте новый скан!", show_alert=True)
                return

            await query.answer("Генерирую инфографику...")
            analysis_data = json.loads(scan["analysis_json"])
            card_bytes = create_report_card(
                product_name=analysis_data.get("product_name", "Продукт"),
                score_str=analysis_data.get("score", "5.0/10"),
                verdict=analysis_data.get("verdict", ""),
                warnings=analysis_data.get("warnings", []),
                positives=analysis_data.get("positives", []),
            )

            bot_user = context.bot.username or "labelspy_bot"
            product_name_clean = html.escape(str(analysis_data.get("product_name", "Продукт")))
            score_clean = html.escape(str(analysis_data.get("score", "5.0/10")))

            caption = (
                f"📊 <b>Инфографика:</b> {product_name_clean}\n"
                f"⭐ Рейтинг безопасности: <code>{score_clean}</code>\n\n"
                f"<i>🤖 Проверено в @{bot_user}</i>"
            )

            await query.message.reply_photo(
                photo=card_bytes,
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.error(f"Ошибка генерации карточки: {e}")
            await query.answer("Не удалось сгенерировать карточку отчёта.", show_alert=True)



async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение готовности принять оплату в Stars со строгой проверкой параметров."""
    query = update.pre_checkout_query
    user = query.from_user
    expected_payload = f"premium_1m_{user.id}"

    # Строгая проверка параметров заказа
    if query.currency != "XTR":
        logger.warning(f"Отказ pre-checkout: неверная валюта '{query.currency}' от пользователя {user.id}")
        await query.answer(ok=False, error_message="Неверная валюта заказа. Оплата принимается в Telegram Stars.")
        return

    if query.total_amount != PREMIUM_STARS_PRICE:
        logger.warning(f"Отказ pre-checkout: неверная сумма {query.total_amount} от пользователя {user.id}")
        await query.answer(ok=False, error_message=f"Неверная сумма заказа. Ожидалось {PREMIUM_STARS_PRICE} Stars.")
        return

    if query.invoice_payload != expected_payload:
        logger.warning(f"Отказ pre-checkout: неверный payload '{query.invoice_payload}' от пользователя {user.id}")
        await query.answer(ok=False, error_message="Заказ устарел или не соответствует вашему аккаунту. Попробуйте снова.")
        return

    await query.answer(ok=True)


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка успешной оплаты через Telegram Stars с идемпотентностью и проверкой."""
    user = update.effective_user
    payment = update.message.successful_payment
    expected_payload = f"premium_1m_{user.id}"

    if payment.currency != "XTR" or payment.total_amount != PREMIUM_STARS_PRICE or payment.invoice_payload != expected_payload:
        logger.error(f"Несоответствие данных успешного платежа для пользователя {user.id}: {payment}")
        await update.message.reply_text(
            "⚠️ <b>Данные платежа не прошли проверку.</b> Пожалуйста, обратитесь к администратору для ручной активации.",
            parse_mode=ParseMode.HTML,
        )
        return

    charge_id = payment.telegram_payment_charge_id
    is_new, new_until = record_successful_payment(
        charge_id=charge_id,
        user_id=user.id,
        amount=payment.total_amount,
        currency=payment.currency,
        payload=payment.invoice_payload,
        duration_days=PREMIUM_SUBSCRIPTION_DAYS,
    )

    if is_new:
        text = (
            f"🎉 <b>Оплата прошла успешно!</b>\n\n"
            f"Вам начислен <b>LabelSpy Premium</b> на {PREMIUM_SUBSCRIPTION_DAYS} дней.\n"
            f"Сумма: <code>{payment.total_amount} ⭐ Telegram Stars</code>.\n"
            f"📅 <b>Подписка активна до:</b> <code>{new_until} (UTC)</code>\n\n"
            f"Теперь у вас полный безлимит на сканирование этикеток 24/7! 📷"
        )
    else:
        text = (
            f"ℹ️ <b>Этот платёж уже был учтён ранее.</b>\n\n"
            f"Ваш <b>LabelSpy Premium</b> активен до: <code>{new_until} (UTC)</code>.\n"
            f"Повторное продление не производилось."
        )

    await update.message.reply_text(
        text=text,
        parse_mode=ParseMode.HTML,
    )


async def handle_text_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий кнопок постоянного нижнего меню и текстовых запросов."""
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip().lower()
    user = update.effective_user
    add_user(user.id, user.username or "", user.first_name or "")

    if "скан" in text:
        msg = (
            f"{tag('file')} <b>Как сделать идеальный скан:</b>\n\n"
            "1. Сфотографируйте блок <b>'Состав'</b> или <b>'Supplement Facts'</b>.\n"
            "2. Держите камеру ровно при хорошем свете.\n"
            "3. Убедитесь, что текст четкий и читаемый.\n"
            f"4. Отправьте фото прямо в этот чат!\n\n"
            f"{tag('pencil')} <i>Бот одинаково хорошо читает составы на русском и английском языках.</i>"
        )
        await update.message.reply_text(
            text=msg,
            parse_mode=ParseMode.HTML,
        )

    elif "профиль" in text:
        scans_count = get_monthly_scan_count(user.id)
        has_prem = is_premium(user.id)
        prem_until = get_premium_until(user.id)

        if has_prem:
            status_str = f"{tag('money')} <b>Premium Безлимит</b>\n<b>Действует до:</b> <code>{prem_until} (UTC)</code>"
        else:
            status_str = f"<b>Бесплатный</b> ({scans_count}/{FREE_SCANS_PER_MONTH} использовано)"

        msg = (
            f"{tag('profile')} <b>Профиль пользователя</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Имя:</b> {html.escape(user.first_name or 'Пользователь')}\n"
            f"<b>ID:</b> <code>{user.id}</code>\n"
            f"<b>Статус:</b> {status_str}\n"
            f"<b>Сканов в этом месяце:</b> <code>{scans_count}</code>\n"
        )
        rows = []
        if not has_prem:
            rows.append([
                InlineKeyboardButton(
                    text="Оформить Премиум",
                    callback_data="premium",
                    icon_custom_emoji_id=btn_id("money"),
                )
            ])
        await update.message.reply_text(
            text=msg,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None,
        )

    elif "премиум" in text:
        demo_hint = f" (или демо на {DEMO_PREMIUM_DAYS} дн.)" if user.id == ADMIN_ID else ""
        msg = (
            f"{tag('money')} <b>LabelSpy Premium</b>\n\n"
            "Премиум-возможности подписки:\n"
            f"• {tag('check')} <b>Безлимитный AI-анализ</b> 24/7 (без месячных лимитов)\n"
            f"• {tag('stats')} <b>Детальный разбор добавок</b>, Е-кодов и скрытого сахара\n"
            f"• {tag('file')} <b>Подробные рекомендации</b> по чистоте состава\n\n"
            f"<b>Стоимость подписки:</b> <b>{PREMIUM_STARS_PRICE} ⭐ Stars (~$0.99) на {PREMIUM_SUBSCRIPTION_DAYS} дней</b>\n\n"
            f"<i>Нажмите кнопку ниже для оплаты{demo_hint}:</i>"
        )
        await update.message.reply_text(
            text=msg,
            parse_mode=ParseMode.HTML,
            reply_markup=premium_keyboard(user.id),
        )

    elif "сервис" in text or "инфо" in text:
        msg = (
            f"{tag('info')} <b>О сервисе {BOT_NAME}</b>\n\n"
            f"{tag('bot')} <b>LabelSpy</b> — независимый эксперт по составам продуктов и добавок.\n\n"
            f"Многие производители маскируют вредные добавки и экономят на сырье.\n\n"
            f"<b>{tag('check')} Что проверяет наш AI:</b>\n"
            f"• Чистоту спортивных добавок (протеин, креатин, BCAA)\n"
            f"• Наличие опасных красителей и консервантов\n"
            f"• Скрытый сахар и подсластители\n"
            f"• Качество и биодоступность витаминов\n\n"
            f"<i>Выбирайте продукты осознанно!</i>"
        )
        await update.message.reply_text(
            text=msg,
            parse_mode=ParseMode.HTML,
        )

    elif any(greeting in text for greeting in ["привет", "здравствуй", "хай", "hello", "hi", "салют"]):
        greeting_text = (
            f"👋 <b>Привет, {html.escape(user.first_name or 'друг')}!</b>\n\n"
            f"Я бот <b>{BOT_NAME}</b> — проверяю составы продуктов питания, витаминов и добавок.\n\n"
            f"📷 <b>Как проверить:</b> сфотографируйте этикетку с составом и отправьте фото сюда!\n\n"
            f"Также вы можете пользоваться кнопками меню внизу экрана."
        )
        await update.message.reply_text(text=greeting_text, parse_mode=ParseMode.HTML)

    elif any(q in text for q in ["помощь", "help", "как пользоваться", "инструкция"]):
        help_text = (
            f"{tag('file')} <b>Инструкция по использованию:</b>\n\n"
            "1. Сфотографируйте блок <b>'Состав'</b> или <b>'Ingredients'</b> на упаковке.\n"
            "2. Отправьте фото в этот чат.\n"
            "3. AI за несколько секунд выдаст детальный вердикт и оценку безопасности."
        )
        await update.message.reply_text(text=help_text, parse_mode=ParseMode.HTML)

    else:
        await update.message.reply_text(
            f"<i>{tag('photo')} Отправьте фото этикетки с составом прямо в чат или воспользуйтесь кнопками меню внизу!</i>",
            parse_mode=ParseMode.HTML,
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help."""
    user = update.effective_user
    add_user(user.id, user.username or "", user.first_name or "")
    text = (
        f"{tag('file')} <b>Как пользоваться {BOT_NAME}:</b>\n\n"
        "1. Сфотографируйте блок <b>'Состав'</b> или <b>'Supplement Facts'</b> на упаковке.\n"
        "2. Отправьте фото прямо в чат.\n"
        "3. AI мгновенно оценит чистоту состава, выявит скрытый сахар и сомнительные добавки.\n\n"
        f"• {tag('profile')} <b>Профиль</b> — проверка лимита бесплатных сканов\n"
        f"• {tag('money')} <b>Премиум</b> — безлимитный анализ 24/7\n\n"
        f"<i>{tag('photo')} Отправьте фото этикетки для анализа!</i>"
    )
    await update.message.reply_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_reply_keyboard(),
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика бота для администратора."""
    user = update.effective_user
    if user.id != ADMIN_ID:
        return
    total_users = get_total_users()
    total_scans = get_total_scans()
    text = (
        f"📊 <b>Статистика {BOT_NAME}:</b>\n\n"
        f"👥 Пользователей в базе: <code>{total_users}</code>\n"
        f"📷 Всего сканирований: <code>{total_scans}</code>\n"
    )
    await update.message.reply_text(text=text, parse_mode=ParseMode.HTML)


def main():
    """Запуск бота."""
    print("Инициализация базы данных...")
    init_db()

    # Запускаем фоновый веб-сервер для облачных хостингов
    threading.Thread(target=start_health_server, daemon=True).start()

    print(f"Запуск {BOT_NAME}...")
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    # Поддерживаем и обычные фото, и документы-изображения (отправка «без сжатия»)
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_menu))

    print(f"Бот @labelspy_bot успешно запущен!")
    application.run_polling()


if __name__ == "__main__":
    main()
