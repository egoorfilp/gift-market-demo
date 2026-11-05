import os
import re
import uuid
import logging
from urllib.parse import urlparse

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
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

# Временное хранение офферов.
# Позже подключим PostgreSQL.
offers = {}


def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "Создать оффер", callback_data="create"
            )
        ],
        [
            InlineKeyboardButton(
                "Мои офферы", callback_data="my_offers"
            ),
            InlineKeyboardButton(
                "Проверить цену", callback_data="check_price"
            ),
        ],
        [
            InlineKeyboardButton(
                "Помощь", callback_data="help"
            )
        ],
    ])


def parse_gift(text):
    text = text.strip()

    match = re.search(
        r"(?:https?://)?t\.me/nft/([A-Za-z0-9_-]+)-(\d+)",
        text,
        re.IGNORECASE,
    )

    if match:
        collection = match.group(1)
        number = match.group(2)

        return {
            "name": f"{collection} #{number}",
            "url": f"https://t.me/nft/{collection}-{number}",
            "source": "Telegram",
        }

    if text.startswith(("https://", "http://")):
        parsed = urlparse(text)

        if parsed.scheme not in ("https", "http"):
            return None

        if not parsed.hostname:
            return None

        return {
            "name": "NFT-подарок",
            "url": text,
            "source": parsed.hostname,
        }

    return None


def offer_text(offer):
    status = offer["status"]

    if status == "pending":
        status_text = "Ожидает ответа"
    elif status == "accepted":
        status_text = "Предложение принято"
    elif status == "rejected":
        status_text = "Предложение отклонено"
    else:
        status_text = "Неизвестен"

    return (
        "🎁 ПРЕДЛОЖЕНИЕ О ПОКУПКЕ\n\n"
        f"Подарок: {offer['name']}\n"
        f"Площадка: {offer['source']}\n"
        f"Цена: {offer['price']} {offer['currency']}\n\n"
        f"Статус: {status_text}\n\n"
        "Принятие предложения не подтверждает "
        "получение оплаты или передачу NFT."
    )


def offer_keyboard(offer_id):
    offer = offers[offer_id]

    if offer["status"] == "pending":
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
            ],
            [
                InlineKeyboardButton(
                    "Посмотреть подарок",
                    url=offer["url"],
                )
            ],
        ])

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "Как это работает?",
                callback_data="deal_help",
            )
        ],
        [
            InlineKeyboardButton(
                "Посмотреть подарок",
                url=offer["url"],
            )
        ],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Gift Market\n\n"
        "Создавай предложения о покупке NFT-подарков "
        "и отправляй их прямо в Telegram.",
        reply_markup=main_menu(),
    )


async def begin_offer(update, context):
    context.user_data["step"] = "gift"

    await update.effective_message.reply_text(
        "Отправь ссылку на NFT-подарок.\n\n"
        "Поддерживаются ссылки Telegram и других площадок. "
        "Для некоторых сайтов название пока нужно будет "
        "уточнять вручную."
    )


async def offer_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await begin_offer(update, context)


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    step = context.user_data.get("step")
    text = update.message.text.strip()

    if step == "gift":
        gift = parse_gift(text)

        if not gift:
            await update.message.reply_text(
                "Не удалось распознать ссылку. "
                "Отправь полную ссылку на подарок."
            )
            return

        context.user_data["gift"] = gift
        context.user_data["step"] = "currency"

        await update.message.reply_text(
            f"Подарок: {gift['name']}\n\n"
            "Выбери валюту:",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "TON", callback_data="currency:TON"
                    ),
                    InlineKeyboardButton(
                        "GRAM", callback_data="currency:GRAM"
                    ),
                ]
            ]),
        )
        return

    if step == "price":
        price = text.replace(",", ".")

        try:
            value = float(price)
        except ValueError:
            await update.message.reply_text(
                "Введи цену числом, например: 20"
            )
            return

        if not 0 < value <= 1000000000:
            await update.message.reply_text(
                "Укажи положительную цену."
            )
            return

        gift = context.user_data["gift"]
        currency = context.user_data["currency"]

        offer_id = uuid.uuid4().hex[:12]

        offers[offer_id] = {
            "id": offer_id,
            "owner": update.effective_user.id,
            "name": gift["name"],
            "url": gift["url"],
            "source": gift["source"],
            "currency": currency,
            "price": price,
            "status": "pending",
        }

        context.user_data["step"] = None

        bot_username = context.bot.username

        await update.message.reply_text(
            "Предложение создано!\n\n"
            + offer_text(offers[offer_id])
            + "\n\n"
            "Чтобы отправить его другому человеку, "
            "открой нужный чат и введи:\n\n"
            f"@{bot_username}\n\n"
            "Выбери предложение из появившегося списка.",
            reply_markup=offer_keyboard(offer_id),
        )
        return

    await update.message.reply_text(
        "Выбери действие в меню:",
        reply_markup=main_menu(),
    )


