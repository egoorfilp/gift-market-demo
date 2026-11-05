import os
import re
import uuid
import html
import logging

from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    LinkPreviewOptions,
    MessageEntity,
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

GRAM_EMOJI_ID = os.getenv(
    "GRAM_EMOJI_ID",
    "5318901904686754959"
)

offers = {}


# -------------------------
# ОБЩИЕ ФУНКЦИИ
# -------------------------

def escape(value):
    return html.escape(str(value), quote=True)


def menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "Создать оффер",
                callback_data="create"
            )
        ],
        [
            InlineKeyboardButton(
                "Мои офферы",
                callback_data="my_offers"
            )
        ]
    ])


def parse_gift(text):
    text = text.strip()

    match = re.fullmatch(
        r"(?:https?://)?t\.me/nft/([A-Za-z0-9_-]+)-(\d+)/?",
        text,
        re.IGNORECASE
    )

    if match:
        collection = match.group(1)
        number = match.group(2)

        return {
            "title": f"{collection} #{number}",
            "url": (
                f"https://t.me/nft/"
                f"{collection}-{number}"
            )
        }

    parsed = urlparse(text)

    if (
        parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
    ):
        return {
            "title": "NFT",
            "url": text
        }

    return None


# -------------------------
# ВАЛЮТЫ
# -------------------------

def price_html(offer):
    price = escape(offer["price"])
    currency = offer["currency"]

    if currency == "GRAM" and GRAM_EMOJI_ID:
        return (
            f"{price} "
            f'<tg-emoji emoji-id="{GRAM_EMOJI_ID}">'
            "💎"
            "</tg-emoji>"
            " GRAM"
        )

    return f"{price} {escape(currency)}"


def price_plain(offer):
    return (
        f"{offer['price']} "
        f"{offer['currency']}"
    )


# -------------------------
# КАРТОЧКА NFT
# -------------------------

def offer_text(offer):
    title = escape(offer["title"])
    buyer = escape(offer["buyer"])

    price = price_html(offer)

    # Ссылка спрятана в названии.
    # Telegram использует её для предпросмотра.
    gift_link = (
        f'<a href="{escape(offer["url"])}">'
        f"{title}</a>"
    )

    if offer["status"] == "pending":
        return (
            f"{gift_link}\n\n"
            f"В предложении указан покупатель "
            f"{buyer}, цена — {price}."
        )

    if offer["status"] == "accepted":
        return (
            f"{gift_link}\n\n"
            "Предложение принято.\n"
            f"Цена: {price}\n\n"
            "Статус: ожидается оплата.\n"
            "Оплата не подтверждена."
        )

    if offer["status"] == "rejected":
        return (
            f"{gift_link}\n\n"
            "Предложение отклонено."
        )

    return "Предложение недоступно."


def offer_buttons(offer_id):
    offer = offers.get(offer_id)

    if not offer:
        return None

    if offer["status"] != "pending":
        return None

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "Отклонить",
                callback_data=f"reject:{offer_id}"
            ),
            InlineKeyboardButton(
                "Принять",
                callback_data=f"accept:{offer_id}"
            )
        ]
    ])


def preview_options():
    return LinkPreviewOptions(
        is_disabled=False,
        show_above_text=True,
        prefer_large_media=True
    )


# -------------------------
# КОМАНДЫ
# -------------------------

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "Gift Market\n\n"
        "Выбери действие:",
        reply_markup=menu()
    )


async def create_offer(update, context):
    context.user_data.clear()
    context.user_data["step"] = "gift"

    await update.effective_message.reply_text(
        "Отправь ссылку на NFT-подарок."
    )


