import os
import re
import html
import uuid
import sqlite3
import logging
from decimal import Decimal, InvalidOperation

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    LinkPreviewOptions,
)

from telegram.constants import ParseMode

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# =========================
# CONFIG
# =========================

TOKEN = os.environ["BOT_TOKEN"]

GRAM_EMOJI_ID = os.getenv(
    "GRAM_EMOJI_ID",
    "5318901904686754959",
)

DB_PATH = os.getenv(
    "DB_PATH",
    "offers.db",
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================
# DATABASE
# =========================

def db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with db() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS offers (
                id TEXT PRIMARY KEY,
                owner INTEGER NOT NULL,
                buyer TEXT NOT NULL,
                gift_name TEXT NOT NULL,
                gift_number TEXT NOT NULL,
                gift_url TEXT NOT NULL,
                price TEXT NOT NULL,
                currency TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                recipient INTEGER
            )
            """
        )


def save_offer(offer):
    with db() as connection:
        connection.execute(
            """
            INSERT INTO offers (
                id,
                owner,
                buyer,
                gift_name,
                gift_number,
                gift_url,
                price,
                currency,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                offer["id"],
                offer["owner"],
                offer["buyer"],
                offer["gift_name"],
                offer["gift_number"],
                offer["gift_url"],
                offer["price"],
                offer["currency"],
                "pending",
            ),
        )


def get_offer(offer_id):
    with db() as connection:
        row = connection.execute(
            "SELECT * FROM offers WHERE id = ?",
            (offer_id,),
        ).fetchone()

    return dict(row) if row else None


def get_user_offers(user_id):
    with db() as connection:
        rows = connection.execute(
            """
            SELECT * FROM offers
            WHERE owner = ?
            ORDER BY rowid DESC
            LIMIT 30
            """,
            (user_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def update_offer_status(offer_id, old_status, new_status, recipient=None):
    with db() as connection:
        result = connection.execute(
            """
            UPDATE offers
            SET status = ?, recipient = ?
            WHERE id = ? AND status = ?
            """,
            (
                new_status,
                recipient,
                offer_id,
                old_status,
            ),
        )

        return result.rowcount > 0


# =========================
# GIFT
# =========================

def parse_gift(text):
    match = re.search(
        r"(?:https?://)?t\.me/nft/([A-Za-z0-9_-]+)-(\d+)",
        text.strip(),
        re.IGNORECASE,
    )

    if not match:
        return None

    slug = match.group(1)
    number = match.group(2)

    name = re.sub(
        r"(?<=[a-z])(?=[A-Z])",
        " ",
        slug,
    )

    return {
        "gift_name": name,
        "gift_number": number,
        "gift_url": f"https://t.me/nft/{slug}-{number}",
    }


def gift_title(offer):
    return (
        f'{offer["gift_name"]} '
        f'#{offer["gift_number"]}'
    )


# =========================
# EMOJI / PRICE
# =========================

def gram_emoji():
    return (
        f'<tg-emoji emoji-id="{GRAM_EMOJI_ID}">'
        "💎"
        "</tg-emoji>"
    )


def price_html(offer):
    price = html.escape(str(offer["price"]))

    if offer["currency"] == "GRAM":
        return f"{price} {gram_emoji()} GRAM"

    return f"{price} TON"


def price_plain(offer):
    if offer["currency"] == "GRAM":
        return f'{offer["price"]} 💎 GRAM'

    return f'{offer["price"]} TON'


def gift_link_html(offer):
    url = html.escape(
        offer["gift_url"],
        quote=True,
    )

    title = html.escape(gift_title(offer))

    return f'<a href="{url}">{title}</a>'


def preview_options():
    return LinkPreviewOptions(
        is_disabled=False,
        show_above_text=True,
        prefer_large_media=True,
    )


# =========================
# OFFER TEXTS
# =========================

def pending_text(offer):
    buyer = html.escape(offer["buyer"])

    return (
        f'{gift_link_html(offer)}\n\n'
        f'Пользователь <b>{buyer}</b> предлагает '
        f'Вам <b>{price_html(offer)}</b> '
        f'за подарок <b>{html.escape(gift_title(offer))}</b>.'
    )


def accepted_text(offer):
    return (
        f'{gift_link_html(offer)}\n\n'
        "<b>Предложение принято!</b>\n\n"
        f'Подарок: <b>{html.escape(gift_title(offer))}</b>\n'
        f'Стоимость: <b>{price_html(offer)}</b>\n\n'
        "Статус: <b>Ожидается оплата</b>."
    )


def rejected_text(offer):
    return (
        f'{gift_link_html(offer)}\n\n'
        "<b>Предложение отклонено.</b>\n\n"
        f'Стоимость: <b>{price_html(offer)}</b>'
    )


def offer_text(offer):
    if offer["status"] == "accepted":
        return accepted_text(offer)

    if offer["status"] == "rejected":
        return rejected_text(offer)

    return pending_text(offer)


# =========================
# KEYBOARDS
# =========================

def main_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Создать оффер",
                    callback_data="create",
                )
            ],
            [
                InlineKeyboardButton(
                    "Мои офферы",
                    callback_data="my_offers",
                )
            ],
        ]
    )


