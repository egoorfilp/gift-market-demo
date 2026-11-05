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

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)

TOKEN = os.environ["BOT_TOKEN"]

GRAM_ID = os.getenv(
    "GRAM_EMOJI_ID",
    "5318901904686754959"
)

DB_PATH = os.getenv("DB_PATH", "offers.db")


# =====================================
# DATABASE
# =====================================

def connect():
    return sqlite3.connect(DB_PATH)


def init_db():
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS offers (
                id TEXT PRIMARY KEY,
                owner INTEGER NOT NULL,
                buyer TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                price TEXT NOT NULL,
                currency TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
            )
        """)


def save_offer(offer):
    with connect() as db:
        db.execute(
            """
            INSERT INTO offers
            (id, owner, buyer, title, url,
             price, currency, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                offer["id"],
                offer["owner"],
                offer["buyer"],
                offer["title"],
                offer["url"],
                offer["price"],
                offer["currency"],
                offer["status"],
            ),
        )


def get_offer(offer_id):
    with connect() as db:
        db.row_factory = sqlite3.Row

        row = db.execute(
            "SELECT * FROM offers WHERE id = ?",
            (offer_id,),
        ).fetchone()

        return dict(row) if row else None


def get_offers(owner):
    with connect() as db:
        db.row_factory = sqlite3.Row

        rows = db.execute(
            """
            SELECT * FROM offers
            WHERE owner = ?
            ORDER BY rowid DESC
            LIMIT 30
            """,
            (owner,),
        ).fetchall()

        return [dict(row) for row in rows]


def update_status(offer_id, status):
    with connect() as db:
        db.execute(
            """
            UPDATE offers
            SET status = ?
            WHERE id = ?
            """,
            (status, offer_id),
        )


# =====================================
# HELPERS
# =====================================

def esc(value):
    return html.escape(str(value), quote=True)


def parse_gift(text):
    match = re.fullmatch(
        r"(?:https?://)?t\.me/nft/"
        r"([A-Za-z0-9_-]+)-(\d+)/?",
        text.strip(),
        re.IGNORECASE,
    )

    if not match:
        return None

    collection = match.group(1)
    number = match.group(2)

    return {
        "title": f"{collection} #{number}",
        "url": (
            f"https://t.me/nft/"
            f"{collection}-{number}"
        ),
    }


def price_html(offer):
    price = esc(offer["price"])

    if offer["currency"] == "GRAM":
        return (
            f"{price} "
            f'<tg-emoji emoji-id="{GRAM_ID}">'
            "💎"
            "</tg-emoji>"
        )

    return f"{price} TON"


def price_plain(offer):
    return (
        f"{offer['price']} "
        f"{offer['currency']}"
    )


def preview():
    return LinkPreviewOptions(
        is_disabled=False,
        show_above_text=True,
        prefer_large_media=True,
    )


# =====================================
# OFFER CARD
# =====================================

def offer_text(offer):
    title = esc(offer["title"])
    buyer = esc(offer["buyer"])
    price = price_html(offer)

    # Ссылка находится внутри названия.
    # Telegram использует её для карточки NFT.
    gift = (
        f'<a href="{esc(offer["url"])}">'
        f"{title}</a>"
    )

    status = offer["status"]

    if status == "pending":
        return (
            f"Пользователь {buyer} предлагает "
            f"Вам {price} за подарок {gift}."
        )

    if status == "accepted":
        return (
            f"{gift}\n\n"
            "Предложение принято.\n"
            f"Цена: {price}\n\n"
            "Статус: ожидается оплата."
        )

    if status == "rejected":
        return (
            f"{gift}\n\n"
            "Предложение отклонено."
        )

    if status == "demo_paid":
        return (
            f"{gift}\n\n"
            "ТЕСТОВЫЙ РЕЖИМ\n"
            "Продажа успешно смоделирована.\n\n"
            f"Цена: {price}\n"
            "Реальная оплата не производилась."
        )

    return "Предложение недоступно."