async def gram_test(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not GRAM_EMOJI_ID:
        await update.message.reply_text(
            "GRAM_EMOJI_ID не задан."
        )
        return

    try:
        await update.message.reply_text(
            "💎",
            entities=[
                MessageEntity(
                    type=MessageEntity.CUSTOM_EMOJI,
                    offset=0,
                    length=2,
                    custom_emoji_id=GRAM_EMOJI_ID
                )
            ]
        )
    except Exception:
        logging.exception("GRAM emoji test failed")

        await update.message.reply_text(
            "Telegram не разрешил отправить "
            "этот кастомный эмодзи."
        )


# -------------------------
# СОЗДАНИЕ ОФФЕРА
# -------------------------

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.message

    if not message:
        return

    # Поиск кастомных эмодзи
    entities = list(message.entities or [])
    entities += list(message.caption_entities or [])

    emoji_ids = [
        entity.custom_emoji_id
        for entity in entities
        if entity.type == MessageEntity.CUSTOM_EMOJI
    ]

    if emoji_ids:
        await message.reply_text(
            "Найдены ID кастомных эмодзи:\n\n"
            + "\n".join(emoji_ids)
        )
        return

    if not message.text:
        return

    text = message.text.strip()
    step = context.user_data.get("step")

    # ССЫЛКА
    if step == "gift":
        gift = parse_gift(text)

        if not gift:
            await message.reply_text(
                "Отправь корректную HTTPS-ссылку."
            )
            return

        context.user_data["gift"] = gift
        context.user_data["step"] = "buyer"

        await message.reply_text(
            f"Подарок: {gift['title']}\n\n"
            "Введи отображаемое имя покупателя."
        )
        return

    # ПОКУПАТЕЛЬ
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
                        callback_data="currency:TON"
                    ),
                    InlineKeyboardButton(
                        "GRAM",
                        callback_data="currency:GRAM"
                    )
                ]
            ])
        )
        return

    # ЦЕНА
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

        offer_id = uuid.uuid4().hex[:12]

        offer = {
            "id": offer_id,
            "owner": update.effective_user.id,
            "buyer": context.user_data["buyer"],
            "title": gift["title"],
            "url": gift["url"],
            "price": format(price, "f"),
            "currency": context.user_data["currency"],
            "status": "pending"
        }

        offers[offer_id] = offer

        context.user_data.clear()

        await message.reply_text(
            "Оффер создан.\n\n"
            f"Подарок: {offer['title']}\n"
            f"Цена: {price_plain(offer)}\n\n"
            "Чтобы отправить его, введи "
            f"@{context.bot.username} "
            "в нужном чате и выбери оффер.",
            reply_markup=offer_buttons(offer_id)
        )
        return

    await message.reply_text(
        "Выбери действие:",
        reply_markup=menu()
    )


# -------------------------
# INLINE-ОФФЕРЫ
# -------------------------

async def inline_query(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.inline_query.from_user.id

    results = []

    for offer_id, offer in offers.items():
        if offer["owner"] != user_id:
            continue

        if offer["status"] != "pending":
            continue

        results.append(
            InlineQueryResultArticle(
                id=offer_id,
                title=offer["title"],
                description=price_plain(offer),
                input_message_content=InputTextMessageContent(
                    message_text=offer_text(offer),
                    parse_mode="HTML",
                    link_preview_options=preview_options()
                ),
                reply_markup=offer_buttons(offer_id)
            )
        )

    await update.inline_query.answer(
        results[:30],
        cache_time=0,
        is_personal=True
    )


# -------------------------
# КНОПКИ
# -------------------------

async def buttons(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    data = query.data

    if data == "create":
        await query.answer()
        await create_offer(update, context)
        return

    if data == "my_offers":
        await query.answer()

        user_offers = [
            offer
            for offer in offers.values()
            if offer["owner"] == query.from_user.id
        ]

        if not user_offers:
            await query.message.reply_text(
                "У тебя пока нет офферов."
            )
            return

        lines = ["Мои офферы:\n"]

        for offer in user_offers[-15:]:
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
                show_alert=True
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
            f"Валюта: {currency}\n\n"
            "Введи цену."
        )
        return

    if data.startswith(("accept:", "reject:")):
        action, offer_id = data.split(":", 1)

        offer = offers.get(offer_id)

        if not offer:
            await query.answer(
                "Оффер не найден.",
                show_alert=True
            )
            return

        if offer["status"] != "pending":
            await query.answer(
                "На оффер уже ответили.",
                show_alert=True
            )
            return

        if query.from_user.id == offer["owner"]:
            await query.answer(
                "Нельзя ответить на собственный оффер.",
                show_alert=True
            )
            return

        if action == "accept":
            offer["status"] = "accepted"
        else:
            offer["status"] = "rejected"

        await query.answer(
            (
                "Предложение принято. "
                "Оплата ещё не подтверждена."
            )
            if action == "accept"
            else "Предложение отклонено.",
            show_alert=True
        )

        # Сохраняем ссылку внутри названия,
        # чтобы Telegram мог оставить предпросмотр.
        try:
            await query.edit_message_text(
                text=offer_text(offer),
                parse_mode="HTML",
                reply_markup=None,
                link_preview_options=preview_options()
            )
        except Exception:
            logging.exception(
                "Не удалось обновить карточку"
            )

        # Уведомление создателю
        try:
            await context.bot.send_message(
                chat_id=offer["owner"],
                text=(
                    f"Оффер: {offer['title']}\n"
                    f"Цена: {price_plain(offer)}\n"
                    f"Статус: {offer['status']}"
                )
            )
        except Exception:
            logging.exception(
                "Не удалось отправить уведомление"
            )

        return

    await query.answer()


# -------------------------
# ЗАПУСК
# -------------------------

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("offer", create_offer)
    )

    app.add_handler(
        CommandHandler("gramtest", gram_test)
    )

    app.add_handler(
        InlineQueryHandler(inline_query)
    )

    app.add_handler(
        CallbackQueryHandler(buttons)
    )

    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            handle_message
        )
    )

    app.run_polling()


if __name__ == "__main__":
    main()