async def inline_query(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = update.inline_query.from_user.id

    user_offers = [
        offer
        for offer in offers.values()
        if offer["owner"] == user_id
        and offer["status"] == "pending"
    ]

    results = []

    for offer in user_offers[:30]:
        results.append(
            InlineQueryResultArticle(
                id=offer["id"],
                title=offer["name"],
                description=(
                    f"{offer['price']} {offer['currency']}"
                ),
                input_message_content=InputTextMessageContent(
                    offer_text(offer)
                ),
                reply_markup=offer_keyboard(offer["id"]),
            )
        )

    await update.inline_query.answer(
        results,
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
        await begin_offer(update, context)
        return

    if data == "my_offers":
        await query.answer()

        user_offers = [
            o for o in offers.values()
            if o["owner"] == query.from_user.id
        ]

        if not user_offers:
            await query.message.reply_text(
                "У тебя пока нет предложений."
            )
            return

        lines = ["Мои предложения:\n"]

        for offer in user_offers[-15:]:
            lines.append(
                f"{offer['name']} — "
                f"{offer['price']} {offer['currency']} "
                f"({offer['status']})"
            )

        await query.message.reply_text(
            "\n".join(lines)
        )
        return

    if data == "check_price":
        await query.answer(
            "Автоматическую оценку подключим позже. "
            "Пока рыночные цены не проверяются.",
            show_alert=True,
        )
        return

    if data == "help":
        await query.answer(
            "Создай оффер, выбери валюту и цену, "
            "затем отправь предложение через inline-режим.",
            show_alert=True,
        )
        return

    if data == "deal_help":
        await query.answer(
            "Принятие оффера означает согласие с предложением. "
            "Оплату и передачу NFT необходимо подтвердить "
            "отдельно.",
            show_alert=True,
        )
        return

    if data.startswith("currency:"):
        currency = data.split(":", 1)[1]

        if context.user_data.get("step") != "currency":
            await query.answer(
                "Сначала создай новое предложение.",
                show_alert=True,
            )
            return

        context.user_data["currency"] = currency
        context.user_data["step"] = "price"

        await query.answer()

        await query.message.reply_text(
            f"Выбрана валюта: {currency}\n\n"
            "Введи предлагаемую цену числом.\n"
            "Например: 20"
        )
        return

    if data.startswith(("accept:", "reject:")):
        action, offer_id = data.split(":", 1)
        offer = offers.get(offer_id)

        if not offer:
            await query.answer(
                "Предложение не найдено.",
                show_alert=True,
            )
            return

        if offer["status"] != "pending":
            await query.answer(
                "На это предложение уже ответили.",
                show_alert=True,
            )
            return

        if query.from_user.id == offer["owner"]:
            await query.answer(
                "Нельзя принять собственное предложение.",
                show_alert=True,
            )
            return

        offer["status"] = (
            "accepted" if action == "accept"
            else "rejected"
        )

        await query.answer(
            "Предложение принято. "
            "Оплата ещё не подтверждена."
            if action == "accept"
            else "Предложение отклонено.",
            show_alert=True,
        )

        await query.edit_message_text(
            offer_text(offer),
            reply_markup=offer_keyboard(offer_id),
        )

        try:
            await context.bot.send_message(
                chat_id=offer["owner"],
                text=(
                    f"Ответ на предложение:\n\n"
                    f"{offer['name']}\n"
                    f"Статус: {offer['status']}"
                ),
            )
        except Exception:
            logging.info(
                "Не удалось отправить уведомление владельцу."
            )

        return

    await query.answer()


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("offer", offer_command))
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    app.run_polling()


if __name__ == "__main__":
    main()