def offer_keyboard(offer):
    offer_id = offer["id"]
    status = offer["status"]

    if status == "pending":
        return InlineKeyboardMarkup([
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
        ])

    if status == "accepted":
        return InlineKeyboardMarkup([
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
        ])

    return None


def main_menu():
    return InlineKeyboardMarkup([
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
    ])


# =====================================
# START
# =====================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "Gift Market\n\n"
        "Создание предложений для NFT-подарков.",
        reply_markup=main_menu(),
    )


async def create_offer(update, context):
    context.user_data.clear()
    context.user_data["step"] = "gift"

    await update.effective_message.reply_text(
        "Отправь ссылку на NFT-подарок."
    )


# =====================================
# CREATE OFFER
# =====================================

async def messages(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.message

    if not message or not message.text:
        return

    text = message.text.strip()
    step = context.user_data.get("step")

    if step == "gift":
        gift = parse_gift(text)

        if not gift:
            await message.reply_text(
                "Нужна ссылка вида:\n"
                "t.me/nft/PlushPepe-2687"
            )
            return

        context.user_data["gift"] = gift
        context.user_data["step"] = "buyer"

        await message.reply_text(
            f"Подарок: {gift['title']}\n\n"
            "Введи имя покупателя."
        )
        return

    if step == "buyer":
        if not 2 <= len(text) <= 40:
            await message.reply_text(
                "Имя должно содержать "
                "от 2 до 40 символов."
            )
            return

        context.user_data["buyer"] = text
        context.user_data["step"] = "currency"

        await message.reply_text(
            "Выбери валюту:",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "TON",
                        callback_data="currency:TON",
                    ),
                    InlineKeyboardButton(
                        "GRAM",
                        callback_data="currency:GRAM",
                    ),
                ]
            ]),
        )
        return

    if step == "price":
        try:
            price = Decimal(
                text.replace(",", ".")
            )
        except InvalidOperation:
            await message.reply_text(
                "Введи цену числом."
            )
            return

        if (
            not price.is_finite()
            or price <= 0
            or price > 1000000000
        ):
            await message.reply_text(
                "Укажи корректную цену."
            )
            return

        gift = context.user_data["gift"]

        offer = {
            "id": uuid.uuid4().hex[:16],
            "owner": update.effective_user.id,
            "buyer": context.user_data["buyer"],
            "title": gift["title"],
            "url": gift["url"],
            "price": format(price, "f"),
            "currency": context.user_data["currency"],
            "status": "pending",
        }

        save_offer(offer)
        context.user_data.clear()

        await message.reply_text(
            "Предложение создано.\n\n"
            f"{offer['title']}\n"
            f"Цена: {price_plain(offer)}\n\n"
            "Чтобы отправить предложение, "
            "открой нужный чат и введи:\n\n"
            f"@{context.bot.username}\n\n"
            "Выбери оффер из списка."
        )
        return

    await message.reply_text(
        "Выбери действие:",
        reply_markup=main_menu(),
    )


# =====================================
# INLINE MODE
# =====================================

