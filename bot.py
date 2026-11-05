import os
import re
import uuid
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

# Временное хранилище.
# При перезапуске Railway данные могут исчезнуть.
offers = {}


def menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎁 Создать предложение",
                callback_data="create",
            )
        ],
        [
            InlineKeyboardButton(
                "📋 Мои предложения",
                callback_data="my_offers",
            )
        ],
        [
            InlineKeyboardButton(
                "💎 Проверить цену",
                callback_data="price_info",
            ),
            InlineKeyboardButton(
                "ℹ️ Помощь",
                callback_data="help",
            ),
        ],
    ])


def parse_gift(text):
    text = text.strip()

    match = re.fullmatch(
        r"(?:https?://)?t\.me/nft/([A-Za-z0-9_-]+)-(\d+)/?",
        text,
        re.IGNORECASE,
    )

    if match:
        collection = match.group(1)
        number = match.group(2)

        name = re.sub(
            r"(?<=[a-z])(?=[A-Z])",
            " ",
            collection,
        )

        return {
            "name": name,
            "number": number,
            "title": f"{name} #{number}",
            "url": (
                f"https://t.me/nft/"
                f"{collection}-{number}"
            ),
            "source": "Telegram",
        }

    parsed = urlparse(text)

    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return None

    hostname = parsed.hostname.lower()

    if hostname in ("localhost",) or hostname.endswith(".local"):
        return None

    return {
        "name": "NFT-подарок",
        "number": "",
        "title": "NFT-подарок",
        "url": text,
        "source": hostname,
    }


def currency_text(offer):
    return (
        f"{offer['price']} "
        f"{offer['currency']}"
    )


def offer_text(offer):
    title = offer["title"]
    buyer = offer["buyer_name"]
    price = currency_text(offer)

    if offer["status"] == "pending":
        return (
            "🎁 ПРЕДЛОЖЕНИЕ О ПОКУПКЕ\n\n"
            f"Пользователь «{buyer}» предлагает "
            f"Вам {price} за подарок {title}.\n\n"
            "Имя покупателя указано создателем "
            "предложения и не подтверждено Telegram.\n\n"
            "Статус: ожидает ответа.\n\n"
            "Принятие предложения не означает "
            "получение оплаты."
        )

    if offer["status"] == "accepted":
        return (
            "✅ ПРЕДЛОЖЕНИЕ ПРИНЯТО\n\n"
            f"Подарок: {title}\n"
            f"Предложенная цена: {price}\n\n"
            "Статус: ожидается завершение сделки.\n\n"
            "Оплата не подтверждена. "
            "Передача подарка не подтверждена."
        )

    if offer["status"] == "rejected":
        return (
            "❌ ПРЕДЛОЖЕНИЕ ОТКЛОНЕНО\n\n"
            f"Подарок: {title}\n"
            f"Цена: {price}"
        )

    return "Предложение недоступно."


def offer_buttons(offer_id):
    offer = offers[offer_id]

    if offer["status"] == "pending":
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✖️ Отклонить",
                    callback_data=f"reject:{offer_id}",
                ),
                InlineKeyboardButton(
                    "✔️ Принять",
                    callback_data=f"accept:{offer_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🎁 ПОКАЗАТЬ ПОДАРОК",
                    url=offer["url"],
                )
            ],
        ])

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "ℹ️ Как это работает?",
                callback_data="deal_help",
            )
        ],
        [
            InlineKeyboardButton(
                "🎁 ПОКАЗАТЬ ПОДАРОК",
                url=offer["url"],
            )
        ],
    ])


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "🎁 GIFT MARKET\n\n"
        "Создавай предложения о покупке "
        "коллекционных подарков Telegram.\n\n"
        "Выбери действие:",
        reply_markup=menu(),
    )


async def create_offer(update, context):
    context.user_data.clear()
    context.user_data["step"] = "gift"

    await update.effective_message.reply_text(
        "🎁 СОЗДАНИЕ ПРЕДЛОЖЕНИЯ\n\n"
        "Шаг 1/4\n\n"
        "Отправь ссылку на NFT-подарок.\n\n"
        "Например:\n"
        "https://t.me/nft/PlushPepe-2687"
    )