def currency_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💎 GRAM",
                    callback_data="currency:GRAM",
                ),
                InlineKeyboardButton(
                    "TON",
                    callback_data="currency:TON",
                ),
            ]
        ]
    )


def offer_keyboard(offer):
    offer_id = offer["id"]

    if offer["status"] == "pending":
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Отклонить",
                        callback_data=f"reject:{offer_id}",
                    ),
                    InlineKeyboardButton(
                        "Принять",
                        callback_data=f"accept:{offer_id}",
                    ),
                ]
            ]
        )

    if offer["status"] == "accepted":
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Статус оплаты",
                        callback_data=f"payment:{offer_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "Как завершить сделку?",
                        callback_data=f"help:{offer_id}",
                    )
                ],
            ]
        )

    return None


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "<b>Gift Market</b>\n\n"
        "Создавай предложения о покупке "
        "коллекционных подарков Telegram.\n\n"
        "Выбери действие:",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )


async def create_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["step"] = "gift"

    message = (
        "<b>Создание предложения</b>\n\n"
        "Отправь ссылку на NFT-подарок.\n\n"
        "Пример:\n"
        "<code>https://t.me/nft/PlushPepe-2687</code>"
    )

    if update.callback_query:
        await update.callback_query.answer()

        await update.callback_query.message.reply_text(
            message,
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.HTML,
        )


# =========================
# CREATION STEPS
# =========================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    step = context.user_data.get("step")

    if not step:
        return

    text = update.message.text.strip()

    if step == "gift":
        gift = parse_gift(text)

        if not gift:
            await update.message.reply_text(
                "Неверная ссылка.\n\n"
                "Отправь ссылку формата:\n"
                "https://t.me/nft/PlushPepe-2687"
            )
            return

        context.user_data["gift"] = gift
        context.user_data["step"] = "buyer"

        await update.message.reply_text(
            f'Подарок: {gift["gift_name"]} '
            f'#{gift["gift_number"]}\n\n'
            "Теперь введи имя покупателя."
        )

        return

    if step == "buyer":
        if len(text) > 64:
            await update.message.reply_text(
                "Имя слишком длинное. Максимум 64 символа."
            )
            return

        context.user_data["buyer"] = text
        context.user_data["step"] = "currency"

        await update.message.reply_text(
            "Выбери валюту предложения:",
            reply_markup=currency_keyboard(),
        )

        return

    if step == "currency":
        await update.message.reply_text(
            "Сначала выбери валюту кнопкой выше."
        )
        return

    if step == "price":
        try:
            price = Decimal(
                text.replace(",", ".")
            )

            if not price.is_finite() or price <= 0:
                raise InvalidOperation

            if price > Decimal("1000000000"):
                raise InvalidOperation

        except (InvalidOperation, ValueError):
            await update.message.reply_text(
                "Введи корректную сумму.\n"
                "Например: 20 или 1.5"
            )
            return

        gift = context.user_data["gift"]

        offer = {
            "id": uuid.uuid4().hex[:12],
            "owner": update.effective_user.id,
            "buyer": context.user_data["buyer"],
            "gift_name": gift["gift_name"],
            "gift_number": gift["gift_number"],
            "gift_url": gift["gift_url"],
            "price": format(price, "f"),
            "currency": context.user_data["currency"],
        }

        save_offer(offer)

        context.user_data.clear()

        username = context.bot.username

        await update.message.reply_text(
            "<b>Предложение создано!</b>\n\n"
            f'Подарок: {html.escape(gift_title(offer))}\n'
            f'Цена: {html.escape(price_plain(offer))}\n\n'
            "Чтобы отправить предложение:\n\n"
            "1. Открой нужный чат.\n"
            f"2. Напиши <code>@{username}</code> и пробел.\n"
            "3. Выбери созданное предложение.",
            parse_mode=ParseMode.HTML,
        )

        return


# =========================
# INLINE MODE
# =========================