async def inline_query(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = update.inline_query.from_user.id

    results = []

    for offer in get_offers(user_id):
        if offer["status"] != "pending":
            continue

        results.append(
            InlineQueryResultArticle(
                id=offer["id"],
                title=offer["title"],
                description=price_plain(offer),
                input_message_content=InputTextMessageContent(
                    message_text=offer_text(offer),
                    parse_mode="HTML",
                    link_preview_options=preview(),
                ),
                reply_markup=offer_keyboard(offer),
            )
        )

    await update.inline_query.answer(
        results[:30],
        cache_time=0,
        is_personal=True,
    )


# =====================================
# BUTTONS
# =====================================

async def buttons(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    data = query.data or ""

    if data == "create":
        await query.answer()
        await create_offer(update, context)
        return

    if data == "my_offers":
        await query.answer()

        user_offers = get_offers(
            query.from_user.id
        )

        if not user_offers:
            await query.message.reply_text(
                "Офферов пока нет."
            )
            return

        lines = ["Мои офферы:\n"]

        for offer in user_offers[:15]:
            lines.append(
                f"{offer['title']} — "
                f"{price_plain(offer)} "
                f"({offer['status']})"
            )

        await query.message.reply_text(
            "\n".join(lines)
        )
        return

    if data.startswith("currency:"):
        if context.user_data.get("step") != "currency":
            await query.answer(
                "Сначала создай оффер.",
                show_alert=True,
            )
            return

        currency = data.split(":", 1)[1]

        if currency not in ("TON", "GRAM"):
            await query.answer()
            return

        context.user_data["currency"] = currency
        context.user_data["step"] = "price"

        await query.answer()

        await query.message.reply_text(
            f"Выбрана валюта: {currency}\n\n"
            "Введи цену числом."
        )
        return

    if ":" not in data:
        await query.answer()
        return

    action, offer_id = data.split(":", 1)
    offer = get_offer(offer_id)

    if not offer:
        await query.answer(
            "Оффер не найден.",
            show_alert=True,
        )
        return

    if action in ("accept", "reject"):
        if offer["status"] != "pending":
            await query.answer(
                "На предложение уже ответили.",
                show_alert=True,
            )
            return

        if query.from_user.id == offer["owner"]:
            await query.answer(
                "Нельзя ответить на собственный оффер.",
                show_alert=True,
            )
            return

        new_status = (
            "accepted"
            if action == "accept"
            else "rejected"
        )

        update_status(offer_id, new_status)
        offer["status"] = new_status

        await query.answer(
            (
                "Предложение принято. "
                "Оплата ожидается."
            )
            if action == "accept"
            else "Предложение отклонено.",
            show_alert=True,
        )

        try:
            await query.edit_message_text(
                text=offer_text(offer),
                parse_mode="HTML",
                link_preview_options=preview(),
                reply_markup=offer_keyboard(offer),
            )
        except Exception:
            logging.exception(
                "Не удалось обновить сообщение"
            )

        try:
            await context.bot.send_message(
                chat_id=offer["owner"],
                text=(
                    f"{offer['title']}\n"
                    f"Статус: {new_status}"
                ),
            )
        except Exception:
            logging.exception(
                "Не удалось отправить уведомление"
            )

        return

    if action == "payment":
        await query.answer(
            "Оплата пока не подтверждена. "
            "Автоматическая проверка платежей "
            "не подключена.",
            show_alert=True,
        )
        return

    if action == "help":
        await query.answer(
            "Сначала подтвердите получение "
            "реальной оплаты. Передача NFT "
            "до оплаты не требуется.",
            show_alert=True,
        )
        return

    await query.answer()


# =====================================
# TEST MODE
# =====================================

async def demo_payment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not context.args:
        await update.message.reply_text(
            "Команда:\n"
            "/demo_payment ID_ОФФЕРА"
        )
        return

    offer_id = context.args[0]
    offer = get_offer(offer_id)

    if not offer:
        await update.message.reply_text(
            "Оффер не найден."
        )
        return

    if offer["owner"] != update.effective_user.id:
        await update.message.reply_text(
            "Это не твой оффер."
        )
        return

    if offer["status"] != "accepted":
        await update.message.reply_text(
            "Сначала предложение должно "
            "быть принято."
        )
        return

    update_status(offer_id, "demo_paid")

    await update.message.reply_text(
        "ТЕСТОВЫЙ РЕЖИМ\n\n"
        "Продажа успешно смоделирована.\n"
        "Реальная оплата не производилась.\n"
        "NFT не передавался."
    )


# =====================================
# ERROR HANDLER
# =====================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    logging.error(
        "Ошибка при обработке обновления",
        exc_info=context.error,
    )


# =====================================
# MAIN
# =====================================

def main():
    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("offer", create_offer)
    )

    app.add_handler(
        CommandHandler("demo_payment", demo_payment)
    )

    app.add_handler(
        InlineQueryHandler(inline_query)
    )

    app.add_handler(
        CallbackQueryHandler(buttons)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            messages,
        )
    )

    app.add_error_handler(error_handler)

    app.run_polling()


if __name__ == "__main__":
    main()