async def offer_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await create_offer(update, context)


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    text = update.message.text.strip()
    step = context.user_data.get("step")

    if step == "gift":
        gift = parse_gift(text)

        if not gift:
            await update.message.reply_text(
                "Не удалось распознать ссылку.\n"
                "Отправь полную HTTPS-ссылку."
            )
            return

        context.user_data["gift"] = gift
        context.user_data["step"] = "buyer"

        await update.message.reply_text(
            "✅ Ссылка получена!\n\n"
            f"Подарок: {gift['title']}\n"
            f"Источник: {gift['source']}\n\n"
            "Шаг 2/4\n\n"
            "Введи отображаемое имя покупателя.\n\n"
            "Оно будет помечено как введённое "
            "вручную, а не проверенное Telegram."
        )
        return

    if step == "buyer":
        if not 2 <= len(text) <= 40:
            await update.message.reply_text(
                "Имя должно содержать "
                "от 2 до 40 символов."
            )
            return

        context.user_data["buyer_name"] = text
        context.user_data["step"] = "currency"

        await update.message.reply_text(
            "Шаг 3/4\n\n"
            f"Имя покупателя: {text}\n\n"
            "Выбери валюту:",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "💎 TON",
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
        normalized = text.replace(",", ".")

        try:
            price = Decimal(normalized)
        except InvalidOperation:
            await update.message.reply_text(
                "Введи цену числом.\n"
                "Например: 20"
            )
            return

        if (
            not price.is_finite()
            or price <= 0
            or price > 1000000000
        ):
            await update.message.reply_text(
                "Укажи корректную положительную цену."
            )
            return

        gift = context.user_data["gift"]
        buyer = context.user_data["buyer_name"]
        currency = context.user_data["currency"]

        offer_id = uuid.uuid4().hex[:12]

        offers[offer_id] = {
            "id": offer_id,
            "owner": update.effective_user.id,
            "buyer_name": buyer,
            "title": gift["title"],
            "name": gift["name"],
            "number": gift["number"],
            "url": gift["url"],
            "source": gift["source"],
            "price": format(price, "f"),
            "currency": currency,
            "status": "pending",
        }

        context.user_data.clear()

        username = context.bot.username

        await update.message.reply_text(
            "✅ ПРЕДЛОЖЕНИЕ СОЗДАНО!\n\n"
            + offer_text(offers[offer_id])
            + "\n\n"
            "Чтобы отправить предложение, "
            "открой нужный чат и введи:\n\n"
            f"@{username}\n\n"
            "Затем выбери предложение "
            "из появившегося списка.",
            reply_markup=offer_buttons(offer_id),
            link_preview_options=LinkPreviewOptions(
                is_disabled=True
            ),
        )
        return

    await update.message.reply_text(
        "Выбери действие:",
        reply_markup=menu(),
    )


async def inline_query(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = update.inline_query.from_user.id

    user_offers = [
        offer
        for offer in offers.values()
        if (
            offer["owner"] == user_id
            and offer["status"] == "pending"
        )
    ]

    results = []

    for offer in user_offers[:30]:
        # Telegram сам решает, сможет ли
        # показать предпросмотр страницы NFT.
        content = (
            f"{offer['url']}\n\n"
            f"{offer_text(offer)}"
        )

        results.append(
            InlineQueryResultArticle(
                id=offer["id"],
                title=offer["title"],
                description=currency_text(offer),
                input_message_content=InputTextMessageContent(
                    message_text=content,
                    link_preview_options=LinkPreviewOptions(
                        is_disabled=False,
                        show_above_text=True,
                        prefer_large_media=True,
                    ),
                ),
                reply_markup=offer_buttons(offer["id"]),
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
                "У тебя пока нет предложений."
            )
            return

        lines = ["📋 МОИ ПРЕДЛОЖЕНИЯ\n"]

        for offer in user_offers[-15:]:
            lines.append(
                f"🎁 {offer['title']}\n"
                f"💰 {currency_text(offer)}\n"
                f"Статус: {offer['status']}\n"
            )

        await query.message.reply_text(
            "\n".join(lines)
        )
        return

    if data == "price_info":
        await query.answer(
            "Рыночные цены пока не подключены. "
            "Бот не будет придумывать стоимость NFT.",
            show_alert=True,
        )
        return

    if data == "help":
        await query.answer(
            "Создай предложение, введи имя "
            "покупателя, выбери валюту и цену. "
            "Затем отправь оффер через inline-режим.",
            show_alert=True,
        )
        return

    if data == "deal_help":
        await query.answer(
            "Принятие предложения не подтверждает "
            "оплату или передачу подарка. "
            "Проверяй фактическое выполнение сделки.",
            show_alert=True,
        )
        return

    if data.startswith("currency:"):
        currency = data.split(":", 1)[1]

        if currency not in ("TON", "GRAM"):
            await query.answer(
                "Неизвестная валюта.",
                show_alert=True,
            )
            return

        if context.user_data.get("step") != "currency":
            await query.answer(
                "Сначала начни создание предложения.",
                show_alert=True,
            )
            return

        context.user_data["currency"] = currency
        context.user_data["step"] = "price"

        await query.answer()

        await query.message.reply_text(
            "Шаг 4/4\n\n"
            f"Валюта: {currency}\n\n"
            "Введи предлагаемую цену.\n"
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

        offer["status"] = (
            "accepted"
            if action == "accept"
            else "rejected"
        )

        await query.answer(
            (
                "Предложение принято. "
                "Оплата ещё не подтверждена."
            )
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
                    "🔔 ОБНОВЛЕНИЕ ПРЕДЛОЖЕНИЯ\n\n"
                    f"Подарок: {offer['title']}\n"
                    f"Цена: {currency_text(offer)}\n"
                    f"Статус: {offer['status']}"
                ),
            )
        except Exception:
            logging.info(
                "Не удалось отправить уведомление."
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