async def inline_query(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.inline_query

    user_id = query.from_user.id

    user_offers = get_user_offers(user_id)

    search = query.query.strip().lower()

    results = []

    for offer in user_offers:
        if offer["status"] != "pending":
            continue

        title = gift_title(offer)

        if search and search not in title.lower():
            continue

        result = InlineQueryResultArticle(
            id=offer["id"],
            title=title,
            description=(
                f'{offer["buyer"]} · '
                f'{price_plain(offer)}'
            ),
            input_message_content=InputTextMessageContent(
                message_text=pending_text(offer),
                parse_mode=ParseMode.HTML,
                link_preview_options=preview_options(),
            ),
            reply_markup=offer_keyboard(offer),
        )

        results.append(result)

    await query.answer(
        results=results,
        cache_time=0,
        is_personal=True,
    )


# =========================
# MY OFFERS
# =========================

async def show_my_offers(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    offers = get_user_offers(
        update.effective_user.id
    )

    if not offers:
        text = "У тебя пока нет созданных предложений."
    else:
        lines = ["<b>Мои предложения</b>\n"]

        for offer in offers[:15]:
            status = {
                "pending": "Ожидает ответа",
                "accepted": "Принято, ожидается оплата",
                "rejected": "Отклонено",
            }.get(
                offer["status"],
                offer["status"],
            )

            lines.append(
                f'<b>{html.escape(gift_title(offer))}</b>\n'
                f'{html.escape(price_plain(offer))}\n'
                f'Статус: {status}\n'
                f'ID: <code>{offer["id"]}</code>\n'
            )

        text = "\n".join(lines)

    if update.callback_query:
        await update.callback_query.answer()

        await update.callback_query.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
        )


# =========================
# BUTTONS
# =========================

async def handle_buttons(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    data = query.data or ""

    user_id = query.from_user.id

    if data == "create":
        await create_offer(update, context)
        return

    if data == "my_offers":
        await show_my_offers(update, context)
        return

    if data.startswith("currency:"):
        currency = data.split(":", 1)[1]

        if context.user_data.get("step") != "currency":
            await query.answer(
                "Начни создание предложения заново.",
                show_alert=True,
            )
            return

        if currency not in ("TON", "GRAM"):
            await query.answer(
                "Неизвестная валюта.",
                show_alert=True,
            )
            return

        context.user_data["currency"] = currency
        context.user_data["step"] = "price"

        await query.answer()

        await query.message.reply_text(
            f"Валюта: {currency}\n\n"
            "Теперь введи сумму предложения."
        )

        return

    if ":" not in data:
        await query.answer()
        return

    action, offer_id = data.split(":", 1)

    offer = get_offer(offer_id)

    if not offer:
        await query.answer(
            "Предложение не найдено.",
            show_alert=True,
        )
        return

    if action in ("accept", "reject"):
        if offer["status"] != "pending":
            await query.answer(
                "Это предложение уже обработано.",
                show_alert=True,
            )
            return

        if user_id == offer["owner"]:
            await query.answer(
                "Нельзя принять собственное предложение.",
                show_alert=True,
            )
            return

        new_status = (
            "accepted"
            if action == "accept"
            else "rejected"
        )

        changed = update_offer_status(
            offer_id,
            "pending",
            new_status,
            user_id,
        )

        if not changed:
            await query.answer(
                "Предложение уже обработано.",
                show_alert=True,
            )
            return

        offer = get_offer(offer_id)

        if action == "accept":
            await query.answer(
                "Предложение принято!",
                show_alert=True,
            )
        else:
            await query.answer(
                "Предложение отклонено.",
                show_alert=True,
            )

        try:
            await query.edit_message_text(
                text=offer_text(offer),
                parse_mode=ParseMode.HTML,
                link_preview_options=preview_options(),
                reply_markup=offer_keyboard(offer),
            )

        except Exception:
            logger.exception(
                "Не удалось обновить сообщение оффера"
            )

        try:
            action_text = (
                "принято"
                if action == "accept"
                else "отклонено"
            )

            await context.bot.send_message(
                chat_id=offer["owner"],
                text=(
                    f'Предложение по подарку '
                    f'{gift_title(offer)} '
                    f'{action_text}.\n\n'
                    f'Цена: {price_plain(offer)}'
                ),
            )

        except Exception:
            logger.exception(
                "Не удалось уведомить создателя"
            )

        return

    if action == "payment":
        if offer["status"] != "accepted":
            await query.answer(
                "Предложение ещё не принято.",
                show_alert=True,
            )
            return

        await query.answer(
            "Оплата пока не подтверждена.",
            show_alert=True,
        )

        return

    if action == "help":
        await query.answer(
            "После подтверждения оплаты "
            "согласуйте передачу подарка. "
            "Не передавайте NFT до получения средств.",
            show_alert=True,
        )

        return

    await query.answer()


# =========================
# CANCEL
# =========================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data.clear()

    await update.message.reply_text(
        "Создание предложения отменено.",
        reply_markup=main_keyboard(),
    )


# =========================
# ERRORS
# =========================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    logger.error(
        "Ошибка при обработке обновления",
        exc_info=(
            type(context.error),
            context.error,
            context.error.__traceback__,
        ) if context.error else None,
    )


# =========================
# MAIN
# =========================

def main():
    init_db()

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("offer", create_offer)
    )

    app.add_handler(
        CommandHandler("my_offers", show_my_offers)
    )

    app.add_handler(
        CommandHandler("cancel", cancel)
    )

    app.add_handler(
        InlineQueryHandler(inline_query)
    )

    app.add_handler(
        CallbackQueryHandler(handle_buttons)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    app.add_error_handler(error_handler)

    logger.info("Gift Market Bot запущен")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
