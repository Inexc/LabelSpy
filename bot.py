"""
Telegram бот LabelSpy — AI-сканер состава продуктов и спортивного питания
Кнопки с яркими визуальными эмодзи, работающими на всех устройствах.
"""

import logging
import os
import sys
import threading
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

from config import TELEGRAM_TOKEN, FREE_SCANS_PER_MONTH, BOT_NAME, ADMIN_ID
from database import (
    init_db,
    add_user,
    get_monthly_scan_count,
    add_scan,
    is_premium,
    set_premium,
    get_user_info,
)
from emoji_helper import tag, btn_id
from analyzer import analyze_label, format_analysis_html

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

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


def analysis_keyboard() -> InlineKeyboardMarkup:
    """Кнопки под результатом анализа состава."""
    rows = [
        [
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
        ],
        [
            InlineKeyboardButton(
                text="Оформить Премиум",
                callback_data="premium",
                icon_custom_emoji_id=btn_id("money"),
            ),
        ],
    ]
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
                text="Оплатить 50 Stars (~$0.99)",
                callback_data="buy_premium_stars",
                icon_custom_emoji_id=btn_id("money"),
            )
        ],
    ]
    if user_id == ADMIN_ID:
        rows.append([
            InlineKeyboardButton(
                text="Тестовый доступ (демо)",
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
    limit_text = "Безлимитно" if user_has_prem else f"{FREE_SCANS_PER_MONTH - scans_used} из {FREE_SCANS_PER_MONTH}"

    return (
        f"{tag('bot')} <b>LABELSPY · AI СКАНИРОВАНИЕ СОСТАВА</b>\n\n"
        f"<blockquote>🤖 Персональный независимый AI-анализатор чистоты продуктов и добавок прямо в Telegram.</blockquote>\n\n"
        f"• {tag('file')} <b>Спортпит и витамины:</b> проверка реальных дозировок и качества сырья\n"
        f"• {tag('cross')} <b>Контроль рисков:</b> выявление скрытого сахара, трансжиров и вредных добавок\n"
        f"• {tag('stats')} <b>Экспертный вердикт:</b> честная оценка от 1 до 10\n\n"
        f"🪙 <b>Ваш лимит сканов:</b> <code>{limit_text}</code>\n\n"
        f"<i>📷 Отправьте фото этикетки с составом прямо в чат!</i>"
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
    """Обработка фото этикетки."""
    user = update.effective_user
    add_user(user.id, user.username or "", user.first_name or "")
    
    user_has_prem = is_premium(user.id)
    scans_used = get_monthly_scan_count(user.id)
    
    if not user_has_prem and scans_used >= FREE_SCANS_PER_MONTH:
        limit_msg = (
            f"❌ <b>Лимит бесплатных сканов исчерпан!</b>\n\n"
            f"Вы использовали все {FREE_SCANS_PER_MONTH} бесплатных сканов в этом месяце.\n\n"
            f"💎 Оформите <b>LabelSpy Premium</b> для безлимитного анализа!"
        )
        await update.message.reply_text(
            text=limit_msg,
            parse_mode=ParseMode.HTML,
            reply_markup=premium_keyboard(user.id),
        )
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    status_msg = await update.message.reply_text(
        "🔄 <b>Изучаю этикетку...</b>\n<i>AI читает состав и сверяет компоненты. Это займет несколько секунд.</i>",
        parse_mode=ParseMode.HTML,
    )

    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()

        analysis = await analyze_label(bytes(photo_bytes))
        
        product_name = analysis.get("product_name") if "error" not in analysis else "Нераспознано"
        score = analysis.get("score") if "error" not in analysis else None
        add_scan(user.id, product_name, score)

        reply_html = format_analysis_html(analysis)

        await status_msg.edit_text(
            text=reply_html,
            parse_mode=ParseMode.HTML,
            reply_markup=analysis_keyboard(),
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


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий инлайн-кнопок."""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    data = query.data

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
        status_str = "💎 <b>Premium Безлимит</b>" if has_prem else f"<b>Бесплатный</b> ({scans_count}/{FREE_SCANS_PER_MONTH} использовано)"

        text = (
            "👤 <b>Профиль пользователя</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Имя:</b> {user.first_name}\n"
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
        demo_hint = " или попробуйте демо" if user.id == ADMIN_ID else ""
        text = (
            f"{tag('money')} <b>LabelSpy Premium</b>\n\n"
            "Откройте все возможности:\n"
            f"• {tag('check')} <b>Безлимитные сканы</b> 24/7\n"
            f"• {tag('growth_chart')} <b>Приоритетная скорость</b> анализа\n"
            f"• {tag('file')} <b>Сравнение составов</b> двух продуктов\n\n"
            f"<b>Стоимость подписки:</b> <b>50 ⭐ Stars (~$0.99)</b>\n\n"
            f"<i>Нажмите кнопку ниже для оплаты{demo_hint}:</i>"
        )
        await query.message.edit_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=premium_keyboard(user.id),
        )

    elif data == "buy_premium_stars":
        title = "LabelSpy Premium (1 месяц)"
        description = "Безлимитный AI-анализ составов продуктов, добавок и спортивного питания 24/7."
        payload = f"premium_1m_{user.id}"
        currency = "XTR"
        prices = [LabeledPrice("Подписка на 30 дней", 50)]

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
            await query.answer("Эта опция доступна только администратору.", show_alert=True)
            return
        set_premium(user.id, True)
        await query.message.edit_text(
            "🎉 <b>Поздравляем! Демо-Премиум активирован!</b>\n\n"
            "Теперь у вас безлимитные сканы без ограничений ✅.\n"
            "Отправьте любое фото этикетки!",
            parse_mode=ParseMode.HTML,
            reply_markup=back_keyboard(),
        )


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение готовности принять оплату в Stars."""
    query = update.pre_checkout_query
    await query.answer(ok=True)


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка успешной оплаты через Telegram Stars."""
    user = update.effective_user
    payment = update.message.successful_payment

    # Активируем статус в базе данных
    set_premium(user.id, True)

    text = (
        f"🎉 <b>Оплата прошла успешно!</b>\n\n"
        f"Вам начислен <b>LabelSpy Premium</b> на 1 месяц.\n"
        f"Сумма: <code>{payment.total_amount} ⭐ Telegram Stars</code>.\n\n"
        f"Теперь у вас полный безлимит на сканирование этикеток 24/7! 📷"
    )
    await update.message.reply_text(
        text=text,
        parse_mode=ParseMode.HTML,
    )


async def handle_text_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий кнопок постоянного нижнего меню."""
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip().lower()
    user = update.effective_user

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
        status_str = f"{tag('money')} <b>Premium Безлимит</b>" if has_prem else f"<b>Бесплатный</b> ({scans_count}/{FREE_SCANS_PER_MONTH} использовано)"

        msg = (
            f"{tag('profile')} <b>Профиль пользователя</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Имя:</b> {user.first_name}\n"
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
        demo_hint = " или попробуйте демо" if user.id == ADMIN_ID else ""
        msg = (
            f"{tag('money')} <b>LabelSpy Premium</b>\n\n"
            "Откройте все возможности:\n"
            f"• {tag('check')} <b>Безлимитные сканы</b> 24/7\n"
            f"• {tag('growth_chart')} <b>Приоритетная скорость</b> анализа\n"
            f"• {tag('file')} <b>Сравнение составов</b> двух продуктов\n\n"
            f"<b>Стоимость подписки:</b> <b>50 ⭐ Stars (~$0.99)</b>\n\n"
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

    else:
        await update.message.reply_text(
            f"<i>{tag('photo')} Пожалуйста, отправьте фото этикетки с составом прямо в чат!</i>",
            parse_mode=ParseMode.HTML,
        )


def main():
    """Запуск бота."""
    print("Инициализация базы данных...")
    init_db()

    # Запускаем фоновый веб-сервер для облачных хостингов
    threading.Thread(target=start_health_server, daemon=True).start()

    print(f"Запуск {BOT_NAME}...")
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_menu))

    print(f"Бот @labelspy_bot успешно запущен!")
    application.run_polling()



if __name__ == "__main__":
    main()
