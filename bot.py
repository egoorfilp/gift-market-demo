import os
import re
import uuid
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

logging.basicConfig(level=logging.INFO)

TOKEN = os.environ["BOT_TOKEN"]

offers = {}

# Сюда позже добавим ID синего эмодзи GRAM
GRAM_EMOJI_ID = os.getenv("GRAM_EMOJI_ID", "")


def parse_gift(text):
    match = re.search(
        r"(?:https?://)?t\.me/nft/([A-Za-z0-9_-]+)-(\d+)",
        text.strip(),
        re.IGNORECASE,
    )

    if match:
        collection = match.group(1)
        number = match.group(2)

        return {
            "title": f"{collection} #{number}",
            "url": f"https://t.me/nft/{collection}-{number}",
        }

    if text.startswith("https://"):
        return {
            "title": "NFT",
            "url": text,
        }

    return None


def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Создать оффер", callback_data="create")],
        [InlineKeyboardButton("Мои офферы", callback_data="my_offers")],
    ])


def offer_text(offer):
    buyer = offer["buyer"]
    price = offer["price"]
    currency = offer["currency"]
    title = offer["title"]

    if offer["status"] == "accepted":
        return (
            f"Предложение принято.\n\n"
            f"{title}\n"
            f"Цена: {price} {currency}\n\n"
            "Оплата не подтверждена."
        )

    if offer["status"] == "rejected":
        return "Предложение отклонено."

    return (
        f"Пользователь {buyer} предлагает Вам "
        f"{price} {currency} за подарок {title}."
    )


def offer_buttons(offer_id):
    offer = offers[offer_id]

    if offer["status"] != "pending":
        return None

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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Gift Market\n\nВыбери действие:",
        reply_markup=menu(),
    )


async def create_offer(update, context):
    context.user_data.clear()
    context.user_data["step"] = "gift"

    await update.effective_message.reply_text(
        "Отправь ссылку на подарок."
    )


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.message

    # Определяем ID кастомных эмодзи из пересланного сообщения.
    entities = list(message.entities or [])

    if message.caption_entities:
        entities.extend(message.caption_entities)

    emoji_ids = [
        entity.custom_emoji_id
        for entity in entities
        if entity.type == "custom_emoji"
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

    if step == "gift":
        gift = parse_gift(text)

        if not gift:
            await message.reply_text(
                "Отправь корректную ссылку на NFT."
            )
            return

        context.user_data["gift"] = gift
        context.user_data["step"] = "buyer"

        await message.reply_text(
            "Введи имя покупателя."
        )
        return

    if step == "buyer":
        if not 2 <= len(text) <= 40:
            await message.reply_text(
                "Имя должно содержать от 2 до 40 символов."
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
            price = Decimal(text.replace(",", "."))
        except InvalidOperation:
            await message.reply_text("Введи цену числом.")
            return

        if not price.is_finite() or price <= 0:
            await message.reply_text(
                "Цена должна быть положительной."
            )
            return

        offer_id = uuid.uuid4().hex[:12]
        gift = context.user_data["gift"]

        offers[offer_id] = {
            "owner": update.effective_user.id,
            "buyer": context.user_data["buyer"],
            "title": gift["title"],
            "url": gift["url"],
            "price": format(price, "f"),
            "currency": context.user_data["currency"],
            "status": "pending",
        }

        context.user_data.clear()

        await message.reply_text(
            "Оффер создан.\n\n"
            + offer_text(offers[offer_id])
            + "\n\n"
            f"Для отправки введи @{context.bot.username} "
            "в нужном чате и выбери оффер.",
            reply_markup=offer_buttons(offer_id),
        )
        return

    await message.reply_text(
        "Выбери действие:",
        reply_markup=menu(),
    )


async def inline_query(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = update.inline_query.from_user.id
    results = []

    for offer_id, offer in offers.items():
        if (
            offer["owner"] != user_id
            or offer["status"] != "pending"
        ):
            continue

        results.append(
            InlineQueryResultArticle(
                id=offer_id,
                title=offer["title"],
                description=(
                    f"{offer['price']} {offer['currency']}"
                ),
                input_message_content=InputTextMessageContent(
                    message_text=(
                        f"{offer['url']}\n\n"
                        f"{offer_text(offer)}"
                    ),
                    link_preview_options=LinkPreviewOptions(
                        is_disabled=False,
                        show_above_text=True,
                        prefer_large_media=True,
                    ),
                ),
                reply_markup=offer_buttons(offer_id),
            )
        )

    await update.inline_query.answer(
        results[:30],
        cache_time=0,
        is_personal=True,
    )


async def buttons(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
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
            offer for offer in offers.values()
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
                f"{offer['price']} {offer['currency']} "
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
            f"Валюта: {currency}\nВведи цену."
        )
        return

    if data.startswith(("accept:", "reject:")):
        action, offer_id = data.split(":", 1)
        offer = offers.get(offer_id)

        if not offer:
            await query.answer(
                "Оффер не найден.",
                show_alert=True,
            )
            return

        if offer["status"] != "pending":
            await query.answer(
                "На оффер уже ответили.",
                show_alert=True,
            )
            return

        if query.from_user.id == offer["owner"]:
            await query.answer(
                "Нельзя принять собственный оффер.",
                show_alert=True,
            )
            return

        offer["status"] = (
            "accepted" if action == "accept"
            else "rejected"
        )

        await query.answer(
            "Предложение принято. Оплата не подтверждена."
            if action == "accept"
            else "Предложение отклонено.",
            show_alert=True,
        )

        await query.edit_message_text(
            offer_text(offer),
            reply_markup=offer_buttons(offer_id),
        )

        try:
            await context.bot.send_message(
                chat_id=offer["owner"],
                text=(
                    f"Оффер: {offer['title']}\n"
                    f"Статус: {offer['status']}"
                ),
            )
        except Exception:
            logging.exception(
                "Не удалось отправить уведомление"
            )

        return

    await query.answer()


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("offer", create_offer))
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(CallbackQueryHandler(buttons))

    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
            handle_message,
        )
    )

    app.run_polling()


if __name__ == "__main__":
    main()
